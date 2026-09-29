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

# ADR-473. The reverse direction, which this gate did not check.
#
# Field arrays forward their own `key` through `onHelp={setHelpKey}`, so the
# key is never a literal and the checks above cannot see it. When ADR-473
# removed ten `scorecard_*_target` fields, their ten drawer entries were
# ORPHANED -- present, unreachable, and describing columns that no longer
# existed. Every check passed.
#
# An orphan is not as loud as a missing entry (nobody opens an empty panel) but
# it is how a drawer fills with help for a UI that has moved on, and it is
# exactly the stale documentation this cluster keeps finding.
FIELD_KEY_RE = re.compile(r"key:\s*'([a-z0-9_]+)'")

# Entries written ahead of the surface that will use them. Listed BY NAME rather
# than by prefix so staging one is a deliberate act that shows up in review, and
# an entry that never gets its surface stays visible here instead of hiding
# behind a wildcard.
#
# EMPTY as of ADR-473 D6: the scorecard targets surface shipped, so the five
# metric_* entries are reachable and their allowance was retired rather than
# left as a permanent exemption. A stale entry here is the same orphan problem
# one level up -- an allowance nobody revisits allows forever.
STAGED_ENTRIES: set[str] = set()

# Keys built at runtime from data, e.g. setHelpKey(`metric_${key}`) over a list
# of metrics. The regexes above only see literals, so without this the reachable
# set misses them and every such entry reads as an orphan.
#
# A PREFIX is right here and wrong for STAGED_ENTRIES, and the difference is
# worth stating: this says "a surface builds these keys from data", which is a
# structural fact about the code. That said "trust me, it is coming", which
# needed a name so it could expire.
TEMPLATE_KEY_RES = (
    re.compile(r"setHelpKey\(\s*`([a-z_]+)\$\{"),
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

    # ── orphans: an entry no field or literal can reach ──────────────────
    reachable = set()
    for path in sorted(SRC.rglob("*.tsx")):
        text = path.read_text()
        if path != DRAWER:
            for r in USE_RES:
                reachable.update(m.group(1) for m in r.finditer(text))
            reachable.update(FIELD_KEY_RE.findall(text))

    # Prefixes that a surface builds keys from at runtime.
    template_prefixes = set()
    for path in sorted(SRC.rglob("*.tsx")):
        if path == DRAWER:
            continue
        text = path.read_text()
        for r in TEMPLATE_KEY_RES:
            template_prefixes.update(m.group(1) for m in r.finditer(text))

    built_at_runtime = {
        e for e in entries if any(e.startswith(p) for p in template_prefixes)
    }

    orphans = sorted(entries - reachable - STAGED_ENTRIES - built_at_runtime)
    if orphans:
        print("FAIL: HELP_CONTENT entries nothing can reach\n")
        for key in orphans:
            print(f"  '{key}' has no field and no literal referencing it")
        print("\nRemove the entry, or re-key it onto the field that replaced it.")
        return 1

    # Says "literal" deliberately: a key built at runtime
    # (setHelpKey(someVar)) cannot be checked here, and an OK line that implied
    # total coverage would be the more dangerous output.
    print(f"OK: {used_total} literal help key(s) across the app, all resolvable "
          f"({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
