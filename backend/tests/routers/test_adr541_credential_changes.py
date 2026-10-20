"""Password and email changes are confirmed out of band and end every session (ADR-541).

Owner, 2026-10-18: changing your password must be confirmed from email, so
someone with unauthorised access can't change it; changing your email must
sign you out everywhere else. These run the real handlers on sqlite with
Cognito, SES and Redis stubbed at their real names (CI has no Redis).
"""
import ast
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.api import deps
from tests._credentials import make_test_password
from app.models.audit_log import AuditLog
from app.routers import employees as E
from app.services import account_security as AS
from tests.conftest import make_employee


class FakeRedis:
    """The handful of Redis calls account_security and the router make."""

    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, ttl, v):
        self.d[k] = v

    def delete(self, *ks):
        for k in ks:
            self.d.pop(k, None)

    def incr(self, k):
        self.d[k] = int(self.d.get(k, 0)) + 1
        return self.d[k]

    def expire(self, k, ttl):
        pass


# Generated, never written (ADR-547): GitGuardian incident 38384008 on PR #80
# was this file's old literal fixture. It only ever reaches a mocked Cognito.
_NEW_PASSWORD = make_test_password()

def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "op")


@pytest.fixture
def env():
    """Cognito, SES senders and Redis, stubbed; returns the stubs to inspect."""
    r = FakeRedis()
    cognito = MagicMock()
    sent = []
    draws = iter(range(111111, 999999, 111111))   # distinct, predictable codes
    with patch.object(AS.secrets, "randbelow", side_effect=lambda n: next(draws)), \
         patch.object(AS, "_redis", return_value=r), \
         patch.object(E, "_get_redis", return_value=r), \
         patch.object(E, "_cognito_client", return_value=cognito), \
         patch.object(AS, "_cognito", return_value=cognito), \
         patch("app.services.email.send_email_change_code",
               side_effect=lambda **kw: sent.append(("code", kw))), \
         patch("app.services.email.send_email_changed_notice",
               side_effect=lambda **kw: sent.append(("notice", kw))):
        yield {"redis": r, "cognito": cognito, "sent": sent}


def _person(db, email="jo@example.com", role="walker"):
    e = make_employee(db, role=role, name="Jo Rivera")
    e.email = email
    e.username = "jo.rivera"
    e.cognito_sub = str(uuid.uuid4())
    db.commit()
    return e


def _audits(db, action):
    return db.query(AuditLog).filter(AuditLog.action_type == action).all()


# ── D2: a session issued before the change is refused ───────────────────────

class TestTokensIssuedBeforeAChangeAreRefused:
    def test_no_stamp_means_every_token_is_fine(self, db):
        e = _person(db)
        assert not deps._issued_before_revocation(e, {"auth_time": 1})

    def test_a_token_from_before_the_change_is_refused(self, db):
        e = _person(db)
        e.tokens_valid_after = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
        before = int(e.tokens_valid_after.timestamp()) - 1
        assert deps._issued_before_revocation(e, {"auth_time": before})

    def test_the_sign_in_in_the_same_second_is_accepted(self, db):
        """iat is whole seconds; the stamp is floored, so the sign-in that
        immediately follows the change is not refused."""
        e = _person(db)
        e.tokens_valid_after = datetime(2026, 10, 19, 12, 0, 0, 700000, tzinfo=timezone.utc)
        assert not deps._issued_before_revocation(e, {"auth_time": int(e.tokens_valid_after.timestamp())})

    def test_a_token_without_a_sign_in_time_is_refused_once_stamped(self, db):
        e = _person(db)
        e.tokens_valid_after = datetime.now(timezone.utc)
        assert deps._issued_before_revocation(e, {})

    def test_get_caller_employee_answers_401(self, db):
        e = _person(db)
        stamp = datetime.now(timezone.utc)
        e.tokens_valid_after = stamp
        db.commit()
        # From the AWARE stamp, not e.tokens_valid_after: after the commit
        # SQLite hands it back naive, and .timestamp() on a naive value applies
        # the host's local offset. This test used to compute auth_time that
        # way and passed only because deps made the same mistake (ADR-549:
        # deps now reads a naive stamp as UTC, as it is stored).
        user = {"id": e.cognito_sub, "username": e.username, "email": e.email,
                "cognito_groups": [], "auth_time": int(stamp.timestamp()) - 60}
        with pytest.raises(HTTPException) as exc:
            deps.get_caller_employee(current_user=user, db=db)
        assert exc.value.status_code == 401
        assert exc.value.detail["code"] == "credentials_changed"

    def test_a_public_endpoint_treats_it_as_no_token(self, db):
        e = _person(db)
        e.tokens_valid_after = datetime.now(timezone.utc)
        db.commit()
        user = {"id": e.cognito_sub, "username": e.username, "email": e.email,
                "cognito_groups": [], "auth_time": 1}
        assert deps.get_caller_employee_anonymous(current_user=user, db=db) is None

    def test_the_token_dict_carries_the_sign_in_time_not_the_issue_time(self):
        """iat moves on every refresh; auth_time does not. Checking iat would let
        a session that survived a failed global sign-out refresh past the stamp."""
        src = inspect.getsource(deps.get_current_user)
        assert '"auth_time": payload.get("auth_time"' in src

    def test_a_refreshed_token_from_an_old_sign_in_is_still_refused(self, db):
        e = _person(db)
        e.tokens_valid_after = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        stamp = int(e.tokens_valid_after.timestamp())
        # Refreshed AFTER the change (new iat), signed in BEFORE it.
        assert deps._issued_before_revocation(e, {"auth_time": stamp - 3600, "iat": stamp + 60})


# ── D1: a password change needs the emailed code ────────────────────────────

class TestPasswordChange:
    def test_the_code_goes_through_cognito_forgot_password(self, db, env):
        e = _person(db)
        out = E.request_password_code(caller=e, _={})
        env["cognito"].forgot_password.assert_called_once()
        kw = env["cognito"].forgot_password.call_args.kwargs
        assert kw["Username"] == "jo.rivera"
        assert out["sent_to"] == "j•••@example.com"

    def test_no_email_is_refused_before_cognito_is_asked(self, db, env):
        e = _person(db, email=None)
        with pytest.raises(HTTPException) as exc:
            E.request_password_code(caller=e, _={})
        assert exc.value.status_code == 409
        env["cognito"].forgot_password.assert_not_called()

    def test_an_unverified_email_in_cognito_reads_as_no_email(self, db, env):
        e = _person(db)
        env["cognito"].forgot_password.side_effect = _client_error("InvalidParameterException")
        with pytest.raises(HTTPException) as exc:
            E.request_password_code(caller=e, _={})
        assert exc.value.status_code == 409

    def test_requests_are_capped(self, db, env):
        e = _person(db)
        for _ in range(AS.MAX_CODE_REQUESTS_PER_HOUR):
            E.request_password_code(caller=e, _={})
        with pytest.raises(HTTPException) as exc:
            E.request_password_code(caller=e, _={})
        assert exc.value.status_code == 429

    def test_the_right_code_changes_it_and_ends_every_session(self, db, env):
        e = _person(db)
        out = E.confirm_password_change(
            payload=E._PasswordConfirmRequest(code="123456", new_password=_NEW_PASSWORD),
            caller=e, db=db, _={},
        )
        env["cognito"].confirm_forgot_password.assert_called_once()
        env["cognito"].admin_user_global_sign_out.assert_called_once()
        assert e.tokens_valid_after is not None
        assert out["signed_out"] is True
        [a] = _audits(db, "account.password_changed")
        assert a.after_snapshot["confirmed_by"] == "email_code"

    def test_a_wrong_code_changes_nothing(self, db, env):
        e = _person(db)
        env["cognito"].confirm_forgot_password.side_effect = _client_error("CodeMismatchException")
        with pytest.raises(HTTPException) as exc:
            E.confirm_password_change(
                payload=E._PasswordConfirmRequest(code="000000", new_password=_NEW_PASSWORD),
                caller=e, db=db, _={},
            )
        assert exc.value.status_code == 400
        env["cognito"].admin_user_global_sign_out.assert_not_called()
        assert e.tokens_valid_after is None
        assert _audits(db, "account.password_changed") == []

    def test_a_cognito_sign_out_failure_still_stamps(self, db, env):
        """The stamp is the half this API enforces; it must not depend on AWS."""
        e = _person(db)
        env["cognito"].admin_user_global_sign_out.side_effect = _client_error("InternalErrorException")
        E.confirm_password_change(
            payload=E._PasswordConfirmRequest(code="123456", new_password=_NEW_PASSWORD),
            caller=e, db=db, _={},
        )
        assert e.tokens_valid_after is not None
        [a] = _audits(db, "account.password_changed")
        assert a.after_snapshot["signed_out_everywhere"] is False

    def test_the_request_rejects_unknown_keys(self):
        with pytest.raises(Exception):
            E._PasswordConfirmRequest(code="123456", new_password=_NEW_PASSWORD, old_password=make_test_password())


# ── R2/D3: an email change needs codes from both inboxes ────────────────────

def _codes(env):
    """The codes the stubbed sender was asked to email, by which inbox."""
    return {kw["which"]: (kw["to_email"], kw["code"]) for kind, kw in env["sent"] if kind == "code"}


class TestEmailChange:
    def test_one_code_goes_to_each_address(self, db, env):
        e = _person(db)
        out = E.request_email_change(payload=E._EmailChangeRequest(new_email="New@Example.org"),
                                     caller=e, db=db, _={})
        codes = _codes(env)
        assert codes["current"][0] == "jo@example.com"
        assert codes["new"][0] == "new@example.org"
        assert out["new_masked"] == "n•••@example.org"

    def test_an_account_with_no_email_is_sent_to_an_admin(self, db, env):
        """R3: nothing to confirm against, and self-service would be a takeover."""
        e = _person(db, email=None)
        with pytest.raises(HTTPException) as exc:
            E.request_email_change(payload=E._EmailChangeRequest(new_email="me@example.org"),
                                   caller=e, db=db, _={})
        assert exc.value.status_code == 409
        assert "admin" in exc.value.detail

    def test_both_codes_change_it_tell_the_old_inbox_and_end_sessions(self, db, env):
        e = _person(db)
        E.request_email_change(payload=E._EmailChangeRequest(new_email="new@example.org"),
                               caller=e, db=db, _={})
        c = _codes(env)
        E.confirm_email_change(
            payload=E._EmailConfirmRequest(current_code=c["current"][1], new_code=c["new"][1]),
            caller=e, db=db, _={},
        )
        kw = env["cognito"].admin_update_user_attributes.call_args.kwargs
        assert {"Name": "email", "Value": "new@example.org"} in kw["UserAttributes"]
        assert {"Name": "email_verified", "Value": "true"} in kw["UserAttributes"]
        assert e.email == "new@example.org"
        assert e.tokens_valid_after is not None
        env["cognito"].admin_user_global_sign_out.assert_called_once()
        notices = [kw for kind, kw in env["sent"] if kind == "notice"]
        assert [n["to_email"] for n in notices] == ["jo@example.com"]
        [a] = _audits(db, "account.email_changed")
        assert a.after_snapshot["from"] == "j•••@example.com"          # masked, never the address
        assert "jo@example.com" not in str(a.after_snapshot)

    def test_swapped_codes_are_refused(self, db, env):
        """Each code is bound to its inbox: the new-address code can't stand in
        for the current-address one."""
        e = _person(db)
        E.request_email_change(payload=E._EmailChangeRequest(new_email="new@example.org"),
                               caller=e, db=db, _={})
        c = _codes(env)
        assert c["current"][1] != c["new"][1]   # pinned draws (fixture)
        with pytest.raises(HTTPException) as exc:
            E.confirm_email_change(
                payload=E._EmailConfirmRequest(current_code=c["new"][1], new_code=c["current"][1]),
                caller=e, db=db, _={},
            )
        assert exc.value.status_code == 400
        assert e.email == "jo@example.com"
        env["cognito"].admin_update_user_attributes.assert_not_called()

    def test_five_wrong_guesses_burn_the_code(self, db, env):
        e = _person(db)
        E.request_email_change(payload=E._EmailChangeRequest(new_email="new@example.org"),
                               caller=e, db=db, _={})
        c = _codes(env)
        wrong = "999999" if c["current"][1] != "999999" else "888888"
        details = []
        for _ in range(AS.MAX_CODE_ATTEMPTS):
            with pytest.raises(HTTPException) as exc:
                E.confirm_email_change(
                    payload=E._EmailConfirmRequest(current_code=wrong, new_code=c["new"][1]),
                    caller=e, db=db, _={},
                )
            details.append(exc.value.detail)
        assert "expired" in details[-1]
        with pytest.raises(HTTPException):   # the right code no longer works
            E.confirm_email_change(
                payload=E._EmailConfirmRequest(current_code=c["current"][1], new_code=c["new"][1]),
                caller=e, db=db, _={},
            )
        assert e.email == "jo@example.com"

    def test_the_same_address_is_refused(self, db, env):
        e = _person(db)
        with pytest.raises(HTTPException) as exc:
            E.request_email_change(payload=E._EmailChangeRequest(new_email="JO@example.com"),
                                   caller=e, db=db, _={})
        assert exc.value.status_code == 400


# ── D4's precondition: no flow calls Cognito's user-level APIs ──────────────

USER_LEVEL = {"change_password", "update_user_attributes", "verify_user_attribute",
              "get_user_attribute_verification_code", "set_user_mfa_preference"}


def test_no_backend_code_calls_a_user_level_cognito_api():
    """ADR-541 D4 reads these, in CloudTrail, as someone going around the app.
    Walks every call site in app/, not a list of known endpoints."""
    import pathlib
    hits = []
    for f in pathlib.Path(E.__file__).resolve().parents[1].rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in USER_LEVEL:
                hits.append(f"{f.name}:{n.lineno} {n.func.attr}")
    assert hits == [], hits


def test_every_self_service_endpoint_lets_every_role_in():
    """The old email gate left out captain, field_supervisor and driver_trainee."""
    from app.models.employee import VALID_ROLES
    assert set(E._allow_self.allowed_roles) == set(VALID_ROLES)


# ── Amendment (2026-10-19 staging walk-through): the other device is told why,
#    and learns within a minute ───────────────────────────────────────────────

import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[3]


def test_the_session_check_endpoint_runs_the_full_caller_check():
    sig = inspect.signature(E.check_session).parameters
    assert sig["caller"].default.dependency is deps.get_caller_employee
    assert sig["_"].default is E._allow_self or sig["_"].default.dependency is E._allow_self
    assert E.check_session(caller=object(), _={}) == {"ok": True}


def test_the_web_records_the_reason_before_signing_out():
    """The race: signOut() flips the auth state and App's <Navigate to="/login">
    wins while the await is pending, dropping a reason carried only in the URL."""
    src = (_REPO / "frontend/src/api/axiosClient.ts").read_text()
    block = src[src.index("error.response?.status === 401"):]
    assert block.index("sessionStorage.setItem('asheflow_session_ended'") < block.index("await signOut()")


def test_the_sign_in_page_reads_the_stored_reason_once():
    src = (_REPO / "frontend/src/components/auth/Login.tsx").read_text()
    assert "sessionStorage.getItem('asheflow_session_ended')" in src
    assert "sessionStorage.removeItem('asheflow_session_ended')" in src


def test_an_open_web_tab_checks_on_focus_and_every_minute():
    src = (_REPO / "frontend/src/hooks/useSessionTimeout.ts").read_text()
    assert "SESSION_CHECK_MS = 60 * 1000" in src
    assert "'/employees/me/session'" in src and "visibilitychange" in src
    # Platform accounts have no Employee row: the check would 403 for them.
    assert "isPlatform" in src and "'surveyor'" in src


def test_the_mobile_app_checks_on_foreground_and_every_minute():
    """D7: web AND mobile."""
    src = (_REPO / "mobile/src/contexts/AuthContext.tsx").read_text()
    assert "'/employees/me/session'" in src
    assert "AppState.addEventListener('change'" in src and "60_000" in src
