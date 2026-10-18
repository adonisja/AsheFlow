#!/usr/bin/env python3
"""Refuse a push whose commits cite an ADR that has no documentation.

CLAUDE.md requires four artifacts per change -- ADR, journal, LEARNING_GUIDE
lesson, and a deep dive (ADR-501) -- and says to write the ADR *before*
implementing. That rule has been in
the file the whole time and was skipped twice in three days (ADR-354, ADR-365).
Both were found by grepping `git log` against `docs/decisions/`, never by recall.

So this is the grep, run automatically. It does not make anyone remember the
rule; it makes forgetting it fail loudly at the moment of pushing, which is the
last point where fixing it is cheap.

WHAT IT CANNOT CATCH
--------------------
A commit that cites no ADR at all. Detecting "this change deserved an ADR" needs
judgment about the change, and a check that guesses would either miss the real
cases or cry wolf on typo fixes until it was disabled. This catches the
narrower, unambiguous failure: a commit that NAMES a decision record which does
not exist.

Both real lapses were of exactly that kind.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "docs" / "decisions"
JOURNALS = ROOT / "docs" / "journals"
GUIDE = ROOT / "docs" / "LEARNING_GUIDE.md"
DEEP_DIVES = ROOT / "docs" / "deep-dives"

# ADR-501: the nine parts every deep dive carries. Presence, not depth: a small
# fix's part may be one line saying why it is empty, but the author must have
# DECIDED about it, which a missing heading shows they did not.
DEEP_DIVE_PARTS = range(1, 10)
PART_HEADING = re.compile(r"^## Part (\d)\b", re.MULTILINE)

ADR_IN_SUBJECT = re.compile(r"\bADR-(\d{3})\b")

# ADR-536: depth, not just headings. ADR-528..534's docs passed the structural
# check above while being summaries (547-1,504-word deep dives against a
# 12,232-word calibration). These are FLOORS that catch the summary shape --
# they cannot certify a good doc. Applied from ADR-535 on: the older corpus
# predates the standard, and failing it would make ALLOW_UNDOCUMENTED routine.
DEPTH_FROM = 535   # ADR-535 was written under the new standard; gate it too
DEEP_DIVE_MIN_WORDS = 1200
LESSON_MIN_WORDS = 500
CASE_FRAME = ("symptom", "why it stayed invisible", "diagnosis", "lesson")
WIKILINK = re.compile(r"\[\[(ADR-[^\]|]+)")
CALIBRATION = ("docs/deep-dives/ADR-487-D5-Push-Notifications.md (deep dive); "
               "'## Lesson — Partition a shared model by who may see it (ADR-483)' (lesson)")


def commits_being_pushed(argv: list[str]) -> list[str]:
    """Subjects of the commits this push would publish.

    Git feeds a pre-push hook `<local ref> <local sha> <remote ref> <remote sha>`
    on stdin. Reading that is exact, but the hook also has to work when someone
    runs this script by hand -- so a range can be passed as argv, and the
    fallback is the last commit.
    """
    if len(argv) > 1:
        rng = argv[1]
    else:
        stdin = "" if sys.stdin.isatty() else sys.stdin.read().strip()
        rng = None
        for line in stdin.split("\n"):
            parts = line.split()
            if len(parts) != 4:
                continue
            local_sha, remote_sha = parts[1], parts[3]
            if local_sha == "0" * 40:      # deleting a branch
                return []
            if remote_sha == "0" * 40:     # new branch: check its recent commits
                rng = f"{local_sha}~20..{local_sha}"
            else:
                rng = f"{remote_sha}..{local_sha}"
            break
        if not rng:
            rng = "HEAD~1..HEAD"

    try:
        out = subprocess.run(
            ["git", "log", "--format=%h|%s", rng],
            capture_output=True, text=True, cwd=ROOT, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        # An unresolvable range (a fresh clone, a rewritten history) must not
        # block a push. Failing open here is correct: this check exists to catch
        # a habit lapse, not to gate correctness.
        return []
    return [l for l in out.strip().split("\n") if l]


def _frontmatter_feature(text: str) -> str:
    """The `feature:` line of a deep dive's YAML frontmatter, or ''."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    head = text[3:end] if end != -1 else ""
    for line in head.splitlines():
        if line.startswith("feature:"):
            return line
    return ""


def deep_dive_gap(number: str) -> str | None:
    """Why ADR-<number> lacks a complete deep dive, or None if it has one (ADR-501).

    A deep dive COVERS an ADR by identity, never by mention: its filename starts
    `ADR-<number>-`, or its frontmatter `feature:` line names it as a whole token.
    Mentions do not count. The push deep dive cites ADR-311 and ADR-486 in
    passing, and must not satisfy them forever.
    """
    if not DEEP_DIVES.is_dir():
        return "a deep dive in docs/deep-dives/ (the directory does not exist)"
    token = re.compile(rf"\bADR-{number}\b")
    candidates = []
    for path in sorted(DEEP_DIVES.glob("*.md")):
        text = path.read_text(errors="ignore")
        if path.name.startswith(f"ADR-{number}-") or token.search(_frontmatter_feature(text)):
            candidates.append((path, text))
    if not candidates:
        return f"a deep dive in docs/deep-dives/ (ADR-{number}-*.md, or `feature: ADR-{number}`)"

    # Several may cover one ADR; any COMPLETE one satisfies it.
    best_missing = None
    for path, text in candidates:
        present = {int(n) for n in PART_HEADING.findall(text)}
        absent = [n for n in DEEP_DIVE_PARTS if n not in present]
        if not absent:
            return None
        if best_missing is None or len(absent) < len(best_missing[1]):
            best_missing = (path, absent)
    path, absent = best_missing
    return (f"{path.relative_to(ROOT)} is incomplete: no "
            + ", ".join(f"'## Part {n}'" for n in absent)
            + " (a part may be one line saying why it is empty, but its heading must be there)")


def _covering_deep_dives(number: str) -> list[tuple[Path, str]]:
    token = re.compile(rf"\bADR-{number}\b")
    out = []
    if DEEP_DIVES.is_dir():
        for path in sorted(DEEP_DIVES.glob("*.md")):
            text = path.read_text(errors="ignore")
            if path.name.startswith(f"ADR-{number}-") or token.search(_frontmatter_feature(text)):
                out.append((path, text))
    return out


def _part(text: str, n: int) -> str:
    """The body of '## Part n', up to the next '## Part'."""
    m = re.search(rf"^## Part {n}\b.*$", text, re.MULTILINE)
    if not m:
        return ""
    nxt = re.search(r"^## Part \d\b", text[m.end():], re.MULTILINE)
    return text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]


def _has_wrong_right(text: str) -> bool:
    return bool(re.search(r"\bWRONG\b", text)) and bool(re.search(r"\bRIGHT\b", text))


def _deep_dive_depth_problems(text: str) -> list[str]:
    problems = []
    words = len(text.split())
    if words < DEEP_DIVE_MIN_WORDS:
        problems.append(f"{words} words (floor {DEEP_DIVE_MIN_WORDS}; a floor, not the standard)")
    casebook = _part(text, 5)
    first_case = casebook.find("### Case")
    if first_case == -1:
        problems.append("Part 5 has no '### Case' entries")
    else:
        if not re.search(r"^\s*\|.*\|", casebook[:first_case], re.MULTILINE):
            problems.append("Part 5 does not open with a summary table (# | where | one line | found by)")
        cases = re.split(r"(?=^### Case)", casebook[first_case:], flags=re.MULTILINE)
        for case in (c for c in cases if c.startswith("### Case")):
            title = case.splitlines()[0][4:60]
            lower = case.lower()
            absent = [f for f in CASE_FRAME if f not in lower]
            if absent:
                problems.append(f"case '{title}' lacks: " + ", ".join(absent))
        if not _has_wrong_right(casebook):
            problems.append("Part 5 has no WRONG/RIGHT pair")
        if "```" not in casebook:
            problems.append("Part 5 has no fenced block of real output or code")
    if "as climbed" not in _part(text, 6).lower():
        problems.append("Part 6 does not record the ladder 'as climbed'")
    broken = sorted({n for n in WIKILINK.findall(text) if not (DECISIONS / f"{n}.md").exists()})
    if broken:
        problems.append("broken wikilinks: " + ", ".join(broken))
    return problems


def _lesson_text(number: str) -> str:
    guide = GUIDE.read_text(errors="ignore") if GUIDE.exists() else ""
    sections = re.split(r"\n(?=## )", guide)
    return "\n".join(s for s in sections
                     if s.startswith("## Lesson") and re.search(rf"ADR-{number}\)", s.splitlines()[0]))


def _lesson_depth_problems(text: str) -> list[str]:
    problems = []
    words = len(text.split())
    if words < LESSON_MIN_WORDS:
        problems.append(f"{words} words (floor {LESSON_MIN_WORDS})")
    lower = text.lower()
    if not re.search(r"^###.*recognition", text, re.MULTILINE | re.IGNORECASE):
        problems.append("no recognition-cue section")
    if not _has_wrong_right(text):
        problems.append("no WRONG/RIGHT pair")
    if not re.search(r"^\*[^*\n].*[^*\n]\*\s*$|\*Principle", text, re.MULTILINE):
        problems.append("no italic principle sentence")
    # In BODY text, not headings: a "### How it was verified" heading with
    # nothing under it is the hollow-section shape this gate exists to stop
    # (the first draft of this check accepted exactly that; its test caught it).
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#")).lower()
    if not re.search(r"\bprobe|\b\d+ (failed|passed)\b|\bfails? \d+\b|\b\d+ tests? fail|\bverified\b", body):
        problems.append("no verification evidence in the text (probe results, N failed/passed)")
    if "failure mode" not in lower:
        problems.append("no failure-modes section")
    return problems


def depth_gaps(number: str) -> list[str]:
    """ADR-536: what makes ADR-<number>'s deep dive or lesson too thin, or []."""
    if int(number) < DEPTH_FROM:
        return []
    out = []
    dives = _covering_deep_dives(number)
    if dives:
        results = [(path, _deep_dive_depth_problems(text)) for path, text in dives]
        if all(problems for _, problems in results):
            path, problems = min(results, key=lambda r: len(r[1]))
            out.append(f"{path.relative_to(ROOT)} is too thin: " + "; ".join(problems))
    lesson = _lesson_text(number)
    if lesson:
        problems = _lesson_depth_problems(lesson)
        if problems:
            out.append(f"the ADR-{number} lesson is too thin: " + "; ".join(problems))
    return out


def missing_artifacts(number: str) -> list[str]:
    """Which of the four artifacts are absent for ADR-<number>."""
    missing = []
    if not list(DECISIONS.glob(f"ADR-{number}-*.md")):
        missing.append(f"docs/decisions/ADR-{number}-*.md")

    cited = f"ADR-{number}"
    if not any(cited in p.read_text(errors="ignore") for p in JOURNALS.glob("*.md")):
        missing.append("a journal in docs/journals/ referencing it")

    guide = GUIDE.read_text(errors="ignore") if GUIDE.exists() else ""
    # Match the wikilink form and the plain "(ADR-354)" form -- the guide uses
    # both, and an earlier version of this check reported false gaps by
    # accepting only the first.
    if not re.search(rf"ADR-{number}[-|)\]]", guide):
        missing.append("a lesson in docs/LEARNING_GUIDE.md")

    gap = deep_dive_gap(number)
    if gap:
        missing.append(gap)
    missing.extend(depth_gaps(number))
    return missing


def main() -> int:
    gaps: dict[str, tuple[list[str], list[str]]] = {}
    for line in commits_being_pushed(sys.argv):
        sha, subject = line.split("|", 1)
        for number in set(ADR_IN_SUBJECT.findall(subject)):
            missing = missing_artifacts(number)
            if missing:
                shas, _ = gaps.get(number, ([], []))
                gaps[number] = (shas + [sha], missing)

    if not gaps:
        return 0

    print("", file=sys.stderr)
    print("Commits cite an ADR with missing documentation:", file=sys.stderr)
    for number, (shas, missing) in sorted(gaps.items()):
        print(f"\n  ADR-{number}  (cited by {', '.join(shas)})", file=sys.stderr)
        for m in missing:
            print(f"    missing: {m}", file=sys.stderr)
    print(
        "\nCLAUDE.md requires an ADR, a journal, a LEARNING_GUIDE lesson and a deep\n"
        "dive for every fix, change or feature -- with the ADR written BEFORE\n"
        "implementing.\n"
        "\nDeep dive: start from docs/templates/DEEP-DIVE-TEMPLATE.md; the standard\n"
        "is docs/deep-dives/ADR-487-D5-Push-Notifications.md. Scale the parts,\n"
        "never the depth: a small fix may be short, but all nine parts are there.\n"
        "A new bug in an existing feature adds a casebook case to its deep dive;\n"
        "this check cannot see that, so it is on you (ADR-501 D2).\n"
        "\nDepth (ADR-536; ADR-535 onward): the checks above are FLOORS. Passing them is\n"
        f"not the standard; compare against {CALIBRATION}.\n"
        "\n"
        "Write the missing artifacts, then push again. To push anyway (a WIP\n"
        "branch, say), set ALLOW_UNDOCUMENTED=1.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
