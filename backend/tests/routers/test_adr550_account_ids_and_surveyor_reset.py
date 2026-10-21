"""Accounts are identified by ID; support can reset a surveyor's two-factor (ADR-550).

Owner, 2026-10-20: "pass the contributor id/surveyor id to the function to
identify the specific surveyor account that needs to be reset instead of a
name that is unreliable ... filter on that role and avoid any tenant
accounts", and give platform admins and support usable account identifiers.
"""
import inspect
import logging
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import deps
from app.models.audit_log import AuditLog
from app.models.employee import Employee
from app.models.platform_session import PlatformSessionStamp
from app.models.survey_register import SurveyContributor
from app.routers import employees as E
from app.routers import platform_alerts as PA
from app.routers import platform_account as P
from app.routers import survey_register as R
from app.services import mfa_containment
from app.services.audit import write_audit
from tests.conftest import SEED_COMPANY_ID
# The ADR-513 survey tables (autouse) and the support caller.
from tests.routers.test_adr513_survey_areas import SUPPORT, _tables, city  # noqa: F401

SUB = str(uuid.uuid4())
OK = mfa_containment.ContainmentResult(2, True, True, [])


def _contributor(db, sub=SUB, revoked=False, email="s@example.org"):
    c = SurveyContributor(id=uuid.uuid4(), cognito_sub=sub, display_name="Test Surveyor",
                          cognito_username="test.surveyor", email=email,
                          agreement_version="v1", agreement_signed_on=date(2026, 10, 13),
                          revoked_at=datetime.now(timezone.utc) if revoked else None)
    db.add(c); db.commit()
    return c


def _cognito(groups=("surveyor",), username="test.surveyor", found=True):
    c = MagicMock()
    c.list_users.return_value = {"Users": [{"Username": username}] if found else []}
    c.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": g} for g in groups]}
    return c


def _reset(db, c, cognito, reason="Lost their phone and cannot get codes"):
    with patch.object(R, "_cognito", return_value=cognito), \
         patch.object(R.mfa_containment, "contain", return_value=OK) as contain, \
         patch.object(R, "send_surveyor_mfa_reset_notice") as mail:
        out = R.reset_contributor_mfa(contributor_id=c.id, body=R.ResetMfaIn(reason=reason),
                                      staff=SUPPORT, db=db)
    return out, contain, mail


# ── D2: support resets a surveyor, by surveyor ID ──────────────────────────

def test_support_can_reset_a_surveyor_by_id(db):
    c = _contributor(db)
    cog = _cognito()
    out, contain, mail = _reset(db, c, cog)
    # Resolved by the SUB on the row, never by a name.
    assert cog.list_users.call_args.kwargs["Filter"] == f'sub = "{SUB}"'
    assert contain.call_args.kwargs == {"username": "test.surveyor", "pool_id": contain.call_args.kwargs["pool_id"],
                                        "region": contain.call_args.kwargs["region"], "clear_factor": True}
    assert out.contributor_id == c.id and out.surveyor_emailed is True
    assert db.get(PlatformSessionStamp, SUB) is not None, "sessions not ended inside the API"
    row = db.query(AuditLog).filter(AuditLog.action_type == "survey.contributor.mfa_reset").one()
    assert row.target_id == c.id                     # the surveyor ID: the row lands
    assert row.after_snapshot["actor_kind"] == "platform_support"
    assert "cannot get codes" in row.after_snapshot["reason"]
    assert mail.call_args.kwargs["to_email"] == "s@example.org"


def test_the_reason_may_say_codes_but_not_contain_one(db):
    """_CODE_WORDS would refuse the likeliest reason; a digit run is what leaks."""
    c = _contributor(db)
    _reset(db, c, _cognito(), reason="Lost their phone and cannot get codes")
    with pytest.raises(HTTPException) as exc:
        _reset(db, c, _cognito(), reason="Their current code is 482913, please reset")
    assert exc.value.status_code == 422


@pytest.mark.parametrize("groups,why", [
    (("surveyor", "platform_support"), "also staff"),
    (("surveyor", "super_admin"), "also super admin"),
    (("walker",), "not a surveyor"),
])
def test_support_can_never_reach_an_account_that_is_more_than_a_surveyor(db, groups, why):
    c = _contributor(db)
    with pytest.raises(HTTPException) as exc:
        _reset(db, c, _cognito(groups=groups))
    assert exc.value.status_code == 409, why


def test_a_tenant_employee_behind_the_same_sub_is_refused(db):
    c = _contributor(db)
    db.add(Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="Real Employee",
                    role="walker", is_active=True, cognito_sub=SUB))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        _reset(db, c, _cognito())
    assert exc.value.status_code == 409 and "company employee" in exc.value.detail


def test_a_revoked_or_unknown_contributor_is_refused(db):
    with pytest.raises(HTTPException) as exc:
        _reset(db, _contributor(db, revoked=True), _cognito())
    assert exc.value.status_code == 409
    ghost = SurveyContributor(id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        _reset(db, ghost, _cognito())
    assert exc.value.status_code == 404


def test_the_reset_is_open_to_support_not_to_surveyors():
    dep = inspect.signature(R.reset_contributor_mfa).parameters["staff"].default
    assert dep.dependency is deps.get_platform_staff
    with pytest.raises(HTTPException):
        deps.get_platform_staff(current_user={"id": "x", "cognito_groups": ["surveyor"]})


# ── D3: the super-admin reset takes an account ID ──────────────────────────

def test_the_request_takes_exactly_one_identifier():
    with pytest.raises(ValidationError):
        PA.MfaResetRequest()
    with pytest.raises(ValidationError):
        PA.MfaResetRequest(account_id=uuid.uuid4(), username="x")
    assert PA.MfaResetRequest(account_id=uuid.uuid4()).username is None


@pytest.mark.parametrize("by", ["account_id", "username"])
def test_a_platform_reset_is_audited_against_the_sub(db, by):
    """Prod had 0 platform.mfa_reset rows: the username was the target_id."""
    sub = str(uuid.uuid4())
    cog = MagicMock()
    cog.list_users.return_value = {"Users": [{"Username": "test.support"}]}
    cog.admin_get_user.return_value = {"Username": "test.support",
                                       "UserAttributes": [{"Name": "sub", "Value": sub}]}
    body = PA.MfaResetRequest(account_id=uuid.UUID(sub)) if by == "account_id" \
        else PA.MfaResetRequest(username="test.support")
    with patch.object(PA.boto3, "client", return_value=cog), \
         patch.object(PA.mfa_containment, "contain", return_value=OK):
        out = PA.platform_reset_mfa(body=body, _super={"id": "owner", "cognito_groups": ["super_admin"]}, db=db)
    assert out["account_id"] == sub
    row = db.query(AuditLog).filter(AuditLog.action_type == "platform.mfa_reset").one()
    assert str(row.target_id) == sub
    assert db.get(PlatformSessionStamp, sub) is not None


def test_staff_rows_carry_their_account_id():
    cog = MagicMock()
    cog.list_users_in_group.return_value = {"Users": [{"Username": "adon", "UserStatus": "CONFIRMED",
        "Attributes": [{"Name": "sub", "Value": SUB}, {"Name": "email", "Value": "a@x"}]}]}
    cog.list_users.return_value = {"Users": []}
    with patch.object(PA.boto3, "client", return_value=cog):
        rows = PA._list_platform_staff()   # ADR-551 wraps it to add reset requests (needs a db)
    assert rows and all(r.account_id == SUB for r in rows)


# ── D4: the tenant reset ends sessions here too ────────────────────────────

def test_the_tenant_reset_stamps_the_employee(db):
    admin = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="Admin", role="admin",
                     is_active=True, username="the.admin", cognito_sub=str(uuid.uuid4()))
    target = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="Walker", role="walker",
                      is_active=True, username="the.walker", cognito_sub=str(uuid.uuid4()))
    db.add_all([admin, target]); db.commit()
    with patch.object(E.mfa_containment, "contain", return_value=OK):
        E.reset_employee_mfa(employee_id=target.id, db=db, caller=admin, _={})
    db.refresh(target)
    assert target.tokens_valid_after is not None


# ── D5: a dropped audit row is no longer silent ────────────────────────────

def test_a_non_uuid_target_is_logged_not_swallowed(db, caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.audit"):
        write_audit(db, action_type="x.y", target_table="t", target_id="test.surveyor")
    assert "dropped x.y" in caplog.text


# ── D1: the IDs reach the account's own page ───────────────────────────────

def test_platform_me_returns_both_ids_for_a_surveyor(db):
    c = _contributor(db)
    cog = MagicMock()
    cog.admin_get_user.return_value = {"UserMFASettingList": None, "UserAttributes": []}
    with patch.object(P, "_cognito", return_value=cog):
        out = P.get_me(caller={"id": SUB, "username": "test.surveyor", "cognito_groups": ["surveyor"]}, db=db)
    assert out.account_id == SUB and out.surveyor_id == c.id


# ── Clients ────────────────────────────────────────────────────────────────

import pathlib
ROOT = pathlib.Path(__file__).resolve().parents[3]
WEB = ROOT / "frontend" / "src"


def test_support_resets_a_surveyor_by_id_on_the_activity_page():
    src = (WEB / "pages" / "superadmin" / "SurveyActivity.tsx").read_text()
    assert "`/survey/contributors/${resetting.id}/reset-mfa`" in src     # by surveyor ID
    assert "reason: resetReason.trim()" in src
    assert '<AccountId id={c.id} label="Surveyor ID" />' in src
    assert "c.id.toLowerCase().startsWith(q)" in src, "the list can't be searched by ID"


def test_staff_rows_reset_by_account_id_not_by_name():
    src = (WEB / "pages" / "superadmin" / "PlatformStaff.tsx").read_text()
    assert "doReset({ account_id: r.account_id }" in src
    assert "must also be removed from its group temporarily" not in src, (
        "stale since ADR-466/548: a reset restores the enrolment window")


@pytest.mark.parametrize("path", [
    WEB / "pages" / "superadmin" / "Surveyors.tsx",
    WEB / "pages" / "superadmin" / "PlatformAccount.tsx",
    ROOT / "mobile" / "src" / "screens" / "Survey" / "PlatformAccountScreen.tsx",
])
def test_the_ids_are_shown(path):
    src = path.read_text()
    assert "surveyor_id" in src or "Surveyor ID" in src
