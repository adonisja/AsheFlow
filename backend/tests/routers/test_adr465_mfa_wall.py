"""Enrolment is a wall, not a nudge (ADR-465).

ADR-459 D2 claimed the app was unusable until a privileged account enrolled.
It was not: `blocked` was computed and nothing consumed it. These pin both
halves -- the API refusal and the client redirect -- because either alone is
bypassable.
"""
import inspect
import pathlib
import re

from app.api import deps
from app.services import mfa_status

ROOT = pathlib.Path(__file__).resolve().parents[3]
APP = ROOT / "frontend/src/App.tsx"
WALL = ROOT / "frontend/src/pages/MfaRequired.tsx"
AXIOS = ROOT / "frontend/src/api/axiosClient.ts"
MAIN = ROOT / "backend/app/main.py"


# ── the rule itself ─────────────────────────────────────────────────────────

def test_privileged_without_a_factor_is_blocked():
    s = mfa_status.evaluate(role="admin", enrolled=False, grace_started_at=None)
    assert s.blocked is True and s.grace_days_total == 0


def test_field_inside_the_window_is_not_blocked():
    """Only `blocked` walls. A field user keeps their ADR-377 grace period."""
    s = mfa_status.evaluate(role="walker", enrolled=False, grace_started_at=None)
    assert s.blocked is False


def test_an_enrolled_privileged_user_is_not_blocked():
    s = mfa_status.evaluate(role="admin", enrolled=True, grace_started_at=None)
    assert s.blocked is False


# ── D3: the API refuses ─────────────────────────────────────────────────────

def test_the_gate_exists_and_is_applied_with_require_configured():
    assert hasattr(deps, "require_mfa_enrolled")
    src = MAIN.read_text()
    line = next(l for l in src.splitlines() if l.startswith("_configured = ["))
    assert "require_mfa_enrolled" in line, (
        "the MFA gate is not applied to the gated routers"
    )


def test_the_refusal_carries_a_machine_readable_code():
    """The client routes on the code. String-matching a message breaks the
    moment the copy is edited."""
    src = inspect.getsource(deps.require_mfa_enrolled)
    assert '"code": "mfa_enrolment_required"' in src
    assert "HTTP_403_FORBIDDEN" in src


def test_the_gate_fails_open_on_an_unexpected_error():
    """This runs on every gated request. A bug that fails closed locks out the
    whole company, including the admin who would fix it."""
    src = inspect.getsource(deps.require_mfa_enrolled)
    assert "except Exception:" in src
    tail = src.split("except Exception:")[1]
    assert "return" in tail.split("\n\n")[0], "the fail-open path does not return"


def test_an_unreachable_cognito_counts_as_enrolled():
    """is_enrolled returns None when Cognito cannot be read. Treating None as
    NOT enrolled would wall everyone during an AWS hiccup."""
    src = inspect.getsource(deps.require_mfa_enrolled)
    assert src.count("True if enrolled is None else enrolled") == 2, (
        "a None enrolment result is not being treated as enrolled"
    )


def test_the_identity_endpoints_stay_reachable_while_blocked():
    """The wall needs a door: /employees/me and /me/mfa-status feed the very
    page that clears the block (ADR-464)."""
    src = MAIN.read_text()
    line = next(l for l in src.splitlines()
                if "include_router(employees.identity_router" in l)
    assert "_configured" not in line and "require_mfa_enrolled" not in line


# ── D1/D2: the client walls ─────────────────────────────────────────────────

def test_protected_route_redirects_a_blocked_caller():
    src = APP.read_text()
    assert "mfaStatus?.blocked" in src, "no redirect on blocked"
    assert "/mfa-setup" in src


def test_the_block_is_checked_before_the_setup_redirect():
    """A blocked Owner sent to /setup hits API calls this same rule 403s --
    the ADR-464 deadlock rebuilt one layer up."""
    src = APP.read_text()
    assert src.index("mfaStatus?.blocked") < src.index("!isConfigured"), (
        "the setup redirect runs first and re-creates the deadlock"
    )


def test_the_wall_offers_only_enrolment_or_sign_out():
    """No cancel, no skip, no back -- those are the bypasses."""
    src = WALL.read_text()
    assert "SecurityPanel" in src, "the page does not offer enrolment"
    assert "signOut" in src, "the page offers no way out"
    for bypass in (">Skip<", ">Cancel<", ">Not now<", ">Later<"):
        assert bypass not in src, f"the wall offers {bypass}"


def test_signing_out_does_not_skip_the_wall():
    """Stated on the page, because a user who assumes otherwise will try it."""
    assert "will not skip" in WALL.read_text()


def test_the_client_routes_on_the_403_code():
    src = AXIOS.read_text()
    assert "mfa_enrolment_required" in src
    assert "/mfa-setup" in src


def test_a_blocked_user_is_not_signed_out_by_the_interceptor():
    """They are legitimately signed in and owe a factor. Signing them out
    makes the fix harder to reach."""
    src = AXIOS.read_text()
    block = src.split("mfa_enrolment_required")[1].split("}")[0]
    assert "signOut" not in block
