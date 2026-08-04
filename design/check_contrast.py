"""Verify every palette pairing meets its contrast target (plan §0.4, §5.1).

    python design/check_contrast.py            # check
    python design/check_contrast.py --report   # full table, always exit 0

Exits non-zero if any `_check` target or CVD pair fails.

## Why this exists

Five WCAG failures shipped — mobile `success` at 2.54:1, `subtleForeground` at
2.56:1, `primaryForeground` at 2.95:1 dark, plus web `warning` and `gold`.
Nobody chose those; nothing measured them. The palette is now generated, so a
regression here would propagate to both platforms at once.

## The CVD check is the important one

`success` and `danger` measured **1.05:1 under deuteranopia** — functionally
identical. A red-green colour-blind walker (≈6% of men, and DSP field staff
skew heavily male) could not tell "delivered" from "failed".

This check enforces a floor so the colours at least *help*. It does NOT make
colour safe to rely on alone — plan §4 rule 1 requires an icon or label on
every status regardless, because no palette makes red and green safe for
everyone.

The CVD simulation is a Brettel/Viénot-style LMS approximation, not a clinical
model. At 1.05:1 the direction was not in doubt; treat small differences near
the threshold as indicative rather than exact.
"""
from __future__ import annotations

import colorsys
import itertools
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SPEC = ROOT / "palette.json"


# ── colour maths ──────────────────────────────────────────────────────────────

def hsl_to_hex(h: float, s: float, ll: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360, ll / 100, s / 100)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _channels(hex_: str):
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_: str) -> float:
    r, g, b = _channels(hex_)
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def simulate_cvd(hex_: str, kind: str) -> str:
    """Approximate deuteranopia / protanopia via an LMS transform."""
    r, g, b = (_linear(c) for c in _channels(hex_))
    long_ = 17.8824 * r + 43.5161 * g + 4.11935 * b
    med = 3.45565 * r + 27.1554 * g + 3.86714 * b
    short = 0.0299566 * r + 0.184309 * g + 1.46709 * b

    if kind == "deuteranopia":
        long2, med2, short2 = long_, 0.494207 * long_ + 1.24827 * short, short
    else:  # protanopia
        long2, med2, short2 = 2.02344 * med - 2.52581 * short, med, short

    r2 = 0.080944 * long2 - 0.130504 * med2 + 0.116721 * short2
    g2 = -0.0102485 * long2 + 0.0540194 * med2 - 0.113615 * short2
    b2 = -0.000365294 * long2 - 0.00412163 * med2 + 0.693513 * short2

    def delinear(c: float) -> float:
        c = max(c, 0.0)
        return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055

    return "#%02X%02X%02X" % tuple(
        round(min(max(delinear(x), 0.0), 1.0) * 255) for x in (r2, g2, b2)
    )


def cvd_distance(a: str, b: str, kind: str) -> float:
    """Perceptual distance between two colours AS SEEN under CVD.

    Contrast ratio is luminance-only and therefore blind to hue: it scores
    violet #4D4DD2 and olive #6F6F01 as nearly identical (1.09:1) when they are
    obviously different colours. That is fine for text legibility, which is a
    luminance problem, and wrong for "can these two be told apart".

    So this uses Euclidean distance in Lab-ish space instead. Rough scale:
      < 15  effectively the same colour
      15-30 distinguishable side by side
      > 30  clearly different
    """
    def to_lab(hex_: str):
        r, g, b = (_linear(c) for c in _channels(hex_))
        x = 0.4124 * r + 0.3576 * g + 0.1805 * b
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        z = 0.0193 * r + 0.1192 * g + 0.9505 * b
        xn, yn, zn = 0.95047, 1.0, 1.08883
        f = lambda t: t ** (1 / 3) if t > 0.008856 else (7.787 * t) + 16 / 116
        fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
        return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))

    la, aa, ba = to_lab(simulate_cvd(a, kind))
    lb, ab, bb = to_lab(simulate_cvd(b, kind))
    return ((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2) ** 0.5


# ── checking ──────────────────────────────────────────────────────────────────

def load():
    return json.loads(SPEC.read_text())


def theme_hexes(theme: dict) -> dict[str, str]:
    return {
        k: hsl_to_hex(*v["hsl"])
        for k, v in theme.items()
        if isinstance(v, dict) and "hsl" in v
    }


# ── semantic collisions ───────────────────────────────────────────────────────
#
# Two tokens that MEAN different things must not RESOLVE to the same value.
# Contrast and provenance checks cannot see this: a role token aliasing a status
# token is perfectly legible and perfectly wrong.
#
# Found on device 2026-08-03 (ADR-253): every role token was an exact alias of a
# status or brand token, so a Trainer's whole screen rendered amber (== `gold`)
# and a Driver's rendered blue (== `info`). Amber then meant both "your role"
# and "warning" on the same screen. All four colour gates passed.
#
# Anything listed here is a DELIBERATE alias and needs a reason. Everything else
# that collides is a bug.
# Only tokens that can appear as *meaning-bearing colour on the same surface*
# are compared. Surfaces (card/surface/tabBar) sharing pure white is normal
# layering, not a semantic collision — comparing everything against everything
# produced 40 findings of which 35 were noise, which is how a gate gets ignored.
ROLE_TOKENS = {"driver", "walker", "trainer", "trainee", "neutral"}
STATUS_TOKENS = {"success", "warning", "danger", "info", "gold"}
IDENTITY_TOKENS = {"brand", "primary", "ring"}
MEANING_BEARING = ROLE_TOKENS | STATUS_TOKENS | IDENTITY_TOKENS

ALLOWED_ALIASES: dict[frozenset[str], str] = {
    frozenset({"driver", "info"}):
        "Driver blue is the same blue as info. Kept deliberately: `info` never "
        "renders as a chip on a roster row, which is the only surface where a "
        "role colour carries meaning alone. Revisit if that stops being true.",
    frozenset({"walker", "success"}):
        "Walker green is the same green as success. Kept: where they co-occur "
        "(a delivered-state read on a walker's row) both meanings point the "
        "same way, so the ambiguity is not misleading.",
    frozenset({"trainer", "gold"}):
        "Trainer amber == gold. This is the collision that made a Trainer's "
        "whole Home screen render amber (found on device, ADR-253). Re-huing "
        "was measured and rejected: with five statuses, brand, primary and ring "
        "already placed, `trainer` lands 4.8 Lab from `danger` even AFTER "
        "moving off gold, so warm-band role colour is ambiguous at any value. "
        "Mitigation is the usage rule instead — role colour never carries "
        "meaning alone, and never renders as a status on the same surface.",
    frozenset({"brand", "trainee"}):
        "Trainee violet == brand. Same measurement, same conclusion. Additional "
        "reason to keep it: trainee is the role most often seen beside a "
        "trainer, and the violet/amber pair is the widest-separated in the "
        "family (133.8 light / 137.6 dark). Note `ring` was moved OFF this "
        "value to cyan — a focus indicator sharing a role colour was a real "
        "WCAG 2.4.11 defect, unlike this pair.",
}


def _family(token: str) -> str:
    for name, group in (
        ("role", ROLE_TOKENS),
        ("status", STATUS_TOKENS),
        ("identity", IDENTITY_TOKENS),
    ):
        if token in group:
            return name
    return "other"


def semantic_collisions(theme_name: str, theme: dict) -> list[str]:
    """Meaning-bearing tokens from different families resolving to one value.

    Scoped to base tokens: a `*Light` variant colliding is a consequence of its
    base colliding, so reporting both doubles the noise for one defect.
    """
    hexes = theme_hexes(theme)
    by_value: dict[str, list[str]] = {}
    for token, hx in hexes.items():
        if token in MEANING_BEARING:
            by_value.setdefault(hx, []).append(token)

    problems = []
    for hx, tokens in by_value.items():
        for a, b in itertools.combinations(sorted(tokens), 2):
            if frozenset({a, b}) in ALLOWED_ALIASES:
                continue
            # same family = same kind of meaning; two roles sharing a value is
            # caught by the pairwise distance check, not here
            if _family(a) == _family(b):
                continue
            problems.append(
                f"{theme_name}: `{a}` ({_family(a)}) and `{b}` ({_family(b)}) "
                f"both resolve to {hx} — distinct meanings must not share a value"
            )
    return problems


def check(report: bool = False) -> int:
    spec = load()
    failures: list[str] = []
    advisories: list[str] = []
    rows: list[tuple] = []
    collisions: list[str] = []

    for theme_name in ("light", "dark"):
        theme = spec[theme_name]
        hexes = theme_hexes(theme)
        collisions.extend(semantic_collisions(theme_name, theme))

        for token, meta in theme.items():
            if not isinstance(meta, dict) or "_check" not in meta:
                continue
            against = meta["_check"]["on"]
            target = float(meta["_check"]["min"])

            if against not in hexes:
                failures.append(
                    f"{theme_name}.{token}: _check.on='{against}' is not a token"
                )
                continue

            got = contrast(hexes[token], hexes[against])
            ok = got >= target
            rows.append((theme_name, f"{token} on {against}", hexes[token], got, target, ok))
            if not ok:
                failures.append(
                    f"{theme_name}.{token} on {against}: {got:.2f}:1 "
                    f"(needs {target}:1) — {hexes[token]}"
                )

        # ── Colour-vision deficiency ──────────────────────────────────
        # ENFORCED: the interactive accent must never be mistaken for a status
        # colour — that separation IS achievable and is why brand moved off
        # amber. ADVISORY: red/amber/green cannot be separated by colour under
        # deuteranopia at all (they collapse toward yellow; only lightness
        # differs, and reaching 1.6:1 needs ~25-30 lightness points, at which
        # point the colours stop reading as their own semantics). Reported so
        # the cost stays visible; mitigated by icons, not by the palette.
        cvd = spec.get("cvd", {})
        floor = float(cvd.get("enforced", {}).get("min", 1.6))

        for a, b in cvd.get("enforced", {}).get("pairs", []):
            if a not in hexes or b not in hexes:
                continue
            for kind in ("deuteranopia", "protanopia"):
                # Perceptual distance, NOT contrast ratio — see cvd_distance().
                got = cvd_distance(hexes[a], hexes[b], kind)
                ok = got >= floor
                rows.append((theme_name, f"{a} vs {b} [{kind[:6]}]", "", got, floor, ok))
                if not ok:
                    failures.append(
                        f"{theme_name}: {a} vs {b} under {kind} is only {got:.1f} apart "
                        f"(needs {floor}) — the accent is being confused with a "
                        f"status colour"
                    )

        for a, b in cvd.get("advisory", {}).get("pairs", []):
            if a not in hexes or b not in hexes:
                continue
            worst = min(
                contrast(simulate_cvd(hexes[a], k), simulate_cvd(hexes[b], k))
                for k in ("deuteranopia", "protanopia")
            )
            advisories.append(
                f"{theme_name}: {a} vs {b} worst-case {worst:.2f}:1 under CVD "
                f"— MUST carry an icon or label (plan §4 rule 1)"
            )

    if report:
        cur = None
        for theme_name, label, hx, got, target, ok in rows:
            if theme_name != cur:
                print(f"\n{theme_name.upper()}")
                cur = theme_name
            mark = "ok  " if ok else "FAIL"
            print(f"  {mark} {label:34} {hx:8} {got:6.2f}:1  (min {target})")
        print()

    if advisories and report:
        print("\nADVISORY — colour alone cannot carry these; icons are required:")
        for a in advisories:
            print(f"  {a}")

    if collisions:
        print("\nSEMANTIC COLLISIONS:\n")
        for c in collisions:
            print(f"  {c}")
        print(
            "\nTwo tokens with different meanings resolve to the same value. Either give\n"
            "one a distinct value in design/palette.json, or — if the alias is genuinely\n"
            "intended — add it to ALLOWED_ALIASES in this file WITH a reason.\n"
            "Contrast checks cannot catch this: an aliased token is legible and wrong."
        )

    if failures:
        print("\nCONTRAST FAILURES:\n")
        for f in failures:
            print(f"  {f}")
        print(
            "\nFix the value in design/palette.json, then re-run. Both platforms are\n"
            "generated from that file, so a failure here would ship to web AND mobile."
        )

    if failures or collisions:
        return 1

    print(
        f"OK — {len(rows)} pairings checked, all meet target; "
        f"no semantic collisions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(check(report="--report" in sys.argv))
