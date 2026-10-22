"""Every account can change its email; an admin can for someone who lost the
inbox; Cognito stays the record (ADR-563).

Found: an admin's edit of an ACTIVE employee's email changed only the
database copy (staging walker.test: walker.test@asheflow.internal in the DB,
walker@test.com in Cognito), platform accounts couldn't change email at all,
and the self-service flow proved "the current address" against the database.

Every Cognito and email call here is stubbed: locally the settings carry the
real staging pool (ADR-561 found that).
"""
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.email_change_request import EmailChangeRequest
from app.models.employee import Employee
from app.models.platform_session import PlatformSessionStamp
from app.routers import employees as E
from app.routers import platform_alerts as PA
from app.schemas.employee import EmployeeUpdate
from app.services import account_security, email_change
from tests.conftest import SEED_COMPANY_ID


@pytest.fixture(autouse=True)
def _survey_table(db):
    """apply_change mirrors a surveyor's email; the shared schema omits survey tables."""
    from app.models.survey_register import SurveyContributor
    SurveyContributor.__table__.create(bind=db.get_bind(), checkfirst=True)
    yield


def _cog(email="old@recovery.example", verified="true", sub=None, groups=(), username="the.person",
         others=()):
    sub = sub or str(uuid.uuid4())
    c = MagicMock()
    c.admin_get_user.return_value = {"Username": username, "UserAttributes": [
        {"Name": "sub", "Value": sub}, {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": verified}, {"Name": "name", "Value": "The Person"}]}
    c.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": g} for g in groups]}
    c.list_users.return_value = {"Users": [{"Attributes": [{"Name": "sub", "Value": s}]} for s in others]}
    c.sub = sub
    return c


@contextmanager
def _aws(cog):
    with patch.object(account_security, "_cognito", return_value=cog), \
         patch("app.services.email.send_email_changed_notice") as old_notice, \
         patch("app.services.email.send_email_change_link") as link, \
         patch("app.services.integration_alerts.raise_platform_alert") as alert:
        yield {"old_notice": old_notice, "link": link, "alert": alert}


def _emp(db, role="walker", username="the.person", sub=None, email="db-copy@example.com", status="active"):
    e = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=f"E {username}", role=role, is_active=True,
                 username=username, cognito_sub=sub, email=email, account_status=status)
    db.add(e); db.commit()
    return e


# ── D1: apply_change writes Cognito, mirrors, ends sessions, tells the OLD address ──

def test_apply_writes_cognito_then_mirrors_and_tells_the_cognito_address(db):
    cog = _cog()
    emp = _emp(db, sub=cog.sub)
    with _aws(cog) as m:
        out = email_change.apply_change(db, username="the.person", new_email="New@Example.com",
                                        actor={"kind": "self", "ref": "x"}, confirmed_by="codes_to_both_addresses")
    attrs = {a["Name"]: a["Value"] for a in cog.admin_update_user_attributes.call_args.kwargs["UserAttributes"]}
    assert attrs == {"email": "new@example.com", "email_verified": "true"}
    db.refresh(emp)
    assert emp.email == "new@example.com" and emp.tokens_valid_after is not None
    # The OLD address is Cognito's, not the drifted database copy.
    assert m["old_notice"].call_args.kwargs["to_email"] == "old@recovery.example"
    row = db.query(AuditLog).filter(AuditLog.action_type == "account.email_changed").one()
    assert "new@example.com" not in str(row.after_snapshot), "addresses are masked in the audit"
    assert out["old_notified"] is True
    m["alert"].assert_not_called()


def test_a_platform_account_gets_a_session_stamp_and_an_alert_if_privileged(db):
    cog = _cog(groups=("platform_support",), username="sup.port")
    with _aws(cog) as m:
        email_change.apply_change(db, username="sup.port", new_email="n@example.com",
                                  actor={"kind": "self", "ref": cog.sub}, confirmed_by="codes_to_both_addresses")
    assert db.get(PlatformSessionStamp, cog.sub) is not None
    assert m["alert"].call_args.kwargs["alert_type"] == "account.email_changed"


# ── D3: admin-started change waits for the NEW inbox ──────────────────────

def test_start_sends_the_link_only_to_the_new_address_and_stores_a_hash(db):
    cog = _cog()
    with _aws(cog) as m:
        email_change.start_admin_change(db, username="the.person", kind="employee", company_id=SEED_COMPANY_ID,
                                        new_email="fresh@example.com", by_kind="tenant_admin", by_ref="a",
                                        by_label="An admin at your company")
    kw = m["link"].call_args.kwargs
    assert kw["to_email"] == "fresh@example.com"
    req = db.query(EmailChangeRequest).one()
    assert req.status == "pending" and req.token_hash == email_change.token_hash(kw["token"])
    assert kw["token"] not in (req.token_hash,), "the raw token is never stored"
    cog.admin_update_user_attributes.assert_not_called()   # nothing changes yet


def test_starting_again_replaces_the_pending_change(db):
    cog = _cog()
    with _aws(cog):
        for addr in ("a1@example.com", "a2@example.com"):
            email_change.start_admin_change(db, username="the.person", kind="employee", company_id=None,
                                            new_email=addr, by_kind="super_admin", by_ref="s", by_label="x")
    statuses = sorted(r.status for r in db.query(EmailChangeRequest).all())
    assert statuses == ["cancelled", "pending"]


def test_an_address_another_account_uses_is_refused(db):
    cog = _cog(others=[str(uuid.uuid4())])
    with _aws(cog), pytest.raises(email_change.EmailChangeError) as exc:
        email_change.start_admin_change(db, username="the.person", kind="employee", company_id=None,
                                        new_email="taken@example.com", by_kind="super_admin", by_ref="s", by_label="x")
    assert exc.value.status == 409


def test_the_link_works_once_then_not_again(db):
    cog = _cog()
    emp = _emp(db, sub=cog.sub)
    with _aws(cog) as m:
        email_change.start_admin_change(db, username="the.person", kind="employee", company_id=SEED_COMPANY_ID,
                                        new_email="fresh@example.com", by_kind="tenant_admin", by_ref="a", by_label="x")
        token = m["link"].call_args.kwargs["token"]
        email_change.confirm_admin_change(db, token)
        with pytest.raises(email_change.EmailChangeError):
            email_change.confirm_admin_change(db, token)
    db.refresh(emp)
    assert emp.email == "fresh@example.com"
    assert db.query(EmailChangeRequest).one().status == "applied"


def test_an_expired_link_changes_nothing(db):
    cog = _cog()
    with _aws(cog) as m:
        email_change.start_admin_change(db, username="the.person", kind="employee", company_id=None,
                                        new_email="fresh@example.com", by_kind="super_admin", by_ref="s", by_label="x")
        token = m["link"].call_args.kwargs["token"]
        req = db.query(EmailChangeRequest).one()
        req.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1); db.commit()
        with pytest.raises(email_change.EmailChangeError):
            email_change.confirm_admin_change(db, token)
    assert db.query(EmailChangeRequest).one().status == "expired"
    cog.admin_update_user_attributes.assert_not_called()


# ── the tenant admin endpoint ─────────────────────────────────────────────

def _admin(db, role="admin"):
    tag = uuid.uuid4().hex[:6]
    return _emp(db, role=role, username=f"adm.{tag}", sub=str(uuid.uuid4()), email=f"adm.{tag}@example.com")


def test_a_tenant_admin_can_start_a_change_for_their_employee(db):
    admin, cog = _admin(db), _cog()
    target = _emp(db, sub=cog.sub)
    with _aws(cog) as m:
        out = E.admin_start_email_change(employee_id=target.id, body=E.AdminEmailChangeIn(new_email="n@example.com"),
                                         db=db, caller=admin, current_user={"cognito_groups": ["admin"]})
    assert out["pending_email_masked"] != "n@example.com" and m["link"].called


def test_management_cannot_change_an_admins_email(db):
    mgr, cog = _admin(db, role="management"), _cog()
    target = _emp(db, role="admin", sub=cog.sub)
    with _aws(cog), pytest.raises(HTTPException) as exc:
        E.admin_start_email_change(employee_id=target.id, body=E.AdminEmailChangeIn(new_email="n@example.com"),
                                   db=db, caller=mgr, current_user={"cognito_groups": ["management"]})
    assert exc.value.status_code == 403


def test_another_companys_employee_is_not_found(db):
    admin, cog = _admin(db), _cog()
    other = Employee(id=uuid.uuid4(), company_id=uuid.uuid4(), name="X", role="walker", is_active=True,
                     username="x.y", cognito_sub=cog.sub, account_status="active")
    db.add(other); db.commit()
    with _aws(cog), pytest.raises(HTTPException) as exc:
        E.admin_start_email_change(employee_id=other.id, body=E.AdminEmailChangeIn(new_email="n@example.com"),
                                   db=db, caller=admin, current_user={"cognito_groups": ["admin"]})
    assert exc.value.status_code == 404


def test_an_admin_uses_my_account_for_their_own_email(db):
    admin = _admin(db)
    with pytest.raises(HTTPException) as exc:
        E.admin_start_email_change(employee_id=admin.id, body=E.AdminEmailChangeIn(new_email="n@example.com"),
                                   db=db, caller=admin, current_user={"cognito_groups": ["admin"]})
    assert exc.value.status_code == 400


# ── D4: the direct edit no longer diverges an active account ──────────────

def test_the_direct_edit_refuses_an_active_accounts_email(db):
    admin = _admin(db)
    target = _emp(db, status="active")
    with pytest.raises(HTTPException) as exc:
        E.update_employee(employee_id=target.id, employee=EmployeeUpdate(email="n@example.com"),
                          db=db, caller=admin, current_user={"cognito_groups": ["admin"]})
    assert exc.value.status_code == 409
    db.refresh(target)
    assert target.email == "db-copy@example.com"


# ── the super-admin endpoint is for platform accounts only ────────────────

def test_a_super_admin_cannot_change_a_tenant_employees_email(db):
    cog = _cog(groups=("walker",))
    with patch.object(PA, "_resolve_account", return_value=("the.person", cog.sub)), _aws(cog), \
            pytest.raises(HTTPException) as exc:
        PA.platform_start_email_change(body=PA.PlatformEmailChangeIn(account_id=uuid.UUID(cog.sub),
                                                                      new_email="n@example.com"),
                                       _super={"id": "owner"}, db=db)
    assert exc.value.status_code == 403


def test_a_super_admin_can_start_one_for_a_surveyor(db):
    cog = _cog(groups=("surveyor",))
    with patch.object(PA, "_resolve_account", return_value=("the.person", cog.sub)), _aws(cog) as m:
        PA.platform_start_email_change(body=PA.PlatformEmailChangeIn(account_id=uuid.UUID(cog.sub),
                                                                      new_email="n@example.com"),
                                       _super={"id": "owner"}, db=db)
    assert db.query(EmailChangeRequest).one().account_kind == "surveyor" and m["link"].called


@pytest.mark.parametrize("bad", [{"account_id": str(uuid.uuid4()), "new_email": "not-an-email"},
                                 {"account_id": str(uuid.uuid4()), "new_email": "a@b.co", "x": 1}])
def test_the_platform_request_is_typed(bad):
    with pytest.raises(ValidationError):
        PA.PlatformEmailChangeIn(**bad)


# ── the public confirm is rate-limited on the real client IP ──────────────

def test_the_confirm_route_is_rate_limited():
    from app.routers import auth_email_change
    assert hasattr(auth_email_change.confirm_email_change, "__wrapped__"), "missing @limiter.limit"


# ── platform self-service: the current address is Cognito's ──────────────

class _Redis:
    def __init__(self): self.d = {}
    def get(self, k): return self.d.get(k)
    def setex(self, k, ttl, v): self.d[k] = v
    def delete(self, *ks):
        for k in ks: self.d.pop(k, None)
    def incr(self, k): self.d[k] = int(self.d.get(k, 0)) + 1; return self.d[k]
    def expire(self, k, ttl): pass


def test_a_platform_account_changes_its_own_email_with_two_codes(db):
    from app.routers import platform_account as P
    cog = _cog(groups=("surveyor",), username="test.surveyor")
    caller = {"id": cog.sub, "username": "test.surveyor", "cognito_groups": ["surveyor"]}
    r, sent = _Redis(), []
    with _aws(cog) as m, patch.object(account_security, "_redis", return_value=r), \
            patch("app.core.security._get_redis", return_value=r), \
            patch("app.services.email.send_email_change_code", side_effect=lambda **kw: sent.append(kw)):
        out = P.request_email_change(payload=P._EmailChangeRequest(new_email="New@Example.com"), caller=caller)
        codes = {kw["which"]: kw for kw in sent}
        assert codes["current"]["to_email"] == "old@recovery.example"     # Cognito's address
        assert codes["new"]["to_email"] == "new@example.com"
        P.confirm_email_change(payload=P._EmailConfirmRequest(current_code=codes["current"]["code"],
                                                              new_code=codes["new"]["code"]),
                               caller=caller, db=db)
    assert out["current_masked"] != "old@recovery.example"
    attrs = {a["Name"]: a["Value"] for a in cog.admin_update_user_attributes.call_args.kwargs["UserAttributes"]}
    assert attrs["email"] == "new@example.com"
    assert m["old_notice"].call_args.kwargs["to_email"] == "old@recovery.example"


def test_no_verified_address_means_ask_a_super_admin(db):
    from app.routers import platform_account as P
    cog = _cog(verified="false", groups=("surveyor",))
    with _aws(cog), pytest.raises(HTTPException) as exc:
        P.request_email_change(payload=P._EmailChangeRequest(new_email="n@example.com"),
                               caller={"id": cog.sub, "username": "the.person", "cognito_groups": ["surveyor"]})
    assert exc.value.status_code == 409 and "super admin" in exc.value.detail


# ── the surveyor endpoint is super admin only, by surveyor ID ─────────────

def test_the_surveyor_change_is_keyed_on_the_surveyor_id(db):
    from datetime import date
    from app.models.survey_register import SurveyContributor
    from app.routers import survey_register as R
    cog = _cog(groups=("surveyor",), username="test.surveyor")
    c = SurveyContributor(id=uuid.uuid4(), cognito_sub=cog.sub, display_name="S", cognito_username="test.surveyor",
                          agreement_version="v1", agreement_signed_on=date(2026, 10, 1))
    db.add(c); db.commit()
    with _aws(cog) as m:
        R.start_surveyor_email_change(contributor_id=c.id, body=R.SurveyorEmailChangeIn(new_email="n@example.com"),
                                      owner={"id": "owner"}, db=db)
    assert m["link"].call_args.kwargs["to_email"] == "n@example.com"
    import inspect
    sig = inspect.signature(R.start_surveyor_email_change)
    assert "get_super_admin" in str(sig.parameters["owner"].default.dependency)
