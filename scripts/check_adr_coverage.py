#!/usr/bin/env python3
"""Refuse a push whose commits cite an ADR that has no documentation.

CLAUDE.md requires three artifacts per change -- ADR, journal, LEARNING_GUIDE
lesson -- and says to write the ADR *before* implementing. That rule has been in
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


def missing_artifacts(number: str) -> list[str]:
    """Which of the three artifacts are absent for ADR-<number>."""
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
        "\nCLAUDE.md requires an ADR, a journal and a LEARNING_GUIDE lesson for\n"
        "every fix, change or feature -- with the ADR written BEFORE implementing.\n"
        "\n"
        "Write the missing artifacts, then push again. To push anyway (a WIP\n"
        "branch, say), set ALLOW_UNDOCUMENTED=1.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
