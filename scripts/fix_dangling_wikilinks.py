#!/usr/bin/env python3
"""Repair dangling [[ADR-NNN-Title]] wikilinks by resolving on the ADR NUMBER.

An ADR's title gets edited after other documents already link to it, and the old
link silently rots -- Obsidian renders it as a dead link and nothing in CI notices.
ADR-243 was cited by three ADRs for days before anyone spotted it had never been
written, so a dangling link is not always cosmetic.

The number is the stable identifier; the title is not. This rewrites
[[ADR-260-Old-Title|ADR-260]] to the file that actually is ADR-260, preserving any
|alias. It refuses to guess: a link whose number has no file is REPORTED, never
rewritten, because that is the case that might mean a missing ADR.

Usage:
  python scripts/fix_dangling_wikilinks.py            # report only
  python scripts/fix_dangling_wikilinks.py --write    # apply
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "docs"
LINK = re.compile(r"\[\[([^\]|#]+)(\|[^\]]*)?\]\]")
ADR_NUM = re.compile(r"^ADR-0*(\d+)\b")


def main() -> int:
    write = "--write" in sys.argv
    files = sorted(ROOT.rglob("*.md"))
    stems = {p.stem for p in files}

    # ADR number -> canonical stem. Built from filenames, the source of truth.
    by_number: dict[int, str] = {}
    for p in files:
        m = ADR_NUM.match(p.stem)
        if m:
            by_number[int(m.group(1))] = p.stem

    fixed: list[str] = []
    unresolved: list[str] = []

    for f in files:
        text = f.read_text(errors="ignore")
        changed = False

        def repl(m: re.Match) -> str:
            nonlocal changed
            target, alias = m.group(1).strip(), (m.group(2) or "")
            if target in stems:
                return m.group(0)

            # A trailing backslash is usually an ESCAPED PIPE inside a markdown
            # table -- [[Target\|Alias]] -- where the backslash is required so the
            # pipe is not read as a column separator. The link is fine; only this
            # regex mis-reads it. Stripping the backslash silently breaks the table,
            # so leave those alone entirely.
            if target.endswith("\\"):
                return m.group(0)

            num = ADR_NUM.match(target)
            if not num:
                return m.group(0)          # not an ADR link; leave it alone
            canonical = by_number.get(int(num.group(1)))
            if not canonical:
                unresolved.append(f"{f.relative_to(ROOT)}: {target!r} (no ADR-{num.group(1)} file)")
                return m.group(0)

            changed = True
            fixed.append(f"{f.relative_to(ROOT)}: {target!r} -> {canonical!r}")
            return f"[[{canonical}{alias}]]"

        new = LINK.sub(repl, text)
        if changed and write:
            f.write_text(new)

    for line in fixed:
        print(f"  {'FIXED ' if write else 'WOULD FIX '}{line}")
    for line in unresolved:
        print(f"  UNRESOLVED {line}", file=sys.stderr)

    print(f"\n  {len(fixed)} repairable, {len(unresolved)} unresolved"
          f"{'' if write else '  (dry run -- pass --write to apply)'}")
    # Unresolved links are reported, not fatal: some are prose or placeholders.
    return 0


if __name__ == "__main__":
    sys.exit(main())
