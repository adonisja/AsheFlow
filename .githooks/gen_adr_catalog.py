#!/usr/bin/env python3
"""
Regenerate docs/ADR-CATALOG.md from the ADR and LEARNING_GUIDE files.

WHY THIS EXISTS
---------------
CLAUDE.md tells every session to read the catalog FIRST — it is the ~5k-token
index that stands in for the ~850k-token corpus. But the generator it names was
not in the repo, so nothing regenerated the file: on 2026-08-14 the catalog
stopped at ADR-253 while the repo had decisions through ADR-271. Eighteen
decisions, including four from that week, were invisible to the documented
lookup path — the exact failure the index is supposed to prevent.

A stale index is worse than no index: it answers confidently and wrongly, so
nobody thinks to look further.

FORMAT (matches the file it replaces, so diffs stay reviewable)
  `<number> <title>` per decision, with `[status]` appended for anything not
  settled. Unmarked means accepted/implemented/resolved.

Title comes from frontmatter `title:`, falling back to the filename. Status
comes from frontmatter `status:`; anything outside the settled set is surfaced
as a marker so a reader knows to open the file rather than trust the line.

Run from the repo root:  python .githooks/gen_adr_catalog.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "docs" / "decisions"
GUIDE = ROOT / "docs" / "LEARNING_GUIDE.md"
OUT = ROOT / "docs" / "ADR-CATALOG.md"

# Statuses that need no marker. Anything else is flagged so the reader opens
# the file instead of trusting a one-line summary of an unsettled decision.
SETTLED = {"accepted", "implemented", "resolved", "shipped", "done"}


def frontmatter(text: str) -> dict:
    """Parse the leading --- block. Deliberately minimal: these files use flat
    `key: value` frontmatter, and pulling in PyYAML for that would make a hook
    depend on a package the repo does not otherwise need."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def collect_decisions() -> list[tuple[int, str]]:
    rows = []
    claimed: dict[int, list[str]] = {}
    for path in sorted(DECISIONS.glob("ADR-*.md")):
        m = re.match(r"ADR-(\d+)", path.name)
        if not m:
            continue
        num = int(m.group(1))
        fm = frontmatter(path.read_text(encoding="utf-8"))
        # A renumbered redirect stub keeps the OLD filename on purpose, so that
        # wikilinks written before the split still resolve. It does not CLAIM
        # the number -- the decision that kept it does -- so it is excluded from
        # the duplicate check below or every resolved collision reports forever.
        tags = fm.get("tags") or ""
        if "renumbered" not in tags:
            claimed.setdefault(num, []).append(path.name)
        title = fm.get("title") or path.stem.split("-", 2)[-1].replace("-", " ")
        # Strip a leading "ADR-N — " if the title repeats it.
        title = re.sub(r"^ADR-\d+\s*[—-]\s*", "", title).strip()
        status = (fm.get("status") or "unknown").lower()
        if status not in SETTLED:
            title = f"{title} [{status}]"
        rows.append((num, title))

    # Two decisions under one number make every bare `ADR-N` citation ambiguous,
    # and check_adr_coverage.py -- which resolves a citation by globbing
    # `ADR-N-*.md` -- is satisfied by whichever file it finds first. So a commit
    # cites a number that does not identify a decision, and the gate passes.
    #
    # This happened twice before anyone noticed: ADR-405 (bag sort zones vs
    # truck-room access) and ADR-464 (redaction registry vs setup gating), the
    # second cited in 36 places across both meanings. Found by running `uniq -d`
    # over the filenames during an unrelated docs audit, never by recall --
    # which is why it is a gate now and not a habit.
    dupes = {n: names for n, names in claimed.items() if len(names) > 1}
    if dupes:
        print("gen_adr_catalog: DUPLICATE ADR NUMBERS", file=sys.stderr)
        for n, names in sorted(dupes.items()):
            print(f"  ADR-{n} is claimed by {len(names)} files:", file=sys.stderr)
            for nm in names:
                print(f"    {nm}", file=sys.stderr)
        print("\nGive the later decision the next free number, add\n"
              "`renumbered_from: <old>` to its frontmatter, and leave a stub at the\n"
              "old filename with `tags: [adr, renumbered]` so existing wikilinks\n"
              "still resolve. Then reclassify the bare `ADR-<old>` citations --\n"
              "they split across BOTH meanings and each one must be read.",
              file=sys.stderr)
        raise SystemExit(1)

    return rows


def collect_lessons() -> list[str]:
    if not GUIDE.exists():
        return []
    return re.findall(r"^## Lesson\s*[—-]\s*(.+)$",
                      GUIDE.read_text(encoding="utf-8"), re.M)


def main() -> int:
    decisions = collect_decisions()
    lessons = collect_lessons()
    if not decisions:
        print("gen_adr_catalog: no ADRs found — refusing to write an empty catalog",
              file=sys.stderr)
        return 1

    width = max(len(str(n)) for n, _ in decisions)
    lines = [
        "---",
        "tags: [index, generated]",
        "---",
        "",
        "# ADR catalog",
        "",
        "**Generated by `.githooks/gen_adr_catalog.py` — do not edit by hand.**",
        "",
        "A compact index of every decision in this project, for agent context. "
        "Read this to find the relevant ADR, then read that ADR's file for detail. "
        "Reading the whole corpus costs ~850k tokens; this file costs ~5k. "
        "Dates and full metadata are in each file's frontmatter.",
        "",
        "Format: `number title`. An unsettled decision is marked `[status]` — "
        "superseded, proposed, planned, parked, in-progress, or unknown. "
        "Anything unmarked is accepted/implemented/resolved.",
        "",
        "## Decisions",
        "",
    ]
    lines += [f"{str(n).zfill(width)} {t}" for n, t in decisions]
    lines += [
        "",
        "## Reusable lessons",
        "",
        f"{len(lessons)} lessons in `LEARNING_GUIDE.md`. Search that file for "
        "the full text of any that looks relevant.",
        "",
    ]
    lines += [f"- {t}" for t in lessons]
    lines += [
        "",
        "## How to search",
        "",
        "```bash",
        "grep -ril '<topic>' docs/decisions/     # find ADRs by content",
        "grep -n '<topic>' docs/LEARNING_GUIDE.md  # find the reusable lesson",
        "ls docs/journals/ | grep <YYYY-MM-DD>   # find what was actually built",
        "```",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"gen_adr_catalog: {len(decisions)} decisions, {len(lessons)} lessons "
          f"-> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
