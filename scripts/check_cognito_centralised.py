#!/usr/bin/env python3
"""Fail if a Cognito pool/client id is hardcoded outside ci.yml's env: block (ADR-350).

Centralising the ids makes drift unlikely; it does not make it impossible. Someone
can still add a call site with a fresh literal, and that is invisible in review
because the new literal looks correct in isolation -- which is exactly how the
PR #20 production outage shipped: the frontend read an updated GitHub secret while
the backend kept an unchanged ci.yml literal, and a secret diffs to nothing.

This is the check that would have caught it before merge.
"""
import re
import sys
from pathlib import Path

CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"

# A pool id (us-east-2_XXXXXXXXX) or either app client id.
LITERAL = re.compile(r"us-east-2_[A-Za-z0-9]{9}|4r8tjkjs01e2b930qtqd12vdmf|3hjkvuirnaadus65slhm2ja37d")


def env_block_lines(lines: list[str]) -> set[int]:
    """1-indexed line numbers of the top-level `env:` block, where literals belong."""
    inside = False
    out = set()
    for i, line in enumerate(lines, 1):
        if re.match(r"^env:\s*$", line):
            inside = True
            out.add(i)
            continue
        if inside:
            # The block ends at the next top-level key (no leading whitespace).
            if line.strip() and not line[0].isspace():
                inside = False
            else:
                out.add(i)
    return out


def main() -> int:
    if not CI.exists():
        print(f"ci.yml not found at {CI}", file=sys.stderr)
        return 1

    lines = CI.read_text().splitlines()
    allowed = env_block_lines(lines)

    offenders = [
        (i, line.strip())
        for i, line in enumerate(lines, 1)
        if LITERAL.search(line) and i not in allowed
    ]

    if not offenders:
        print("Cognito ids are centralised in ci.yml's env: block.")
        return 0

    print("Hardcoded Cognito id outside the env: block (ADR-350):", file=sys.stderr)
    for num, text in offenders:
        print(f"  ci.yml:{num}: {text[:110]}", file=sys.stderr)
    print(
        "\nThe frontend and backend must agree on these. A second copy drifts silently --\n"
        "that is what caused the PR #20 outage. Reference the env: block instead:\n"
        "  ${{ env.PROD_COGNITO_POOL_ID }} / ${{ env.STAGING_COGNITO_POOL_ID }}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
