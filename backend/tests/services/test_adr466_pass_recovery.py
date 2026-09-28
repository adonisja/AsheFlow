"""A spent enrolment pass is recoverable (ADR-466).

ADR-459 stamps custom:mfa_first_seen so a privileged account's one-time
enrolment pass cannot be replayed. Nothing cleared it, so an account that spent
the pass without enrolling -- a crash or dropped connection mid-setup -- was
locked out with no in-product remedy. The prod Owner reached exactly that state.
"""
import inspect
import pathlib

import pytest

from app.services import mfa_containment

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra/lambda/cognito-pre-auth/handler.py"
RUNBOOK = ROOT / "docs/runbooks/MFA-Lockout-Recovery.md"

# The whole of docs/ is gitignored from the public repo (.gitignore:99) and
# reaches AsheFlow-private only through the pre-push hook, so in CI this file is
# LEGITIMATELY absent -- unlike the proprietary modules, which ci.yml copies in
# before pytest runs (hence the ADR-311 ban on import skip-guards: there, a
# missing file is always a broken sync).
#
# So these two tests cannot run in CI, and pretending otherwise is what failed
# PR #58. They are gated on the repo being a working copy that HAS docs/, which
# is a real condition and not an ImportError in disguise:
#
#   * on a developer machine docs/ exists, so they run and can fail;
#   * in CI the directory itself is absent, so they are reported as skipped.
#
# Gating on the DIRECTORY, not the file, is the point. `RUNBOOK.exists()` would
# also skip when the runbook is deleted locally -- the exact regression these
# tests exist to catch -- whereas docs/ missing while the file inside it is gone
# is not a state a working copy can reach.
DOCS_PRESENT = (ROOT / "docs" / "runbooks").is_dir()
needs_docs = pytest.mark.skipif(
    not DOCS_PRESENT,
    reason="docs/ is gitignored from the public repo; runs on a working copy",
)


# ── D1: the reset clears the pass ───────────────────────────────────────────

def test_clearing_a_factor_also_clears_the_enrolment_pass():
    src = inspect.getsource(mfa_containment.contain)
    assert "custom:mfa_first_seen" in src, (
        "the reset leaves the stamp, so a privileged user stays refused"
    )
    assert "admin_delete_user_attributes" in src


def test_the_pass_is_cleared_only_when_the_factor_is():
    """Containment (ADR-387) deliberately keeps the victim's factor. Clearing
    their pass there would hand an attacker a fresh unprotected sign-in."""
    src = inspect.getsource(mfa_containment.contain)
    guard = src.index("if clear_factor:")
    stamp = src.index("custom:mfa_first_seen")
    signout = src.index("admin_user_global_sign_out")
    assert guard < stamp < signout, (
        "the stamp clear is outside the clear_factor branch"
    )


def test_a_failed_pass_clear_does_not_fail_the_reset():
    """The factor is cleared, which is what containment promises. A surviving
    stamp costs a runbook step; failing the call costs the whole reset."""
    src = inspect.getsource(mfa_containment.contain)
    block = src[src.index("custom:mfa_first_seen"):]
    assert "clear_pass:" in block, "the stamp failure is not recorded separately"
    assert "raise" not in block.split("errors.append")[0]


# ── D2: the refusal is ours ─────────────────────────────────────────────────

def test_the_refusal_does_not_name_an_internal_trigger():
    src = HANDLER.read_text()
    hint = src.split("ENROL_HINT = (")[1].split(")")[0]
    assert "PreAuthentication" not in hint, "the message names the Lambda"


def test_the_refusal_does_not_point_at_the_old_enrolment_page():
    """ADR-465 moved enrolment to /mfa-setup. Account > Security is stale."""
    src = HANDLER.read_text()
    hint = src.split("ENROL_HINT = (")[1].split(")")[0]
    assert "Account > Security" not in hint


def test_the_refusal_names_a_way_out_for_a_spent_pass():
    """Someone seeing this usually CANNOT reach enrolment -- their pass is
    spent. Telling them to go set it up is a dead end without this."""
    src = HANDLER.read_text()
    hint = src.split("ENROL_HINT = (")[1].split(")")[0]
    assert "administrator" in hint and "reset" in hint


def test_the_refusal_has_no_trailing_period():
    """Cognito appends its own; two in a row is the visible seam."""
    src = HANDLER.read_text()
    hint = src.split("ENROL_HINT = (")[1].split(")")[0]
    assert not hint.strip().rstrip('"').endswith("."), "double period at the seam"


# ── D3: the runbook covers it ───────────────────────────────────────────────

@needs_docs
def test_the_runbook_documents_the_spent_pass_case():
    src = RUNBOOK.read_text()
    assert "custom:mfa_first_seen" in src, "the runbook does not know about the stamp"
    assert "spent its enrolment pass" in src


@needs_docs
def test_break_glass_remains_the_last_case():
    """An operator scanning headings should meet the ordinary remedies first."""
    src = RUNBOOK.read_text()
    assert src.index("BREAK GLASS") < src.index("spent its enrolment pass")
