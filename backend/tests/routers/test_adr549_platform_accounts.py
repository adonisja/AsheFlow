"""Platform accounts manage their own sign-in; surveyors enrol at first sign-in (ADR-549).

Platform accounts (super_admin, platform_support, surveyor) have no Employee
row, and every self-service auth path was built on that row. These drive the
real functions: the Lambda, the MFA tier, the API gate, the session stamp, the
/platform/me endpoints and the device sweep.
"""
import importlib.util
import inspect
import pathlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.api import deps
from app.models.audit_log import AuditLog
from app.models.platform_session import PlatformSessionStamp
from app.routers import platform_account as P
from app.routers import survey_register as S
from app.services import account_security, device_fleet, mfa_status
from app.tasks import device_sweep
from tests._credentials import make_test_password

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"
NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def _surveyor(**over):
    u = {"id": str(uuid.uuid4()), "username": "test.surveyor", "email": "s@example.com",
         "cognito_groups": ["surveyor"], "auth_time": int(NOW.timestamp())}
    u.update(over)
    return u


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "op")


# ── D1: a surveyor enrols at first sign-in ─────────────────────────────────

def _lambda():
    spec = importlib.util.spec_from_file_location("pre_auth_handler_549", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_auth_handler_549"] = mod
    spec.loader.exec_module(mod)
    mod._now = lambda: NOW
    return mod


def _lambda_user(mod, stamp=None, mfa=None):
    attrs = [] if stamp is None else [{"Name": "custom:mfa_first_seen", "Value": stamp}]
    c = MagicMock()
    c.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": "surveyor"}]}
    c.admin_get_user.return_value = {"UserMFASettingList": mfa, "UserStatus": "CONFIRMED",
                                     "UserAttributes": attrs}
    mod._client = c
    return {"userPoolId": "us-east-2_T", "userName": "test.surveyor",
            "triggerSource": "PreAuthentication_Authentication", "request": {}}


def test_the_lambda_gates_a_surveyor_with_the_24h_window():
    mod = _lambda()
    assert "surveyor" in mod.PRIVILEGED_GROUPS
    assert mod.handler(_lambda_user(mod), None) is not None                       # first sign-in
    inside = (NOW - timedelta(hours=3)).isoformat(timespec="seconds")
    assert mod.handler(_lambda_user(mod, stamp=inside), None) is not None        # inside the window
    closed = (NOW - timedelta(hours=25)).isoformat(timespec="seconds")
    with pytest.raises(Exception) as exc:
        mod.handler(_lambda_user(mod, stamp=closed), None)                       # window closed
    assert str(exc.value) == mod.ENROL_HINT
    assert mod.handler(_lambda_user(mod, stamp=closed, mfa=["SOFTWARE_TOKEN_MFA"]), None)


def test_a_surveyor_is_on_the_enrol_before_use_tier():
    assert mfa_status.tier_for("", {"surveyor"}) == "privileged"
    st = mfa_status.evaluate(role="", enrolled=False, grace_started_at=None, groups={"surveyor"})
    assert st.blocked and st.grace_days_total == 0


def test_mfa_status_serves_a_surveyor_instead_of_403():
    """Was: 403 'No employee record found' on every load (staging, 2026-10-19)."""
    from app.routers import employees as E
    with patch.object(mfa_status, "is_enrolled", return_value=False), \
         patch.object(mfa_status, "read_setup_window",
                      return_value=("open", NOW + timedelta(hours=20))):
        out = E.get_my_mfa_status(db=None, caller=None, current_user=_surveyor())
    assert out["tier"] == "privileged" and out["blocked"] is True
    assert out["setup_window_ends_at"] == (NOW + timedelta(hours=20)).isoformat()


# ── D2: the survey API refuses an unenrolled caller ────────────────────────

def test_the_survey_router_is_mounted_behind_the_mfa_gate():
    from app.main import app
    from fastapi.routing import APIRoute
    # Find a survey route in the built app and check its dependency tree.
    paths = app.openapi()["paths"]
    assert any(p.startswith("/api/v1/survey/") for p in paths)
    src = (ROOT / "backend" / "app" / "main.py").read_text()
    line = next(l for l in src.splitlines() if "include_router(survey_register.router" in l)
    assert "require_mfa_enrolled" in line


def test_require_mfa_enrolled_refuses_an_unenrolled_surveyor(db):
    with patch.object(mfa_status, "is_enrolled", return_value=False):
        with pytest.raises(HTTPException) as exc:
            deps.require_mfa_enrolled(current_user=_surveyor(), db=db)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "mfa_enrolment_required"
    with patch.object(mfa_status, "is_enrolled", return_value=True):
        assert deps.require_mfa_enrolled(current_user=_surveyor(), db=db) is None


# ── D3: a platform session stamp ───────────────────────────────────────────

def test_a_platform_session_from_before_the_stamp_is_refused(db):
    u = _surveyor()
    db.add(PlatformSessionStamp(cognito_sub=u["id"], tokens_valid_after=NOW, updated_at=NOW))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        deps.get_platform_user(current_user=dict(u, auth_time=int(NOW.timestamp()) - 60), db=db)
    assert exc.value.status_code == 401 and exc.value.detail["code"] == "credentials_changed"
    # The sign-in that follows the change (same second or later) is accepted.
    assert deps.get_platform_user(current_user=u, db=db) == u


def test_a_tenant_caller_never_reads_the_platform_table():
    db = MagicMock()
    walker = {"id": "x", "cognito_groups": ["walker"], "auth_time": 1}
    assert deps.get_platform_user(current_user=walker, db=db) == walker
    db.get.assert_not_called()


@pytest.mark.parametrize("gate", [deps.get_super_admin, deps.get_platform_staff,
                                  S.get_writer, S.get_area_viewer, P.get_platform_account])
def test_every_platform_gate_checks_the_stamp(gate):
    """A gate on get_current_user directly would skip revocation entirely."""
    dep = inspect.signature(gate).parameters["current_user"].default
    assert dep.dependency is deps.get_platform_user, gate.__name__


# ── D4: /platform/me ───────────────────────────────────────────────────────

def test_a_tenant_account_cannot_use_the_platform_endpoints():
    with pytest.raises(HTTPException) as exc:
        P.get_platform_account(current_user={"id": "x", "cognito_groups": ["admin"]})
    assert exc.value.status_code == 403


def test_me_reads_the_callers_own_cognito_record():
    c = MagicMock()
    c.admin_get_user.return_value = {"UserMFASettingList": None, "UserAttributes": [
        {"Name": "name", "Value": "Test Surveyor"}, {"Name": "email", "Value": "s@example.com"},
        {"Name": "email_verified", "Value": "true"}]}
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = None   # not a contributor row
    with patch.object(P, "_cognito", return_value=c):
        out = P.get_me(caller=_surveyor(), db=db)
    assert c.admin_get_user.call_args.kwargs["Username"] == "test.surveyor"
    assert (out.name, out.role_label, out.mfa_enrolled, out.email_verified) == \
        ("Test Surveyor", "Surveyor", False, True)


def test_request_code_is_rate_limited_on_a_namespaced_key():
    seen = []
    c = MagicMock()
    c.forgot_password.return_value = {"CodeDeliveryDetails": {"Destination": "s***@e***"}}
    with patch.object(account_security, "allow_request",
                      side_effect=lambda key, flow: seen.append((key, flow)) or True), \
         patch.object(P, "_cognito", return_value=c):
        out = P.request_password_code(caller=_surveyor(id="abc"))
    assert seen == [("platform:abc", "password")]
    assert out["sent_to"] == "s***@e***"


def test_request_code_without_a_verified_email_is_409():
    c = MagicMock()
    c.forgot_password.side_effect = _client_error("InvalidParameterException")
    with patch.object(account_security, "allow_request", return_value=True), \
         patch.object(P, "_cognito", return_value=c):
        with pytest.raises(HTTPException) as exc:
            P.request_password_code(caller=_surveyor())
    assert exc.value.status_code == 409


def test_confirm_changes_the_password_ends_sessions_and_audits(db):
    u = _surveyor()
    c = MagicMock()
    with patch.object(P, "_cognito", return_value=c), \
         patch.object(account_security, "_cognito", return_value=c):
        out = P.confirm_password_change(
            payload=P._PasswordConfirmRequest(code="123456", new_password=make_test_password()),
            caller=u, db=db)
    assert out["signed_out"] is True
    c.admin_user_global_sign_out.assert_called_once()
    row = db.get(PlatformSessionStamp, u["id"])
    assert row is not None
    audit = db.query(AuditLog).filter(AuditLog.action_type == "account.password_changed",
                                      AuditLog.target_id == uuid.UUID(u["id"])).one()
    assert audit.actor_id is None and audit.company_id is None
    assert audit.after_snapshot["actor_kind"] == "surveyor"   # write_audit maps detail -> after
    # The session that made the change is now over too, from the stamp alone.
    with pytest.raises(HTTPException):
        deps.get_platform_user(current_user=dict(u, auth_time=int(row.tokens_valid_after.replace(
            tzinfo=row.tokens_valid_after.tzinfo or timezone.utc).timestamp()) - 1), db=db)


def test_the_stamp_lands_even_when_cognito_sign_out_fails(db):
    c = MagicMock()
    c.admin_user_global_sign_out.side_effect = _client_error("InternalErrorException")
    with patch.object(account_security, "_cognito", return_value=c):
        assert account_security.end_platform_sessions(db, "sub-1", "u") is False
    db.flush()          # the caller commits, as with end_all_sessions
    assert db.get(PlatformSessionStamp, "sub-1") is not None


# ── D1: surveyors' devices on the 7-day timing ─────────────────────────────

def _sweep(db, privileged_only):
    swept = {}
    groups = {("super_admin", "platform_support"): {"adon"}, ("surveyor",): {"test.surveyor"}}
    with patch.object(device_sweep, "SessionLocal", return_value=db), \
         patch.object(device_sweep, "_groups_for", return_value=set()), \
         patch.object(device_sweep, "_platform_usernames",
                      side_effect=lambda g=device_sweep.PLATFORM_GROUPS: groups[tuple(g)]), \
         patch.object(device_sweep.mfa_status, "is_enrolled", return_value=False), \
         patch.object(device_fleet, "forget_stale",
                      side_effect=lambda username, ttl, **_: swept.setdefault(username, ttl) and 1), \
         patch.object(device_sweep, "raise_platform_alert") as alert:
        out = device_sweep.sweep_stale_devices(privileged_only=privileged_only)
    return out, swept, alert


def test_a_surveyor_is_swept_daily_on_the_field_ttl_without_an_alert(db):
    out, swept, alert = _sweep(db, privileged_only=False)
    assert swept["test.surveyor"] == device_fleet.FIELD_DEVICE_TTL
    assert swept["adon"] == device_fleet.PRIVILEGED_CHALLENGE_TTL
    assert out["surveyor_checked"] == 1
    assert all(c.kwargs.get("subject_ref") != "test.surveyor" for c in alert.call_args_list)


def test_the_hourly_privileged_run_skips_surveyors(db):
    out, swept, _ = _sweep(db, privileged_only=True)
    assert "test.surveyor" not in swept and out["surveyor_checked"] == 0


# ── D5/D6: both clients ────────────────────────────────────────────────────

WEB = ROOT / "frontend" / "src"
MOB = ROOT / "mobile" / "src"


def test_the_web_account_route_admits_every_platform_group():
    """It sat inside the super-admin-only layout and rendered the tenant page."""
    app_src = (WEB / "App.tsx").read_text()
    route = next(l for l in app_src.splitlines() if 'path="/superadmin/account"' in l)
    assert "<PlatformAccount />" in route
    # It must sit in the layout route that admits all three groups.
    before = app_src[:app_src.index(route)]
    layout = before[before.rindex("<Route element={<ProtectedRoute allowedRoles="):]
    assert "'super_admin', 'platform_support', 'surveyor'" in layout.splitlines()[0]
    assert "</Route>" not in layout, "the account route escaped the all-platform layout"


def test_the_web_page_uses_the_platform_endpoints():
    src = (WEB / "pages" / "superadmin" / "PlatformAccount.tsx").read_text()
    for path in ("'/platform/me'", "'/platform/me/password/request-code'", "'/platform/me/password/confirm'"):
        assert path in src, path
    assert "/employees/me" not in src
    assert "<SecurityPanel />" in src


@pytest.mark.parametrize("path", [WEB / "hooks" / "useSessionTimeout.ts",
                                  MOB / "contexts" / "AuthContext.tsx"], ids=["web", "mobile"])
def test_platform_accounts_poll_their_own_session_check(path):
    """Skipped before, so a platform account's other tabs/phones never learned
    of a password change until they next clicked something."""
    src = path.read_text()
    assert "'/platform/me/session'" in src
    assert "if (!enabled || isPlatform) return;" not in src


def test_mobile_surveyors_reach_an_account_screen():
    shell = (MOB / "screens" / "Survey" / "SurveyScreens.tsx").read_text()
    assert 'name="PlatformAccount"' in shell and "navigate('PlatformAccount')" in shell
    screen = (MOB / "screens" / "Survey" / "PlatformAccountScreen.tsx").read_text()
    assert "'/platform/me/password/confirm'" in screen and "<MfaEnrolment" in screen


def test_mobile_support_does_not_land_on_the_tenant_tabs():
    nav = (MOB / "navigation" / "index.tsx").read_text()
    support = nav.index("hasRole('platform_support')")
    main = nav.index('name="Main"')
    assert support < main, "platform_support must be routed before the tenant shell"


def test_the_wall_gives_a_surveyor_a_true_reason():
    src = (WEB / "pages" / "MfaRequired.tsx").read_text()
    assert "isSurveyorOnly" in src and "Survey records carry your name" in src
