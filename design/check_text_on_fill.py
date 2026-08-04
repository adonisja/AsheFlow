"""Fail on text whose contrast against its own button fill is below WCAG AA.

    python design/check_text_on_fill.py             # gate
    python design/check_text_on_fill.py --report    # every pair, exit 0

## Why this exists

`check_contrast.py` verifies the PALETTE — pairs declared in `palette.json`. It
cannot see a screen that ignores the palette and hardcodes `color: '#fff'` on a
token-coloured fill.

That shipped three times (ADR-255):

    Commit Sort — build routes    2.82:1   RouteSortScreen
    Submit Survey                 2.82:1   DriverSurveyScreen
    Submit                        2.82:1   ScheduleChangesScreen

All three on `c.primary`, which in DARK theme is a *light* navy (#7E95F1).
White on it fails; `primaryForeground` is 6.66:1. On light theme the same code
is fine — which is exactly why it survived review.

## Why this scanner and not the earlier greps

Two previous attempts disagreed wildly (59 vs 2) because neither resolved style
references:

- A proximity grep ("a `c.X` fill within N lines of a `'#fff'`") over-attributes
  across unrelated declarations in the same StyleSheet.
- An inline-JSX-only matcher misses the dominant React Native idiom entirely:
  `submitBtn: { backgroundColor: c.primary }` and `submitText: { color: '#fff' }`
  declared as siblings, applied to a parent and its child.

So this resolves both directions and requires agreement:

1. **JSX walk** — find an element applying a style with a `backgroundColor`,
   then the first text style used inside that element.
2. **Sibling names** — `Xbtn`/`XBtn` paired with `XText`/`XBtnText` in the same
   StyleSheet.

Both ran clean at 2 findings after the fixes, which is what makes the number
trustworthy. A count you cannot reproduce two ways is not a mandate to edit
(LEARNING_GUIDE: "An untrusted count is not a mandate to mass-edit").

## Known limits

Only literal-white foregrounds on token-named fills are checked. A hardcoded
fill with a hardcoded text colour, or a colour computed at runtime, is out of
scope — `check_colour_literals.py` is the gate that stops those accumulating.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
MOBILE = ROOT.parent / "mobile" / "src"
MIN_RATIO = 4.5

_spec = importlib.util.spec_from_file_location("cc", ROOT / "check_contrast.py")
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

PALETTE = json.loads((ROOT / "palette.json").read_text())
STYLE_RE = re.compile(r"(\w+)\s*:\s*\{([^{}]*)\}")
BG_RE = re.compile(r"backgroundColor:\s*c\.(\w+)")
FG_TOKEN_RE = re.compile(r"\bcolor:\s*c\.(\w+)")
FG_HEX_RE = re.compile(r"\bcolor:\s*'(#[0-9a-fA-F]{3,8})'")
APPLY_RE = re.compile(r"style=\{\[?\s*s\.(\w+)")


def token_hex(theme: str, name: str) -> str | None:
    v = PALETTE[theme].get(name)
    return cc.hsl_to_hex(*v["hsl"]) if isinstance(v, dict) and "hsl" in v else None


def normalise(hex_: str) -> str | None:
    """`#fff` -> `#ffffff`; drop an alpha suffix. None if unparseable."""
    body = hex_.lstrip("#")
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    return "#" + body[:6] if len(body) >= 6 else None


def is_white(hex_: str) -> bool:
    return (normalise(hex_) or "").lower() == "#ffffff"


def parse_styles(src: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for m in STYLE_RE.finditer(src):
        name, body = m.group(1), m.group(2)
        entry: dict[str, str] = {}
        if bg := BG_RE.search(body):
            entry["bg_token"] = bg.group(1)
        if fg := FG_HEX_RE.search(body):
            entry["fg_hex"] = fg.group(1)
        elif fg := FG_TOKEN_RE.search(body):
            entry["fg_token"] = fg.group(1)
        if entry:
            out[name] = entry
    return out


def failures_for(path: pathlib.Path) -> list[tuple]:
    src = path.read_text()
    styles = parse_styles(src)
    found: set[tuple] = set()

    def record(holder: str, bg_token: str, fg_hex: str, line: int):
        for theme in ("light", "dark"):
            bg = token_hex(theme, bg_token)
            fg = normalise(fg_hex)
            if not bg or not fg:
                continue
            ratio = cc.contrast(bg, fg)
            if ratio < MIN_RATIO:
                found.add((round(ratio, 2), theme, holder, bg_token, line))

    # 1. JSX walk: element with a fill -> first text style inside it
    for m in APPLY_RE.finditer(src):
        holder = styles.get(m.group(1))
        if not holder or "bg_token" not in holder:
            continue
        chunk = src[m.end():m.end() + 900]
        for tm in re.finditer(r"style=\{\[?\s*s\.(\w+)|color:\s*'(#[0-9a-fA-F]{3,8})'", chunk):
            if tm.group(1):
                child = styles.get(tm.group(1)) or {}
                fg_hex = child.get("fg_hex")
            else:
                fg_hex = tm.group(2)
            if fg_hex and is_white(fg_hex):
                record(m.group(1), holder["bg_token"], fg_hex,
                       src[:m.start()].count("\n") + 1)
            break   # the first text style inside is the label

    # 1b. Inline fill: style={[s.badge, { backgroundColor: c.danger }]} with the
    # label's colour living in a separate style. The fill is not in the
    # StyleSheet at all, so pass 1 cannot see it — this is how a 3.12:1 unread
    # badge survived the first version of this gate.
    for m in re.finditer(
        r"style=\{\[([^\]]*?)\{[^}]*?backgroundColor:\s*c\.(\w+)[^}]*\}\s*\]", src
    ):
        refs = re.findall(r"s\.(\w+)", m.group(1))
        bg_token = m.group(2)
        chunk = src[m.end():m.end() + 400]
        for tm in re.finditer(r"style=\{\[?\s*s\.(\w+)", chunk):
            child = styles.get(tm.group(1)) or {}
            if (fg := child.get("fg_hex")) and is_white(fg):
                record(refs[0] if refs else f"inline:{bg_token}", bg_token, fg,
                       src[:m.start()].count("\n") + 1)
            break

    # 2. Sibling names: Xbtn + XText / XBtnText
    for name, entry in styles.items():
        if "bg_token" not in entry:
            continue
        base = re.sub(r"(Btn|btn|Button)$", "", name)
        for cand in (f"{name}Text", f"{base}Text", f"{base}BtnText", f"{base}btnText"):
            sibling = styles.get(cand)
            if sibling and (fg := sibling.get("fg_hex")) and is_white(fg):
                idx = src.find(f"{name}:")
                record(name, entry["bg_token"], fg,
                       src[:idx].count("\n") + 1 if idx >= 0 else 0)
    return sorted(found)


def check(report: bool = False) -> int:
    rows: list[tuple] = []
    seen: set[tuple] = set()
    for f in sorted(MOBILE.rglob("*.tsx")):
        rel = str(f.relative_to(MOBILE))
        for r in failures_for(f):
            # Both detection methods find the same defect from different angles.
            # Report it once: a gate that prints two lines per bug is a gate
            # whose count nobody trusts.
            key = (rel, r[2], r[1])          # file, style name, theme
            if key in seen:
                continue
            seen.add(key)
            rows.append((rel,) + r)

    if report:
        print(f"{len(rows)} text-on-fill pair(s) below {MIN_RATIO}:1\n")
        for path, ratio, theme, holder, tok, line in rows:
            print(f"  {ratio:5.2f}:1  {theme:5}  {path}:{line}  s.{holder} on c.{tok}")
        return 0

    if rows:
        print(f"\nTEXT-ON-FILL CONTRAST FAILURES ({len(rows)}):\n")
        for path, ratio, theme, holder, tok, line in rows:
            print(f"  {ratio:5.2f}:1  {theme:5}  {path}:{line}")
            print(f"         s.{holder} is c.{tok}; its label is hardcoded white")
        print(
            "\nUse the matching foreground token (usually `c.primaryForeground`)\n"
            "instead of '#fff'. Dark-theme fills are LIGHT, so white-on-fill is a\n"
            "light-theme habit that silently fails in dark mode."
        )
        return 1

    print("OK — no hardcoded white on a token fill below 4.5:1")
    return 0


if __name__ == "__main__":
    raise SystemExit(check(report="--report" in sys.argv))
