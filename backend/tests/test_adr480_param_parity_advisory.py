"""The parity check reports; it must never block a push (ADR-480).

The check itself (ADR-283) was correct the whole time. Nothing ran it, so a real
finding -- prod missing the M2M credential pair -- sat unread for an unknown
period. Wiring it into the pre-push hook is the fix.

Wiring it in WRONGLY is worse than leaving it out: the hook runs under
`set -euo pipefail`, so a check that exits non-zero aborts the push. Parity drift
is information about infrastructure, not a defect in the commit being pushed, and
a hook that blocks unrelated work on an unrelated condition gets --no-verify'd
until it may as well not exist.

The hook is not a tracked file, so this reads it where git keeps it and skips
cleanly on a checkout that has none (CI, a fresh clone).
"""
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOK = ROOT / ".git/hooks/pre-push"

pytestmark = pytest.mark.skipif(
    not HOOK.exists(), reason="no pre-push hook in this checkout"
)


def _parity_block() -> str:
    """The parity section only, so an assertion cannot be satisfied by the
    ADR-coverage block above it, which DOES legitimately exit 1."""
    src = HOOK.read_text()
    if "# Parameter Store parity" not in src:
        pytest.fail("the parity check is not wired into the pre-push hook")
    return src[src.index("# Parameter Store parity"):src.index("SYNC_SCRIPT=")]


def test_the_parity_check_never_exits_nonzero():
    """THE property. `exit 1` here aborts the push under set -e."""
    assert "exit 1" not in _parity_block(), (
        "the parity block can abort a push -- drift is advisory, and a blocking "
        "advisory check gets --no-verify'd into irrelevance"
    )


def test_its_failure_is_captured_rather_than_propagated():
    """Under `set -e` an unguarded non-zero command kills the script, so the
    non-zero exit must be absorbed by the assignment itself."""
    blk = _parity_block()
    assert "|| PARITY_RC=$?" in blk, (
        "the check's exit status must be captured; an unguarded call ends the "
        "hook before the private-repo sync runs"
    )


def test_a_missing_credential_is_not_reported_as_parity():
    """The failure that would make this worthless: a machine with no AWS
    credentials silently reporting that the environments agree."""
    blk = _parity_block()
    assert "NOT CHECKED" in blk
    assert "AccessDenied" in blk and "Unable to locate" in blk


def test_it_runs_before_the_private_repo_sync():
    """A push about to print findings should not first publish to the private
    repo -- same ordering rationale as the ADR-coverage check above it."""
    src = HOOK.read_text()
    assert src.index("# Parameter Store parity") < src.index("SYNC_SCRIPT=")


def test_stdin_is_not_consumed():
    """git writes the ref payload to the hook's stdin and it can be read ONCE.
    check_adr_coverage.py reads it. A child process inheriting stdin can eat it
    -- and did, in this session: a heredoc starved the coverage check until it
    hung. </dev/null is what keeps them independent."""
    assert "</dev/null" in _parity_block(), (
        "the parity check must not inherit the hook's stdin"
    )


def test_the_block_is_syntactically_valid():
    """bash -n on the whole hook -- a broken hook fails every push."""
    r = subprocess.run(["bash", "-n", str(HOOK)], capture_output=True, text=True)
    assert r.returncode == 0, f"pre-push hook is not valid bash: {r.stderr}"
