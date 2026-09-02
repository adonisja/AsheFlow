#!/usr/bin/env python3
"""Flag AI-tell prose in user-facing frontend strings.

The tells are not wrong English. They are the register of a machine writing
copy: an em dash where a full stop would do, "seamlessly", "leverage", "simply",
"robust". A product that talks that way reads as generated, and an operator who
notices stops trusting the screen.

SCOPE IS DELIBERATELY NARROW: strings a user actually reads. Code comments are
excluded — an em dash in a comment explaining a constraint is fine, and sweeping
them would bury the signal in noise.

Also excluded, per the rule this check enforces: a lone em dash used as a
TABULAR placeholder for an empty cell (`{value ?? '—'}`). That is typographic
convention, not prose.

Baselined: existing violations are recorded so the check fails only on NEW ones.
Regenerate deliberately with --update after clearing a batch.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
BASELINE = ROOT / "scripts" / "ui_prose_baseline.json"

# A lone em dash between quotes is an empty-cell placeholder, not prose.
TABULAR = re.compile(r"""['"]\s*—\s*['"]""")

# A quoted VALUE followed by a dash and its gloss — `"07:00" — drivers must be
# on-site by 7 AM` — is the same separator use one line down: a key and its
# description, not two clauses joined. These render in a monospace box under an
# "Example" heading, so they read as a legend rather than a sentence.
VALUE_GLOSS = re.compile(r"""\\?['"][^'"]{1,40}\\?['"]\s+—\s""")

PATTERNS: dict[str, re.Pattern] = {
    "em-dash": re.compile(r"—"),
    "delve": re.compile(r"\bdelve[sd]?\b", re.I),
    "seamless": re.compile(r"\bseamless(ly)?\b", re.I),
    "leverage": re.compile(r"\bleverag(e|es|ed|ing)\b", re.I),
    "robust": re.compile(r"\brobust\b", re.I),
    "utilize": re.compile(r"\butiliz(e|es|ed|ing)\b", re.I),
    "simply": re.compile(r"\bsimply\b", re.I),
    "effortless": re.compile(r"\beffortless(ly)?\b", re.I),
    "unlock": re.compile(r"\bunlock(s|ed|ing)?\s+(the\s+)?(power|potential)\b", re.I),
    "elevate": re.compile(r"\belevat(e|es|ed|ing)\s+your\b", re.I),
    "dive-in": re.compile(r"\b(let'?s\s+)?dive\s+(in|into)\b", re.I),
    "in-the-realm": re.compile(r"\bin\s+the\s+realm\s+of\b", re.I),
    "testament": re.compile(r"\ba\s+testament\s+to\b", re.I),
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
            # A className is markup, not copy.
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

    print("New AI-tell prose in user-facing strings:", file=sys.stderr)
    for rel, num, name, text in new:
        print(f"  {rel}:{num}  [{name}]", file=sys.stderr)
        print(f"    {text}", file=sys.stderr)
    print(
        "\nReword it. An em dash joining two clauses is usually a full stop or a "
        "comma;\na lone em dash as an empty-cell placeholder is fine and is already "
        "excluded.\nAfter clearing a batch, re-baseline with --update.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
