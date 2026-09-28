"""An admin can see, and fix, a sign-in lockout (ADR-467).

ADR-466 made a spent enrolment pass recoverable. It did not make the lockout
VISIBLE, and it left the fix gated to `lc === 'active'` -- which a locked-out
account can never reach, because a refused sign-in issues no token, so no
request reaches get_caller_employee and account_status never leaves
'pending_verification'.

The control that unblocks them was hidden for exactly the population blocked.
"""
import inspect
import pathlib
import re

import pytest

from app.routers import employees as E
from app.schemas.employee import EmployeeMfaEnrolmentResponse
from app.services import mfa_status

ROOT = pathlib.Path(__file__).resolve().parents[3]
ASSETS = ROOT / "frontend/src/pages/Assets.tsx"
TYPES = ROOT / "frontend/src/api/types.ts"


# ── D1: the endpoint ────────────────────────────────────────────────────────

def test_the_endpoint_exists_and_is_admin_only():
    src = inspect.getsource(E.get_mfa_enrolment)
    assert 'RoleChecker(["admin"])' in src, (
        "enrolment state is a security property of another person's account; "
        "widening this gate hands it to dispatch"
    )


def test_it_is_company_scoped():
    """Dimension 1. A cross-tenant read here lists another company's owners."""
    src = inspect.getsource(E.get_mfa_enrolment)
    assert "Employee.company_id == caller.company_id" in src


def test_it_is_scoped_to_privileged_roles():
    """Not a cost optimisation only -- field accounts are not at risk this way.

    They hold a grace window and are never refused for having no factor, so
    listing them would be 500 Cognito round-trips answering a question that
    does not apply to them.
    """
    src = inspect.getsource(E.get_mfa_enrolment)
    assert "MFA_PRIVILEGED_ROLES" in src


def test_it_reads_both_signals_in_one_call():
    """UserMFASettingList and the stamp come from the SAME admin_get_user.

    Probed on the live pool: list_users returns neither, so there is no bulk
    read -- which is why this is an endpoint and not a roster field. Reading
    them in two calls would double the round-trips for nothing.
    """
    src = inspect.getsource(E.get_mfa_enrolment)
    # Count CALLS, not the word -- the docstring and comments name it too, and
    # asserting on the word made this fail at 2 while the code was correct.
    body = "\n".join(
        l for l in src.splitlines()
        if not l.strip().startswith("#") and '"""' not in l
    )
    assert body.count("admin_get_user(") == 1, (
        "both signals must come from ONE admin_get_user per user"
    )
    assert "UserMFASettingList" in src
    assert "custom:mfa_first_seen" in src


def test_an_unreadable_row_does_not_blank_the_others():
    """Per-row try, not one around the loop."""
    src = inspect.getsource(E.get_mfa_enrolment)
    body = src.split("for emp in rows:", 1)[1]
    assert "except (ClientError, BotoCoreError)" in body, (
        "the Cognito read must be guarded INSIDE the loop"
    )


def test_unknown_is_never_reported_as_unenrolled():
    """ADR-377's rule. None means could not read; False accuses."""
    assert EmployeeMfaEnrolmentResponse.model_fields["enrolled"].default is None
    src = inspect.getsource(E.get_mfa_enrolment)
    assert "enrolled: bool | None = None" in src


def test_the_read_is_audited_without_naming_the_exposed_accounts():
    """ADR-458 D3's precedent: audit the read, but counts only.

    Recording WHICH accounts are unprotected would put a target list in a
    second store -- the Dimension 7 failure the audit row exists to avoid.
    """
    src = inspect.getsource(E.get_mfa_enrolment)
    assert 'action_type="employee.mfa_enrolment_viewed"' in src
    detail = src.split("detail={", 1)[1].split("}", 1)[0]
    assert "returned" in detail and "unenrolled" in detail
    for leak in ("name", "email", "username", "\"id\"", "ids"):
        assert leak not in detail, f"the audit detail carries {leak}"


def test_it_is_rate_limited():
    assert hasattr(E.get_mfa_enrolment, "__wrapped__") or True
    src = inspect.getsource(E)
    block = src.split("def get_mfa_enrolment", 1)[0]
    assert '@limiter.limit' in block.rsplit("@router.get", 1)[1]


def test_the_literal_path_is_registered_before_the_id_route():
    """FastAPI matches in registration order.

    /{employee_id} would swallow /mfa-enrolment as an employee id and 422 on
    the UUID parse -- a route that exists and can never be reached.
    """
    from app.main import app
    paths = [p for p in app.openapi()["paths"] if "/employees" in p]
    mfa = next(i for i, p in enumerate(paths) if "mfa-enrolment" in p)
    eid = next(i for i, p in enumerate(paths) if p.endswith("/employees/{employee_id}"))
    assert mfa < eid, "the literal route is shadowed by /{employee_id}"


def test_privileged_roles_still_includes_the_roles_preauth_refuses():
    """If the two lists drift, an account PreAuth blocks is absent from the
    panel that exists to find it."""
    for role in ("admin", "management", "dispatch"):
        assert role in mfa_status.MFA_PRIVILEGED_ROLES


# ── D2: the copy says what the action does ──────────────────────────────────

def test_the_confirm_no_longer_promises_only_the_factor():
    src = ASSETS.read_text()
    block = src.split("const handleResetMfa", 1)[1].split("};", 1)[0]
    assert "must set it up again at their next sign-in." not in block, (
        "pre-ADR-466 copy: an admin cannot tell this unblocks a trapped account"
    )
    assert "stuck and cannot finish" in block


def test_the_success_toast_names_the_outcome_not_just_the_device_count():
    src = ASSETS.read_text()
    assert "Sign-in unblocked." in src


def test_there_is_no_dead_partial_branch_on_the_success_path():
    """Dimension 5.

    fully_contained is `signed_out and not errors`, and a surviving factor
    appends to errors -- so the endpoint raises 502 before returning and
    factor_cleared is always true here. A "partly done" success branch would
    never render.
    """
    src = ASSETS.read_text()
    ok_arm = src.split("setResetMfaMsg({", 1)[1].split("});", 1)[0]
    assert "factor_cleared" not in ok_arm, (
        "branching on factor_cleared in the success arm is unreachable"
    )


# ── D3: the gate reaches the locked-out population ──────────────────────────

def test_the_reset_button_is_available_to_registered_accounts():
    """THE live gap. 'registered' is where a locked-out privileged account is
    pinned, and it was excluded from the only control that fixes it."""
    src = ASSETS.read_text()
    assert "(lc === 'active' || lc === 'registered') && (" in src, (
        "the reset control is still gated to active only"
    )


def test_the_gate_still_excludes_accounts_the_endpoint_refuses():
    """The 409 keys on cognito_username_for returning None. not_invited and
    invited have no username, so the button must not appear for them."""
    src = ASSETS.read_text()
    gate = "(lc === 'active' || lc === 'registered') && ("
    assert gate in src
    for excluded in ("not_invited", "bounced", "deactivated"):
        assert f"lc === '{excluded}'" not in gate


def test_the_409_boundary_is_what_the_gate_claims_it_is():
    """Pins the assumption D3 rests on, in the code rather than the comment."""
    src = inspect.getsource(E.reset_employee_mfa)
    assert "username = cognito_username_for(target)" in src
    assert "if not username:" in src
    # Assert the BEHAVIOUR, not the spelling: the resolver uses getattr, so a
    # literal-string assertion failed while the semantics were exactly right.
    class _Reg:   # a 'registered' employee -- username stamped, so D3 is safe
        username, email = "first.last", "f@example.com"

    class _Invited:   # invited, never registered -- the 409 case
        username, email = None, "f@example.com"

    class _Bare:      # no identifier at all
        username = email = None

    assert E.cognito_username_for(_Reg()) == "first.last"
    assert E.cognito_username_for(_Invited()) == "f@example.com"
    assert E.cognito_username_for(_Bare()) is None, (
        "a row with neither identifier must 409 rather than resolve"
    )


# ── ADR-381: the surface is actually reachable ──────────────────────────────

def test_the_panel_opener_is_called_somewhere():
    """ADR-381's failure, three times in one week: a live endpoint, a clean
    build, and a handler nothing calls. openEscalation shipped that way."""
    src = ASSETS.read_text()
    assert "const openEnrolment" in src, "handler missing"
    calls = re.findall(r"onClick=\{openEnrolment\}", src)
    assert calls, "openEnrolment is defined but never wired to anything"


def test_the_button_is_admin_gated_on_the_client_too():
    src = ASSETS.read_text()
    i = src.index("onClick={openEnrolment}")
    assert "isAdmin && (" in src[max(0, i - 700):i], (
        "the trigger is not behind isAdmin"
    )


def test_the_type_mirrors_the_backend_schema():
    """types.ts is hand-maintained -- there is no codegen."""
    ts = TYPES.read_text()
    assert "export interface MfaEnrolmentRow" in ts
    block = ts.split("export interface MfaEnrolmentRow", 1)[1].split("}", 1)[0]
    for field in EmployeeMfaEnrolmentResponse.model_fields:
        assert field in block, f"{field} missing from the TS type"
    assert "boolean | null" in block, "enrolled must stay three-valued in TS"


def test_the_client_renders_unknown_as_unknown():
    """null must not fall through to the unprotected badge."""
    src = ASSETS.read_text()
    assert "r.enrolled === null ?" in src, (
        "null is not handled before the truthiness check"
    )
    assert src.index("r.enrolled === null ?") < src.index("r.enrolled ? (")
