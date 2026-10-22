"""Every two-factor reset tells the person, at the account's verified address (ADR-561).

Three paths reset someone's second factor; before this only the surveyor
reset emailed them. A reset nobody hears about reads like tampering, and is
how an unwanted reset goes unnoticed.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.employee import Employee
from app.routers import employees as E
from app.routers import platform_alerts as PA
from app.services import account_security, mfa_containment
from tests.conftest import SEED_COMPANY_ID

OK = mfa_containment.ContainmentResult(2, True, True, [])


def _user(email="person@recovery.example", verified="true", name="Jo Doe"):
    return {"Username": "jo.doe", "UserAttributes": [
        {"Name": "email", "Value": email}, {"Name": "email_verified", "Value": verified},
        {"Name": "name", "Value": name}, {"Name": "sub", "Value": str(uuid.uuid4())}]}


# ── the helper: verified Cognito address only, never raises ────────────────

@pytest.mark.real_reset_notice
def test_it_emails_the_verified_cognito_address():
    cog = MagicMock(); cog.admin_get_user.return_value = _user()
    with patch.object(account_security, "_cognito", return_value=cog), \
         patch("app.services.email.send_mfa_reset_notice") as send:
        ok = account_security.notify_mfa_reset("jo.doe", reset_by="An admin at your company",
                                               account="your AsheFlow account",
                                               if_not_you="tell your manager", account_ref="x", reason="lost phone")
    assert ok is True
    kw = send.call_args.kwargs
    assert kw["to_email"] == "person@recovery.example" and kw["reason"] == "lost phone"


@pytest.mark.real_reset_notice
def test_an_unverified_address_gets_nothing():
    cog = MagicMock(); cog.admin_get_user.return_value = _user(verified="false")
    with patch.object(account_security, "_cognito", return_value=cog), \
         patch("app.services.email.send_mfa_reset_notice") as send:
        assert account_security.notify_mfa_reset("jo.doe", reset_by="x", account="y", if_not_you="z",
                                                 account_ref="r") is False
    send.assert_not_called()


@pytest.mark.real_reset_notice
@pytest.mark.parametrize("fail_at", ["lookup", "send"])
def test_a_failure_never_raises(fail_at):
    cog = MagicMock()
    if fail_at == "lookup":
        cog.admin_get_user.side_effect = ClientError({"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
    else:
        cog.admin_get_user.return_value = _user()
    with patch.object(account_security, "_cognito", return_value=cog), \
         patch("app.services.email.send_mfa_reset_notice", side_effect=RuntimeError("ses down")):
        assert account_security.notify_mfa_reset("jo.doe", reset_by="x", account="y", if_not_you="z",
                                                 account_ref="r") is False


# ── the tenant reset ───────────────────────────────────────────────────────

def _pair(db):
    admin = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="Admin", role="admin",
                     is_active=True, username="the.admin", cognito_sub=str(uuid.uuid4()))
    target = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="Walker", role="walker",
                      is_active=True, username="the.walker", cognito_sub=str(uuid.uuid4()),
                      email="db-copy@example.com")
    db.add_all([admin, target]); db.commit()
    return admin, target


def test_the_tenant_reset_tells_the_person_and_says_so(db, _no_real_reset_notice):
    admin, target = _pair(db)
    _no_real_reset_notice.return_value = True
    with patch.object(E.mfa_containment, "contain", return_value=OK):
        out = E.reset_employee_mfa(employee_id=target.id, body=E.MfaResetIn(reason="Lost their phone at work"),
                                   db=db, caller=admin, _={})
    assert out["emailed"] is True
    args, kw = _no_real_reset_notice.call_args
    assert args == ("the.walker",), "looked up by the Cognito username, never Employee.email"
    assert kw["reset_by"] == "An admin at your company" and kw["reason"] == "Lost their phone at work"
    row = db.query(AuditLog).filter(AuditLog.action_type == "employee.mfa_reset").one()
    assert row.after_snapshot["reason"] == "Lost their phone at work"   # write_audit's detail -> after


def test_the_tenant_reset_works_without_a_reason(db, _no_real_reset_notice):
    """Both web dialogs confirm without a text field; the reason is optional."""
    admin, target = _pair(db)
    with patch.object(E.mfa_containment, "contain", return_value=OK):
        out = E.reset_employee_mfa(employee_id=target.id, body=None, db=db, caller=admin, _={})
    assert out["emailed"] is False and _no_real_reset_notice.call_args.kwargs["reason"] is None


@pytest.mark.parametrize("bad", [{"reason": "short"}, {"reason": "x" * 201}, {"reason": "ok ok ok ok", "extra": 1}])
def test_the_tenant_reason_is_bounded(bad):
    with pytest.raises(ValidationError):
        E.MfaResetIn(**bad)


# ── the super-admin reset ──────────────────────────────────────────────────

def test_the_platform_reset_tells_the_person_and_says_so(db, _no_real_reset_notice):
    sub = str(uuid.uuid4())
    cog = MagicMock()
    cog.list_users.return_value = {"Users": [{"Username": "test.support"}]}   # resolve by account id
    cog.admin_get_user.return_value = {"Username": "test.support",
                                       "UserAttributes": [{"Name": "sub", "Value": sub}]}
    _no_real_reset_notice.return_value = True
    with patch.object(PA.boto3, "client", return_value=cog), \
         patch.object(PA.mfa_containment, "contain", return_value=OK):
        out = PA.platform_reset_mfa(body=PA.MfaResetRequest(account_id=uuid.UUID(sub),
                                                            reason="Requested via support ticket"),
                                    _super={"id": "owner", "cognito_groups": ["super_admin"]}, db=db)
    assert out["emailed"] is True
    args, kw = _no_real_reset_notice.call_args
    assert args == ("test.support",) and kw["reset_by"] == "The AsheFlow team"
    assert kw["reason"] == "Requested via support ticket"
    row = db.query(AuditLog).filter(AuditLog.action_type == "platform.mfa_reset").one()
    assert row.after_snapshot["reason"] == "Requested via support ticket"


def test_the_platform_reason_is_bounded():
    with pytest.raises(ValidationError):
        PA.MfaResetRequest(username="x.y", reason="short")


# ── the surveyor reset goes through the same notice ───────────────────────

def test_the_surveyor_notice_is_the_shared_one():
    from app.services import email
    with patch.object(email, "send_mfa_reset_notice") as general:
        email.send_surveyor_mfa_reset_notice(to_email="s@e.org", name="S", reason="lost device", account_ref="r")
    kw = general.call_args.kwargs
    assert kw["reset_by"] == "The AsheFlow team" and kw["account"] == "your survey account"
