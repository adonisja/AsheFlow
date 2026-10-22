"""A locked-out person can request a two-factor reset (ADR-551).

Owner, 2026-10-20: "How will the admin reset your MFA, how do you send the
request when locked out?" These drive the real endpoints: the public request
and confirm steps, who is told for each kind of account, the reset closing the
request, and the lists that show it.
"""
import inspect
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import BackgroundTasks, HTTPException

from app.models.employee import Employee
from app.models.mfa_reset_request import MfaResetRequest
from app.models.notification import Notification
from app.models.survey_register import SurveyContributor
from app.routers import auth_mfa_reset as A
from app.routers import employees as E
from app.services import mfa_reset_requests as M
from tests.conftest import SEED_COMPANY_ID
from tests.routers.test_adr513_survey_areas import _tables, city  # noqa: F401  (survey tables)

@pytest.fixture(autouse=True)
def _no_broker():
    """Delivery is enqueued after commit (send_discord.delay); with the test
    Redis unreachable each enqueue waited ~19 s on the broker. Same patch as
    the ADR-507 gallery tests -- and it lets a test see what was enqueued."""
    with patch("app.services.notify._enqueue") as enq:
        yield enq


REQ = A.request_reset_code.__wrapped__        # past slowapi's decorator, which needs a live Request
CONF = A.confirm_reset_request.__wrapped__


def _req(ip="203.0.113.7"):
    r = MagicMock(); r.client.host = ip
    return r


def _cognito_user(sub, username="the.walker", email="w@example.org", verified=True, groups=()):
    c = MagicMock()
    c.admin_get_user.return_value = {"Username": username, "UserAttributes": [
        {"Name": "sub", "Value": sub}, {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true" if verified else "false"}, {"Name": "name", "Value": "The Walker"}]}
    c.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": g} for g in groups]}
    return c


def _emp(db, role, sub=None, name=None):
    e = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=name or role.title(), role=role,
                 is_active=True, username=f"{role}.{uuid.uuid4().hex[:4]}", cognito_sub=sub or str(uuid.uuid4()))
    db.add(e); db.commit()
    return e


# ── D2 step 1: always the same answer; email only a verified inbox ─────────

@pytest.mark.parametrize("case", ["unknown", "unverified", "verified"])
def test_step_one_answers_the_same_for_every_account(case):
    c = MagicMock()
    if case == "unknown":
        c.admin_get_user.side_effect = ClientError({"Error": {"Code": "UserNotFoundException"}}, "x")
    else:
        c = _cognito_user(str(uuid.uuid4()), verified=(case == "verified"))
    bg = BackgroundTasks()
    with patch.object(A, "_cognito", return_value=c), \
         patch.object(A.account_security, "allow_request", return_value=True), \
         patch.object(A.account_security, "issue_code", return_value="123456") as issue:
        out = REQ(request=_req(), body=A._RequestIn(username="someone"), background=bg)
    assert out["detail"] == A._SENT["detail"]              # never reveals whether the name exists
    assert set(out) == {"detail", "request_token"}         # a ticket for every name, real or decoy
    assert (len(bg.tasks) == 1) == (case == "verified")    # emailed only to a verified inbox
    assert issue.called == (case == "verified")


def test_step_one_is_capped_per_account_before_lookup():
    with patch.object(A.account_security, "allow_request", return_value=False), \
         patch.object(A, "_cognito") as cog:
        with pytest.raises(HTTPException) as exc:
            REQ(request=_req(), body=A._RequestIn(username="Someone"), background=BackgroundTasks())
    assert exc.value.status_code == 429
    cog.assert_not_called()   # capped even for names that don't exist: same cost for both


def test_both_public_steps_are_rate_limited_on_the_client_ip():
    src = inspect.getsource(A)
    assert src.count("@limiter.limit(") == 2
    from app.api.ratelimit import limiter
    from slowapi.util import get_remote_address
    assert limiter._key_func is get_remote_address


# ── D2 step 2 + D3: confirm, record once, tell the right people ────────────

def _confirm(db, cognito, outcome="ok", alert=None):
    """Step 2 with a REAL ticket for the account the stub Cognito describes."""
    attrs = {a["Name"]: a["Value"] for a in cognito.admin_get_user.return_value["UserAttributes"]}
    token = A.reset_request_token.issue(attrs["sub"], cognito.admin_get_user.return_value["Username"])
    with patch.object(A, "_cognito", return_value=cognito), \
         patch.object(A.account_security, "check_code", return_value=outcome), \
         patch("app.services.integration_alerts.raise_platform_alert", alert or MagicMock()):
        return CONF(request=_req(), body=A._ConfirmIn(request_token=token, code="123456"), db=db)


def test_a_wrong_code_records_nothing(db):
    sub = str(uuid.uuid4()); _emp(db, "walker", sub=sub)
    with pytest.raises(HTTPException) as exc:
        _confirm(db, _cognito_user(sub), outcome="wrong")
    assert exc.value.status_code == 400
    assert db.query(MfaResetRequest).count() == 0


def test_an_employee_request_reaches_their_admins_once(db, _no_broker):
    sub = str(uuid.uuid4())
    walker = _emp(db, "walker", sub=sub, name="The Walker")
    admin, mgmt, dispatch = _emp(db, "admin"), _emp(db, "management"), _emp(db, "dispatch")
    out = _confirm(db, _cognito_user(sub))
    assert out["sent_to"] == "your company's admins"
    # ADR-561 D5: every reset path now emails the person, so every kind is promised it.
    assert "email you" in out["detail"] and "sign in" in out["detail"]
    req = db.query(MfaResetRequest).one()
    assert (req.account_kind, req.company_id, req.request_ip) == ("employee", SEED_COMPANY_ID, "203.0.113.7")
    told = {n.employee_id for n in db.query(Notification).filter(Notification.type == "mfa_reset_requested")}
    assert told == {admin.id, mgmt.id}, "only the people who can reset; never dispatch or the requester"
    assert _no_broker.call_count == 2, "the request must reach delivery (push/Discord), not just the inbox"
    _confirm(db, _cognito_user(sub))                      # asking again
    assert db.query(MfaResetRequest).count() == 1
    assert db.query(Notification).filter(Notification.type == "mfa_reset_requested").count() == 2


def test_a_surveyor_request_is_for_support(db):
    sub = str(uuid.uuid4())
    c = SurveyContributor(id=uuid.uuid4(), cognito_sub=sub, display_name="S", cognito_username="s",
                          agreement_version="v1", agreement_signed_on=date(2026, 10, 1))
    db.add(c); db.commit()
    out = _confirm(db, _cognito_user(sub, groups=("surveyor",)))
    assert out["sent_to"] == "AsheFlow support"
    # ADR-556 D4: the surveyor reset emails them (send_surveyor_mfa_reset_notice).
    assert "email you" in out["detail"] and "set up two-factor again" in out["detail"]
    assert out["detail"] == f"Request sent to AsheFlow support. {out['next_step']}"
    req = db.query(MfaResetRequest).one()
    assert (req.account_kind, req.contributor_id) == ("surveyor", c.id)


def test_a_staff_request_raises_a_platform_alert(db):
    alert = MagicMock()
    out = _confirm(db, _cognito_user(str(uuid.uuid4()), username="test.support",
                                     groups=("platform_support",)), alert=alert)
    assert out["sent_to"] == "a super admin"
    assert "email you" in out["detail"]                 # ADR-561 D5
    assert alert.call_args.kwargs["alert_type"] == "mfa.reset_requested"
    assert db.query(MfaResetRequest).one().account_kind == "staff"


def test_an_account_with_no_one_to_ask_is_refused(db):
    with pytest.raises(HTTPException) as exc:
        _confirm(db, _cognito_user(str(uuid.uuid4())))      # no row, no group
    assert exc.value.status_code == 409


# ── D4: the reset closes the request ───────────────────────────────────────

def test_the_tenant_reset_closes_the_request(db):
    sub = str(uuid.uuid4()); walker = _emp(db, "walker", sub=sub); admin = _emp(db, "admin")
    _confirm(db, _cognito_user(sub))
    with patch.object(E.mfa_containment, "contain",
                      return_value=E.mfa_containment.ContainmentResult(0, True, True, [])):
        E.reset_employee_mfa(employee_id=walker.id, db=db, caller=admin, _={})
    req = db.query(MfaResetRequest).one()
    assert req.status == "resolved" and req.resolved_by_ref == str(admin.id)


# ── D3: the lists ──────────────────────────────────────────────────────────

def test_the_company_list_is_scoped_and_drops_stale_requests(db):
    from app.models.company import Company
    other = uuid.uuid4()
    db.add(Company(id=other, name="Other", slug="other", is_active=True)); db.commit()
    fresh, stale = _emp(db, "walker", name="Fresh"), _emp(db, "walker", name="Stale")
    foreign = Employee(id=uuid.uuid4(), company_id=other, name="Foreign", role="walker",
                       is_active=True, cognito_sub=str(uuid.uuid4()))
    db.add(foreign); db.commit()
    now = datetime.now(timezone.utc)
    for e, at in ((fresh, now), (stale, now - timedelta(days=8)), (foreign, now)):
        db.add(MfaResetRequest(cognito_sub=e.cognito_sub, account_kind="employee", status="pending",
                               company_id=e.company_id, requested_at=at))
    db.commit()
    rows = E.list_mfa_reset_requests(caller=_emp(db, "admin"), _={}, db=db)
    assert [r.name for r in rows] == ["Fresh"]


def test_the_lists_carry_the_request():
    assert "reset_requested_at" in E.EmployeeMfaEnrolmentResponse.model_fields
    from app.routers import platform_alerts as PA, survey_register as R
    assert "reset_requested_at" in PA.PlatformStaffOut.model_fields
    assert "reset_requested_at" in R.ContributorHealthOut.model_fields


# ── D1/D5: both clients ────────────────────────────────────────────────────

import pathlib
ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("login,comp", [
    (ROOT / "frontend/src/components/auth/Login.tsx", ROOT / "frontend/src/components/auth/ResetRequest.tsx"),
    (ROOT / "mobile/src/screens/Auth/LoginScreen.tsx", ROOT / "mobile/src/screens/Auth/ResetRequest.tsx"),
], ids=["web", "mobile"])
def test_both_lockout_screens_offer_the_request(login, comp):
    src = login.read_text()
    assert src.count("<ResetRequest") >= 1 and "mfaSetupClosed" in src
    flow = comp.read_text()
    assert "'/auth/mfa-reset/request'" in flow and "'/auth/mfa-reset/confirm'" in flow
    assert "ask an administrator to reset" not in src, "the panel must point at the request, not a person"


def test_the_panel_line_no_longer_promises_an_unreachable_admin():
    src = (ROOT / "frontend/src/components/SecurityPanel.tsx").read_text()
    assert "An admin can reset your second factor" not in src
    assert "request a reset from the sign-in screen" in src


def test_admins_see_the_requests_with_the_reset_button():
    src = (ROOT / "frontend/src/pages/Assets.tsx").read_text()
    assert "'/employees/mfa-reset-requests'" in src
    assert "handleResetMfa({ id: r.employee_id, name: r.name })" in src


def test_an_admin_asking_is_not_told_about_their_own_request(db):
    """Probe 4 first passed: the requester was a walker, never notified anyway."""
    sub = str(uuid.uuid4())
    asker = _emp(db, "admin", sub=sub)
    other = _emp(db, "admin")
    _confirm(db, _cognito_user(sub))
    told = {n.employee_id for n in db.query(Notification).filter(Notification.type == "mfa_reset_requested")}
    assert told == {other.id}


def test_one_pending_request_per_account_is_enforced_by_the_database():
    """Probe 5 first passed: with the early return removed, the INDEX still
    refused the duplicate. So the index is the guarantee -- pin it."""
    idx = next(i for i in MfaResetRequest.__table__.indexes if i.name == "uq_mfa_reset_request_pending")
    assert idx.unique and [c.name for c in idx.columns] == ["cognito_sub"]
    assert "pending" in str(idx.dialect_options["postgresql"]["where"])
    mig = next(pathlib.Path(__file__).resolve().parents[2].glob("alembic/versions/*_adr551_mfa_reset_requests.py")).read_text()
    assert 'unique=True' in mig and "status = 'pending'" in mig


@pytest.mark.parametrize("comp", [ROOT / "frontend/src/components/auth/ResetRequest.tsx",
                                  ROOT / "mobile/src/screens/Auth/ResetRequest.tsx"], ids=["web", "mobile"])
def test_the_person_is_not_asked_for_their_username_again(comp):
    """Owner, 2026-10-20: they typed it to reach this screen. The server turns
    it into the account's permanent ID; the person never re-enters anything."""
    src = comp.read_text()
    assert "const name = username;" in src
    assert "setName" not in src and 'id="rr-user"' not in src and 'accessibilityLabel="Username"' not in src



# ── D2b: the ticket ────────────────────────────────────────────────────────

from app.services import reset_request_token as T


def test_the_ticket_hides_the_account():
    sub = str(uuid.uuid4())
    tok = T.issue(sub, "test.surveyor")
    assert sub not in tok and "test.surveyor" not in tok
    import base64
    raw = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4))
    assert sub.encode() not in raw and b"test.surveyor" not in raw, "encrypted, not just encoded"
    assert T.read(tok) == (sub, "test.surveyor")


def test_a_tampered_or_foreign_ticket_is_refused():
    tok = T.issue(str(uuid.uuid4()), "x")
    assert T.read(tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")) is None
    from cryptography.fernet import Fernet
    assert T.read(Fernet(Fernet.generate_key()).encrypt(b'{"p":"mfa_reset_request","sub":"s"}').decode()) is None


def test_the_ticket_expires_with_the_code():
    tok = T.issue(str(uuid.uuid4()), "x")
    import time as _t
    with patch("cryptography.fernet.time.time", return_value=_t.time() + T.TOKEN_TTL_SECONDS + 5):
        assert T.read(tok) is None


def test_step_two_takes_no_username():
    with pytest.raises(Exception):
        A._ConfirmIn(username="x", request_token="a" * 40, code="123456")


def test_a_decoy_and_a_wrong_code_answer_identically(db):
    """A decoy's code was never sent, so it reads as 'expired'. If that were
    worded differently from 'wrong', the decoy would reveal itself."""
    answers = []
    for outcome in ("wrong", "expired"):
        with patch.object(A.account_security, "check_code", return_value=outcome), \
             patch.object(A, "_cognito") as cog:
            with pytest.raises(HTTPException) as exc:
                CONF(request=_req(), body=A._ConfirmIn(request_token=T.decoy("nobody"), code="123456"), db=db)
            cog.assert_not_called()          # the code is checked before any account lookup
            answers.append((exc.value.status_code, exc.value.detail))
    assert answers[0] == answers[1]


def test_a_ticket_cannot_be_moved_to_another_account(db):
    """The ticket names the account; a code for a DIFFERENT account's key never
    matches, because the code is checked under the ticket's sub."""
    seen = []
    with patch.object(A.account_security, "check_code",
                      side_effect=lambda key, purpose, code: seen.append(key) or "wrong"):
        with pytest.raises(HTTPException):
            sub = str(uuid.uuid4())
            CONF(request=_req(), body=A._ConfirmIn(request_token=T.issue(sub, "a"), code="123456"), db=db)
    assert seen == [f"mfareq:{sub}"]


def test_both_clients_send_the_ticket_not_the_name():
    for comp in (ROOT / "frontend/src/components/auth/ResetRequest.tsx",
                 ROOT / "mobile/src/screens/Auth/ResetRequest.tsx"):
        src = comp.read_text()
        assert "request_token: token" in src
        confirm_call = src[src.index("'/auth/mfa-reset/confirm'"):][:120]
        assert "username" not in confirm_call
