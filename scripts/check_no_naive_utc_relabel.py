#!/usr/bin/env python3
"""Fail on a local wall-clock time relabelled as UTC (ADR-485 D18).

WHY THIS EXISTS
CompanyConfig and the building rows store times as naive `Time` columns,
documented as "read in the company's own timezone". Two ways of turning one
into an instant are wrong:

    datetime.combine(d, t).replace(tzinfo=timezone.utc)   # relabels: 4-5h off
    datetime.combine(d, t).astimezone(timezone.utc)       # uses the SERVER zone

The second is the quieter one -- accidentally right wherever the server runs
UTC, silently wrong everywhere else. Both are replaced by
`local_date.company_datetime(tz, d, t)` / `company_midnight(tz, d)`.

NOT flagged: `.replace(tzinfo=timezone.utc)` on a value that genuinely IS UTC --
a naive timestamp read back from the database. That is correct and common.
Only a `combine(...)` immediately followed by one of the two forms is a defect.

Usage:
    python3 scripts/check_no_naive_utc_relabel.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "backend/app"

# combine(...) -> .replace(tzinfo=timezone.utc) or .astimezone(...), allowing
# the call to wrap across lines.
_BAD = re.compile(
    r"(?:datetime|_dt)\.combine\((?:[^()]|\([^()]*\))*\)\s*"
    r"\.(?:replace\(\s*tzinfo\s*=\s*(?:timezone\.)?utc\s*\)|astimezone\()",
    re.S,
)
_COMMENT = re.compile(r"^\s*#.*$", re.M)

# The module that DEFINES the fix. Its docstring shows both wrong forms by
# design, and its own body is the one correct implementation. A gate that trips
# on its own rationale is a gate people delete (the same exemption the
# native-<select> gate needs for the comments explaining it).
EXEMPT = {"services/local_date.py"}


def main() -> int:
    hits = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(str(path).endswith(e) for e in EXEMPT):
            continue
        src = _COMMENT.sub("", path.read_text())
        for m in _BAD.finditer(src):
            line = src[: m.start()].count("\n") + 1
            hits.append((path.relative_to(ROOT.parent.parent), line,
                         " ".join(m.group(0).split())[:90]))

    if not hits:
        print("OK — no naive local time relabelled as UTC")
        return 0

    print(f"{len(hits)} naive-UTC relabel(s):\n")
    for rel, line, snippet in hits:
        print(f"  {rel}:{line}\n      {snippet}")
    print(
        "\nUse local_date.company_datetime(tz, d, t) or company_midnight(tz, d).\n"
        "A stored Time is LOCAL; attaching UTC relabels it instead of converting\n"
        "(ADR-485 D18), and .astimezone() on a naive value uses the SERVER zone."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
