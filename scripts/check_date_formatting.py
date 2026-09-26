#!/usr/bin/env python3
"""Dates reach the user through frontend/src/utils/date.ts, not Intl directly.

WHY A GATE AND NOT A TEST: the frontend has no test runner, so a .test.ts file
would sit in the tree and never execute -- the green-while-blind failure
ADR-311 is about. This runs in CI as its own step, like check_ui_copy_style.py.

Two failures it exists to prevent, both of which shipped before the shared
formatter existed:

  1. `toLocaleDateString()` with no arguments renders "9/26/2026" -- ambiguous
     outside the US and visually identical to an ID.
  2. `new Date('2026-09-26')` parses as UTC midnight and renders in local time,
     so a calendar date displays as the PREVIOUS DAY anywhere west of
     Greenwich. Every call site that hand-patched this with `+ 'T00:00:00'` was
     evidence of the same bug being rediscovered.

The formatter also renders a nullish timestamp as an em dash. A raw
`new Date(null)` is epoch 0 -- a valid Date that prints "Dec. 31, 1969" and
looks like data rather than a missing value.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
FORMATTER = SRC / "utils" / "date.ts"

# date.ts is the one place allowed to call Intl -- it IS the wrapper.
EXEMPT = {FORMATTER}

BANNED = [
    (re.compile(r"\.toLocaleDateString\s*\("),
     "toLocaleDateString",
     "use formatDate / formatDateShort / formatDayHeader from utils/date"),
    # Catches the `+ 'T00:00:00'` UTC workaround, but ONLY where the result is
    # being FORMATTED. Constructing a Date from a date-only string to read
    # `getDay()` off it -- weekend shading, a heatmap column -- is legitimate
    # and needs the suffix for exactly the reason the comments there say.
    # Flagging that too would push someone to silence the gate rather than fix
    # a real finding, which is how a gate stops being believed.
    (re.compile(
        r"""format(?:Date|DateTime|DayHeader|DayHeaderFull|DateShort"""
        r"""|DateTimeShort|MonthDay)\s*\([^)]*\+\s*['"]T\d\d:\d\d:\d\d['"]"""
        r"""|toLocaleDateString\s*\([^)]*\)\s*$"""),
     "redundant 'T00:00:00' suffix on a formatted date",
     "pass the date string straight to the formatter — it parses in local time"),
]


def main() -> int:
    if not FORMATTER.exists():
        print(f"FAIL: {FORMATTER.relative_to(ROOT)} is missing.")
        return 1

    violations: list[str] = []
    for path in sorted([*SRC.rglob("*.ts"), *SRC.rglob("*.tsx")]):
        if path in EXEMPT:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith(("*", "//")):
                continue  # a comment explaining the rule is not a violation
            for pattern, what, remedy in BANNED:
                if pattern.search(line):
                    violations.append(
                        f"  {path.relative_to(ROOT)}:{lineno}: {what} — {remedy}"
                    )

    if violations:
        print("FAIL: dates must be formatted through frontend/src/utils/date.ts\n")
        print("\n".join(violations))
        print(
            f"\n{len(violations)} violation(s). A bare toLocaleDateString renders "
            "'9/26/2026';\na date-only string parsed as UTC renders the previous day."
        )
        return 1

    print("OK: all date rendering goes through utils/date.ts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
