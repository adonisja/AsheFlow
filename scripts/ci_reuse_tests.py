#!/usr/bin/env python3
"""Reuse a passing backend-test run for byte-identical code (ADR-552).

Two subcommands, both used by .github/workflows/ci.yml:

  fingerprint  -> prints sha256(public tree, private tree, python version)
  lookup       -> writes `hit=true|false` (and run details) to $GITHUB_OUTPUT

The rule that matters is D4: DOUBT MEANS RUN THE TESTS. Every failure here --
no token, an API error, a missing private tree, unexpected JSON -- ends as
hit=false. A bug in this script can only cost time, never hide a failure.

Only a run that ACTUALLY RAN the tests uploads the marker (the workflow's
upload step is conditioned on hit != true), so a reuse never vouches for
another reuse.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

MARKER_PREFIX = "backend-tests-passed-"
MAX_AGE = timedelta(hours=24)


def fingerprint(public_tree: str, private_tree: str, python_version: str) -> str:
    for name, value in (("public tree", public_tree), ("private tree", private_tree),
                        ("python version", python_version)):
        if not value or not value.strip():
            raise ValueError(f"missing {name}")
    raw = f"public={public_tree.strip()}\nprivate={private_tree.strip()}\npython={python_version.strip()}\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def find_reusable(artifacts: dict, fp: str, *, now: datetime, current_run_id: int,
                  max_age: timedelta = MAX_AGE) -> dict | None:
    """The newest usable marker for `fp`, or None.

    Usable: exact name, not expired, from another run, younger than max_age."""
    best = None
    for a in artifacts.get("artifacts", []):
        if a.get("name") != MARKER_PREFIX + fp or a.get("expired"):
            continue
        run = (a.get("workflow_run") or {}).get("id")
        if not run or run == current_run_id:
            continue
        created = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
        if now - created > max_age:
            continue
        if best is None or created > best["created_at"]:
            best = {"run_id": run, "created_at": created}
    return best


def _write_output(**kv) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in kv.items())
    if path:
        with open(path, "a") as f:
            f.write(lines)
    sys.stdout.write(lines)


def _summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")
    print(text)


def lookup(fp: str) -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = int(os.environ.get("GITHUB_RUN_ID", "0") or 0)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/actions/artifacts?name={MARKER_PREFIX}{fp}&per_page=20"],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout
        hit = find_reusable(json.loads(out), fp, now=datetime.now(timezone.utc), current_run_id=run_id)
    except Exception as exc:  # D4: any doubt -> run the tests
        _summary(f"Backend tests will run: could not check for an identical passing run ({type(exc).__name__}).")
        _write_output(hit="false")
        return 0
    if hit is None:
        _summary(f"Backend tests will run: no passing run of this exact code in the last "
                 f"{int(MAX_AGE.total_seconds() // 3600)} h (fingerprint `{fp[:12]}`).")
        _write_output(hit="false")
        return 0
    age_h = (datetime.now(timezone.utc) - hit["created_at"]).total_seconds() / 3600
    url = f"{server}/{repo}/actions/runs/{hit['run_id']}"
    _summary(f"**Reused backend tests from [run #{hit['run_id']}]({url})**: same public code, "
             f"same private tree, same Python, {age_h:.1f} h old (ADR-552). Every other check ran here.")
    _write_output(hit="true", run_id=str(hit["run_id"]), run_url=url)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "fingerprint":
        try:
            print(fingerprint(os.environ.get("PUBLIC_TREE", ""), os.environ.get("PRIVATE_TREE", ""),
                              os.environ.get("PYTHON_VERSION", "")))
        except ValueError as exc:
            # No fingerprint -> the lookup is skipped and the tests run (D4).
            print(f"none ({exc})")
        return 0
    if len(argv) >= 3 and argv[1] == "lookup":
        if argv[2].startswith("none"):
            _summary("Backend tests will run: the code under test could not be fingerprinted.")
            _write_output(hit="false")
            return 0
        return lookup(argv[2])
    print("usage: ci_reuse_tests.py fingerprint | lookup <fingerprint>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
