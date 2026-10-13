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
        "\n"
        "Write the missing artifacts, then push again. To push anyway (a WIP\n"
        "branch, say), set ALLOW_UNDOCUMENTED=1.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
