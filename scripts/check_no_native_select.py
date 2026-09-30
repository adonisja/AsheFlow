#!/usr/bin/env python3
"""Fail on any native <select> in frontend/src (ADR-484).

WHY THIS EXISTS
SelectMenu (components/ui/SelectMenu.tsx) has been the house dropdown since
ADR-433. In the time it reached 6 files, 47 native <select> elements
accumulated across 24 others -- and 25 of those had no <label> and no
aria-label, so they were an accessibility defect as well as a style one.

A house component with no gate is a preference, not a standard.

COMMENTS ARE STRIPPED FIRST, deliberately. The first audit of this reported 58
selects; eleven of them were the word "<select>" inside comments explaining why
a native select had been REPLACED. A gate that trips on its own rationale gets
deleted.

Usage:
    python3 scripts/check_no_native_select.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "frontend/src"

# The house control itself, and the searchable route-log popup (ADR-484's
# consequences section) -- neither contains a native select, but both discuss
# one at length.
EXEMPT = {"ui/SelectMenu.tsx", "walkerlog/Dropdown.tsx"}

_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"^\s*//.*$", re.M)
_SELECT = re.compile(r"<select[\s>]")


def strip_comments(src: str) -> str:
    """Remove comments so prose about <select> cannot be mistaken for one.

    Blanks them to same-length whitespace rather than deleting, so reported
    line numbers still match the file.
    """
    src = _BLOCK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
    return _LINE.sub(lambda m: " " * len(m.group(0)), src)


def main() -> int:
    hits = []
    for path in sorted(ROOT.rglob("*.tsx")):
        rel = str(path.relative_to(ROOT))
        if any(rel.endswith(e) for e in EXEMPT):
            continue
        clean = strip_comments(path.read_text())
        for m in _SELECT.finditer(clean):
            hits.append((rel, clean[: m.start()].count("\n") + 1))

    if not hits:
        print("OK — no native <select> in frontend/src")
        return 0

    print(f"{len(hits)} native <select> element(s) found:\n")
    for rel, line in hits:
        print(f"  {rel}:{line}")
    print(
        "\nUse <SelectMenu> from components/ui/SelectMenu.tsx (ADR-484).\n"
        "It takes value / options / placeholder / onChange, and ariaLabel --\n"
        "pass that one: half the selects this replaced had no accessible name."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
