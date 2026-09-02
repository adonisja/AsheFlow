#!/usr/bin/env python3
"""House style for operator-facing copy: prefer a full stop to a dash.

WHAT THIS IS NOT
----------------
An earlier version of this file claimed to detect "AI-tell" prose. That framing
did not survive checking (ADR-360). The em dash is a folk heuristic with no
empirical support — the one testable version of the claim is that models render
`—` WITHOUT flanking spaces while humans add them, and this codebase is 753
spaced to 140 unspaced, i.e. the human convention throughout.

The features the research actually associates with generated text are
statistical: lower lexical diversity, smaller vocabulary, more nouns and
determiners, fewer adjectives and adverbs. A regex cannot see any of that.

WHAT THIS IS
------------
A style rule, on ordinary editing grounds. In a message an operator reads while
something is going wrong, two short sentences beat one dash-joined clause:

    "Publish failed — see the message above."
    "Publish failed. See the message above."

The second is easier to parse under stress, and stress is the condition this
product is read in. That is the whole justification; it does not depend on who
or what wrote the first version.

SCOPE
-----
Strings a user reads. Excluded, deliberately:

  * Code comments. A dash joining clauses in an explanation is fine, and the
    exclusion keeps the signal legible.
  * A lone em dash as an empty-cell placeholder, `{value ?? '—'}`.
  * A quoted value and its gloss, `"07:00" — drivers must be on-site by 7 AM`,
    which renders as a legend rather than a sentence.
  * className values, which are markup.

Baselined: fails only on NEW instances. Regenerating the baseline WITHOUT
clearing anything is the same failure as lowering MIN_TESTS to make CI pass.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
BASELINE = ROOT / "scripts" / "ui_copy_style_baseline.json"

# A lone em dash between quotes is an empty-cell placeholder, not prose.
TABULAR = re.compile(r"""['"]\s*—\s*['"]""")

# A quoted VALUE followed by a dash and its gloss is a key beside its
# description. These render in a monospace box under an "Example" heading.
VALUE_GLOSS = re.compile(r"""\\?['"][^'"]{1,40}\\?['"]\s+—\s""")

# Only two patterns survive measurement. Eleven vocabulary patterns from the
# first version ("delve", "seamless", "leverage", "robust", ...) had ZERO hits
# across the entire frontend: they were internet folklore about AI writing, not
# anything present in this product. A rule that never fires is not a safeguard,
# it is noise that makes the real signal harder to see.
PATTERNS: dict[str, re.Pattern] = {
    # Two clauses joined by a dash where a full stop or comma reads better.
    "dash-joined-clause": re.compile(r"—"),
    # "Simply" tells the reader their difficulty is their own fault.
    "simply": re.compile(r"\bsimply\b", re.I),
}


def _is_comment(stripped: str) -> bool:
    return stripped.startswith(("//", "*", "/*", "{/*")) or stripped.endswith("*/}")


def scan() -> list[tuple[str, int, str, str]]:
    found = []
    for path in sorted(SRC.rglob("*.tsx")) + sorted(SRC.rglob("*.ts")):
        rel = str(path.relative_to(ROOT))
        for num, line in enumerate(path.read_text(errors="ignore").split("\n"), 1):
            stripped = line.strip()
            if _is_comment(stripped):
                continue
            probe = VALUE_GLOSS.sub("", TABULAR.sub("", line))
            if "className" in probe:
                probe = re.sub(r'className=(\{[^}]*\}|"[^"]*")', "", probe)
            for name, pat in PATTERNS.items():
                if pat.search(probe):
                    found.append((rel, num, name, stripped[:120]))
    return found


def main() -> int:
    found = scan()
    key = lambda h: f"{h[0]}:{h[1]}:{h[2]}"

    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(sorted(key(h) for h in found), indent=2) + "\n")
        print(f"Baseline written: {len(found)} known instances.")
        return 0

    known = set(json.loads(BASELINE.read_text())) if BASELINE.exists() else set()
    new = [h for h in found if key(h) not in known]

    if not new:
        print(f"OK — {len(found)} known instances, none new.")
        return 0

    print("New copy-style issues in user-facing strings:", file=sys.stderr)
    for rel, num, name, text in new:
        print(f"  {rel}:{num}  [{name}]", file=sys.stderr)
        print(f"    {text}", file=sys.stderr)
    print(
        "\nTwo clauses joined by a dash usually want a full stop or a comma.\n"
        "A lone em dash as an empty-cell placeholder, and a quoted value with its\n"
        "gloss, are both already excluded. After clearing a batch, re-baseline\n"
        "with --update.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
