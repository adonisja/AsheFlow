#!/usr/bin/env python3
"""Dangling wikilinks and hollowed-out status notes in the ADR/journal corpus.

Two failure modes, both of which have already happened here:

1. A `[[ADR-NNN-Title|ADR-NNN]]` link whose target file does not exist. CLAUDE.md
   records the precedent: ADR-243 was cited by three ADRs for days before anyone
   noticed it had never been written. Most real cases are subtler — the ADR exists
   but under a different filename, so the number is right and the link is dead.

2. A `status_note` that is valid YAML and empty of information. On 2026-08-29 a
   regex quote-repair truncated two notes to the single character "I". Every
   syntactic check passed: it parses, the field exists, the catalog regenerates.
   Checking for MALFORMED files could never have caught it, which is why this
   checks for CONTENTLESS ones.

Exits non-zero on findings so a hook can gate on it.
"""
import glob
import os
import re
import sys

DOC_GLOBS = ("docs/decisions/*.md", "docs/journals/*.md")

# The truncation incident produced a 1-character note. An older convention in this
# corpus writes legitimately terse notes ("Implemented - 2026-07-15", 22 chars), so
# a length threshold alone flags 18 healthy files and gets the check ignored.
#
# What separates them: a real note, however short, contains a WORD. A truncation is
# a fragment cut mid-token. So require at least two alphanumeric runs of 2+ chars.
MIN_NOTE_CHARS = 8

# [[target]] or [[target|label]]. Coordinate pairs like [[lng, lat]] appear inside
# code samples and are not links.
#
# The backslash in the alias branch is NOT optional. Inside a markdown table a
# link must be written [[Target\|Alias]] or the pipe splits the cell, and the
# previous pattern -- [^\]|]+? -- stopped at the pipe while KEEPING the escape,
# so every table link resolved to "ADR-292-Manual-RTS-Entry\" and was reported
# dangling. Five of them were, wrongly, for months.
#
# This is exactly the trap that produced the 2026-08-29 incident: a repair
# script "fixed" the documents to satisfy the broken pattern and destroyed five
# working links. The pattern was the bug both times. Match the escape here and
# strip it, rather than ever touching the files.
LINK = re.compile(r"\[\[([^\]|]+?)\\?(?:\|[^\]]*)?\]\]")


def _targets_on_disk() -> set[str]:
    return {
        os.path.splitext(os.path.basename(p))[0]
        for g in DOC_GLOBS
        for p in glob.glob(g)
    }


def main() -> int:
    known = _targets_on_disk()
    dangling: list[tuple[str, str]] = []
    hollow: list[tuple[str, str]] = []

    for g in DOC_GLOBS:
        for path in sorted(glob.glob(g)):
            text = open(path, errors="ignore").read()
            base = os.path.basename(path)

            for target in LINK.findall(text):
                target = target.strip()
                # Not a document reference — coordinates, placeholders in examples.
                if "," in target or not target.startswith(("ADR-", "20")):
                    continue
                if target not in known:
                    dangling.append((base, target))

            # Frontmatter only — the first block. Prose quoting a broken note
            # (this incident's own journal does) is not itself a broken note.
            fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            if fm:
                m = re.search(r'^status_note:\s*"(.*?)"\s*$', fm.group(1), re.M | re.S)
                if m:
                    note = m.group(1).strip()
                    words = re.findall(r"[A-Za-z0-9]{2,}", note)
                    if len(note) < MIN_NOTE_CHARS or len(words) < 2:
                        hollow.append((base, note[:40]))

    if hollow:
        print(f"{len(hollow)} status_note(s) parse but say nothing:")
        for base, val in hollow:
            print(f"  {base}: status_note: {val!r}")
        print("  A note this short is almost certainly truncation, not brevity.")
        print("  Check git history in AsheFlow-private BEFORE rewriting it.\n")

    if dangling:
        print(f"{len(dangling)} dangling wikilink(s):")
        seen: dict[str, list[str]] = {}
        for base, target in dangling:
            seen.setdefault(target, []).append(base)
        for target, srcs in sorted(seen.items(), key=lambda kv: -len(kv[1])):
            # The usual cause: right number, wrong filename.
            num = target.split("-")[1] if target.startswith("ADR-") and "-" in target[4:] else None
            hint = ""
            if num:
                actual = glob.glob(f"docs/decisions/ADR-{num}-*.md")
                if actual:
                    hint = f"  -> did you mean {os.path.splitext(os.path.basename(actual[0]))[0]}?"
            print(f"  [[{target}]] ({len(srcs)}x){hint}")

    if not dangling and not hollow:
        print(f"OK — {len(known)} documents, no dangling links, no hollow status notes")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
