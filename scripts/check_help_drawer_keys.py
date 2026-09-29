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
# ADR-473 moved scorecard targets into company_metric_targets; these five carry
# the metric explanations verified against Amazon's guides (ADR-472) and attach
# to the targets surface when it ships.
STAGED_ENTRIES = {
    "metric_pod",
    "metric_dsb_dpmo",
    "metric_fico",
    "metric_speeding_rate",
    "metric_signsignal_rate",
}


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

    orphans = sorted(entries - reachable - STAGED_ENTRIES)
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
