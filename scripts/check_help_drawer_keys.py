#!/usr/bin/env python3
"""Every setHelpKey('x') has an entry in the drawer's HELP_CONTENT.

The drawer renders `HELP_CONTENT[fieldKey]`. A key with no entry does not
throw -- it renders NOTHING, so the `?` button opens an empty panel and reads
as broken rather than as a missing string. Nothing in TypeScript catches this:
`fieldKey` is `string | null`, so any string type-checks.

Also flags a page that hand-rolls a help popover instead of using the shared
drawer. Register.tsx was the last one (ADR-456); the whole point of a shared
component is that the next one is caught here rather than at a walkthrough.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
DRAWER = SRC / "components" / "ui" / "SettingsHelpDrawer.tsx"

ENTRY_RE = re.compile(r"^  ([a-z_][a-z0-9_]*): \{$", re.M)
# Two spellings in use: a literal passed straight to setHelpKey, and a
# `helpKey="x"` prop on a section header that forwards it (CrewPins,
# Preferences). Both are literals and both are checkable.
USE_RES = (
    re.compile(r"setHelpKey\(\s*'([^']+)'\s*\)"),
    re.compile(r'\bhelpKey="([^"]+)"'),
)


def main() -> int:
    if not DRAWER.exists():
        print(f"FAIL: {DRAWER.relative_to(ROOT)} is missing.")
        return 1

    entries = set(ENTRY_RE.findall(DRAWER.read_text()))
    if not entries:
        print("FAIL: no HELP_CONTENT entries parsed — has the file's shape changed?")
        return 1

    problems: list[str] = []
    used_total = 0

    for path in sorted(SRC.rglob("*.tsx")):
        if path == DRAWER:
            continue
        text = path.read_text()
        for m in (m for r in USE_RES for m in r.finditer(text)):
            used_total += 1
            key = m.group(1)
            if key not in entries:
                line = text[: m.start()].count("\n") + 1
                problems.append(
                    f"  {path.relative_to(ROOT)}:{line}: help key '{key}' "
                    "has no HELP_CONTENT entry (the drawer would open empty)"
                )

    if problems:
        print("FAIL: help drawer keys without content\n")
        print("\n".join(problems))
        print(f"\nAdd the entry to {DRAWER.relative_to(ROOT)}.")
        return 1

    # Says "literal" deliberately: a key built at runtime
    # (setHelpKey(someVar)) cannot be checked here, and an OK line that implied
    # total coverage would be the more dangerous output.
    print(f"OK: {used_total} literal help key(s) across the app, all resolvable "
          f"({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
