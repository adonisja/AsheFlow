"""Fail on NEW raw colour literals outside the token layer (plan 0.8).

    python design/check_colour_literals.py             # gate
    python design/check_colour_literals.py --report    # full list, exit 0
    python design/check_colour_literals.py --baseline  # re-record the baseline

## Why this exists

Every other Phase 0 guarantee got a mechanism. "No raw colour literals" did
not, and ~390 accumulated (plan §2.6) — including 51 in the theme file itself,
which shipped a second palette that made 0.2's "reconciled to one value" only
half true.

The lesson from ADR-247/249 is the same each time: a rule that lives only in a
document is one nobody runs.

## Why a script and not an ESLint rule

CI runs no lint on either platform today, so an ESLint rule would not gate
anything. This plugs into the existing `design-tokens` job beside the contrast
and token-sync checks — one place, both platforms, no new infrastructure.

## Baselined, deliberately

~390 existing violations cannot be fixed in one commit without an unreviewable
diff. So the baseline is recorded per file and the gate fails only when a count
goes UP or a new file appears. During the Phase 4 sweep the counts ratchet down
and `--baseline` re-records them; the number can never grow.

This is the honest trade: it does not pretend the debt is gone, and it does
guarantee it stops growing.

## Exceptions (plan §2.6)

Allowlisted BY REASON, never by silence — an exception with no stated cause is
how a rule decays into theatre.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
BASELINE = ROOT / "colour_literal_baseline.json"

# Raw hex, rgb()/rgba(), and Tailwind's own palette utilities. The Tailwind ones
# matter as much as hex: `bg-red-500` bypasses the token layer just as
# completely, and there are more of them on web than raw values.
HEX = re.compile(r"['\"]#[0-9a-fA-F]{3,8}['\"]")
RGB = re.compile(r"\brgba?\(\s*\d[\d.,\s%]*\)")
TAILWIND = re.compile(
    r"\b(?:bg|text|border|ring|fill|stroke|from|to|via|divide|outline|shadow)-"
    r"(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|"
    r"violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-\d{2,3}\b"
)

SCAN = [
    (REPO / "frontend" / "src", (".tsx", ".ts")),
    (REPO / "mobile" / "src", (".tsx", ".ts")),
]

# Files that are ALLOWED to hold literals, each with the reason it is exempt.
EXEMPT: dict[str, str] = {
    "frontend/src/generated-tokens.css":
        "generated FROM the palette — it IS the token layer",
    "mobile/src/theme/generated-colors.ts":
        "generated FROM the palette — it IS the token layer",
    "frontend/src/pages/PrintLoadSheets.tsx":
        "printed output has no theme; print CSS needs literal values",
}

# Specific literals that are legitimate anywhere: third-party brand colours we
# do not own, and pure black for light-theme shadows (dark theme must use
# elevate(), never a black shadow on a near-black surface).
EXEMPT_VALUES = {
    "'#5865F2'": "Discord brand blue — a third party's colour, not ours to theme",
    '"#5865F2"': "Discord brand blue",
    "'#4285F4'": "Google brand blue",
    "'#000'":    "light-theme shadowColor; dark theme uses elevate()",
    "'#000000'": "light-theme shadowColor",
}


def scan() -> dict[str, int]:
    counts: dict[str, int] = {}
    for root, suffixes in SCAN:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in suffixes or not path.is_file():
                continue
            rel = str(path.relative_to(REPO))
            if rel in EXEMPT:
                continue
            text = path.read_text()
            hits = HEX.findall(text) + RGB.findall(text) + TAILWIND.findall(text)
            hits = [h for h in hits if h not in EXEMPT_VALUES]
            if hits:
                counts[rel] = len(hits)
    return counts


def load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text()).get("files", {})


def write_baseline(counts: dict[str, int]) -> None:
    BASELINE.write_text(json.dumps({
        "$comment": [
            "Per-file colour-literal counts, recorded by",
            "design/check_colour_literals.py (plan 0.8).",
            "",
            "The gate fails when a count goes UP or a new file appears. It does",
            "NOT fail on the existing debt — ~390 violations cannot land in one",
            "reviewable commit. Counts ratchet DOWN during the Phase 4 sweep and",
            "this file is re-recorded; the number can never grow.",
            "",
            "Do not hand-edit. Run --baseline after genuinely removing literals.",
        ],
        "total": sum(counts.values()),
        "files": dict(sorted(counts.items())),
    }, indent=2) + "\n")


def main(argv: list[str]) -> int:
    counts = scan()

    if "--baseline" in argv:
        write_baseline(counts)
        print(f"baseline recorded: {sum(counts.values())} literals "
              f"across {len(counts)} files")
        return 0

    if "--report" in argv:
        for f, n in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {n:4}  {f}")
        print(f"\n  {sum(counts.values())} literals across {len(counts)} files")
        return 0

    base = load_baseline()
    if not base:
        print("No baseline. Run: python design/check_colour_literals.py --baseline")
        return 1

    grew = [(f, base.get(f, 0), n) for f, n in counts.items() if n > base.get(f, 0)]

    if grew:
        print("\nNEW COLOUR LITERALS — use the token layer:\n")
        for f, was, now in sorted(grew, key=lambda x: -(x[2] - x[1])):
            print(f"  {f}")
            print(f"      {was} → {now}  (+{now - was})")
        print(
            "\nColour belongs in design/palette.json, reached via useColors() on\n"
            "mobile or a Tailwind token class on web. A literal does not follow a\n"
            "palette change and is invisible to the contrast gate — which is how\n"
            "a 2.82:1 button label shipped (plan §2.6).\n"
            "\nGenuinely unavoidable? Add it to EXEMPT/EXEMPT_VALUES in this file\n"
            "WITH the reason."
        )
        return 1

    shrunk = sum(base.get(f, 0) - n for f, n in counts.items() if n < base.get(f, 0))
    shrunk += sum(v for f, v in base.items() if f not in counts)
    total = sum(counts.values())
    msg = f"OK — {total} literals, none new"
    if shrunk:
        msg += f" ({shrunk} removed since the baseline — run --baseline to record)"
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
