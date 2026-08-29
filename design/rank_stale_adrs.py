#!/usr/bin/env python3
"""Rank `accepted` ADRs by how likely they already shipped.

WHY THIS EXISTS
---------------
188 ADRs read `status: accepted`, and 174 of those carry no status_note at all.
Sampling found many were implemented long ago — ADR-283 shipped as a CI step and
ADR-263 as a role split, and neither had a commit message naming its ADR, so a
grep-based audit reported both as backlog.

That matters beyond tidiness. ADR-293 read "PROPOSED — not implemented" while its
most important decision had already shipped; implementing from that list would
have built a SECOND decay guard beside the first. A catalogue where a third of
entries are stale makes every "what is left?" question expensive.

WHAT THIS DOES NOT DO
---------------------
It does not decide anything. Every signal here is circumstantial — a cited file
existing does not prove the decision inside it was implemented. The output is a
WORK ORDER: read these ADRs first, because the evidence suggests the answer is
already in the tree. A human confirms; this only sorts.

Deliberately no auto-marking. Marking 174 ADRs implemented on inference would
replace "unknown but honest" with "confident and wrong", which is worse — that
is the ADR-301 lesson (a label asserting a state the code does not support) in
its most expensive possible form.

KNOWN FALSE POSITIVE, MEASURED
------------------------------
An ADR that cites the infrastructure it BUILDS ON inherits that evidence. Scored
against ADR-233 (an ADP migration plan, `proposed`, unbuilt), it returns 85 — a
migration, three cited files and three symbols, every one of them belonging to
the existing ADP work the plan extends rather than to the plan itself.

So a high score means "the things this ADR talks about exist", NOT "this ADR
shipped". For a small fix that is nearly the same claim; for a multi-phase plan
built on shipped foundations it is not. Read the decisions, not the number.

VALIDATED
---------
Backtested against the ten ADRs reconciled by hand on 2026-08-29: all ten scored
>= 37, including ADR-283 and ADR-263, which a commit-message grep missed entirely
(their work shipped under other ADRs' commit messages). That is the case this
exists to catch.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
DECISIONS = REPO / "docs" / "decisions"

CODE_ROOTS = ["backend", "frontend/src", "mobile/src", "scripts", "design"]

# Signals, strongest first. Weights are deliberately coarse: the point is
# ordering, and pretending to more precision than circumstantial evidence
# supports would be its own kind of false confidence.
W_MIGRATION = 40   # a migration id that exists is near-proof the schema landed
W_SYMBOL    = 12   # a backticked identifier found in code
W_PATH      = 8    # a cited file that exists
W_COMMIT    = 25   # a commit message naming the ADR

SYMBOL_RE = re.compile(r"`([a-z_][a-z0-9_]{5,})`")
PATH_RE = re.compile(r"`([A-Za-z_][\w/\.]*\.(?:py|tsx|ts))`")
MIGRATION_RE = re.compile(r"\b([0-9a-f]{12})\b")

# Words that appear inside backticks but are prose, not code.
STOPWORDS = {
    "operating_mode", "company_id", "employee_id", "assignment_id",
    "created_at", "updated_at", "normalised_address",
}


def _repo_files() -> dict[str, list[pathlib.Path]]:
    """basename -> paths. Cited paths are often bare (`types.ts`)."""
    out: dict[str, list[pathlib.Path]] = {}
    for root in CODE_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".ts", ".tsx", ".sh", ".yml"):
                out.setdefault(p.name, []).append(p)
    return out


def _grep(term: str) -> bool:
    """Is this identifier present anywhere in the code roots?"""
    roots = [str(REPO / r) for r in CODE_ROOTS if (REPO / r).exists()]
    try:
        r = subprocess.run(
            ["grep", "-rlF", "--include=*.py", "--include=*.ts", "--include=*.tsx",
             term, *roots],
            capture_output=True, text=True, timeout=20,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def _commits_naming(adr: str) -> int:
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "--all", f"--grep=ADR-{adr}"],
            cwd=REPO, capture_output=True, text=True, timeout=20,
        )
        return len([l for l in r.stdout.splitlines() if l.strip()])
    except Exception:
        return 0


def score(path: pathlib.Path, files: dict) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    adr = re.search(r"^adr:\s*(\d+)", text, re.M)
    adr = adr.group(1) if adr else path.name.split("-")[1]

    pts = 0
    why: list[str] = []

    n = _commits_naming(adr)
    if n:
        pts += W_COMMIT
        why.append(f"{n} commit(s) name it")

    migs = [m for m in set(MIGRATION_RE.findall(text))
            if list((REPO / "backend" / "alembic" / "versions").glob(f"{m}*"))]
    if migs:
        pts += W_MIGRATION
        why.append(f"migration {migs[0]} exists")

    paths = {p for p in PATH_RE.findall(text)}
    found_paths = [p for p in paths if os.path.basename(p) in files]
    if found_paths:
        pts += W_PATH
        why.append(f"{len(found_paths)}/{len(paths)} cited file(s) exist")

    syms = {s for s in SYMBOL_RE.findall(text) if s not in STOPWORDS}
    # Cap the work: check the most distinctive handful, not every backtick.
    checked = sorted(syms, key=len, reverse=True)[:6]
    found_syms = [s for s in checked if _grep(s)]
    if found_syms:
        pts += W_SYMBOL
        why.append(f"symbol(s) in code: {', '.join(found_syms[:3])}")

    return {"adr": adr, "file": path.name, "score": pts, "why": why}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=30, help="rows to print")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--min-adr", type=int, default=0, help="ignore ADRs below this number")
    args = ap.parse_args()

    files = _repo_files()
    rows = []
    for p in sorted(DECISIONS.glob("ADR-*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        st = re.search(r"^status:\s*(\w+)", text, re.M)
        if not st or st.group(1).lower() != "accepted":
            continue
        num = re.search(r"^adr:\s*(\d+)", text, re.M)
        if num and int(num.group(1)) < args.min_adr:
            continue
        rows.append(score(p, files))

    rows.sort(key=lambda r: (-r["score"], -int(r["adr"])))

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"\n{len(rows)} ADRs read `accepted`. Ranked by evidence they already shipped.")
    print("This SORTS, it does not decide — open each and confirm.\n")
    for r in rows[: args.limit]:
        print(f"  {r['score']:3}  ADR-{r['adr']}  {r['file'][:46]}")
        for w in r["why"]:
            print(f"       - {w}")
    if len(rows) > args.limit:
        print(f"\n  ... {len(rows) - args.limit} more (use --limit)")
    zero = [r for r in rows if r["score"] == 0]
    print(f"\n  {len(zero)} with NO evidence — likeliest genuine backlog.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
