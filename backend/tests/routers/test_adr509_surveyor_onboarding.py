"""ADR-509 — platform support can onboard surveyors, and nothing else that writes.

Cognito is a fake: the properties under test are what the endpoint asks Cognito
to do (and refuses to), not boto3.
"""
import inspect
import uuid
from datetime import date, timedelta

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import deps
from app.models.audit_log import AuditLog
from app.models.survey_register import SurveyContributor
from app.routers import survey_register as R
from tests.conftest import SEED_COMPANY_ID, make_employee, sqlite_mirror_with_defaults

SUPPORT = {"id": "support-sub-0001", "email": "support@asheflow.com", "cognito_groups": ["platform_support"]}
OWNER = {"id": "owner-sub-0001", "email": "owner@asheflow.com", "cognito_groups": ["super_admin"]}


class FakeCognito:
    def __init__(self, existing_emails=()):
        self.existing = set(existing_emails)
        self.calls = []

    def list_users(self, UserPoolId, Filter, Limit):
        email = Filter.split('"')[1]
        return {"Users": [{"Username": "someone"}] if email in self.existing else []}

    def admin_get_user(self, UserPoolId, Username):
        raise ClientError({"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")

    def admin_create_user(self, **kw):
        self.calls.append(("create", kw["Username"]))
        return {"User": {"Attributes": [{"Name": "sub", "Value": "new-sub-" + kw["Username"]}]}}

    def admin_add_user_to_group(self, **kw):
        self.calls.append(("add_group", kw["Username"], kw["GroupName"]))

    def admin_remove_user_from_group(self, **kw):
        self.calls.append(("remove_group", kw["Username"], kw["GroupName"]))

    def admin_delete_user(self, **kw):
        self.calls.append(("delete", kw["Username"]))


@pytest.fixture(autouse=True)
def _tables(db):
    for m in (SurveyContributor, AuditLog):
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)


@pytest.fixture
def cognito(monkeypatch):
    fake = FakeCognito()
    monkeypatch.setattr(R, "_cognito", lambda: fake)
    import app.routers.platform_alerts as PA
    monkeypatch.setattr(PA.boto3, "client", lambda *a, **k: fake, raising=False)
    sent = []
    monkeypatch.setattr(R, "send_credentials_email", lambda **kw: sent.append(kw))
    fake.sent = sent
    return fake


def _invite(db, caller=SUPPORT, **over):
    body = dict(name="Pat Lee", email="pat@example.com", agreement_version="v1",
                agreement_signed_on=date(2026, 10, 14), confirm_agreement_signed=True)
    body.update(over)
    return R.invite_contributor(R.ContributorInviteIn(**body), staff=caller, db=db)


class TestInvite:
    def test_support_creates_grants_and_admits_in_one_step(self, db, cognito):
        out = _invite(db)
        assert ("create", "pat.lee") in cognito.calls
        assert ("add_group", "pat.lee", "surveyor") in cognito.calls
        c = db.query(SurveyContributor).one()
        assert (c.cognito_sub, c.cognito_username, c.email, c.agreement_version) == (
            "new-sub-pat.lee", "pat.lee", "pat@example.com", "v1")
        assert out.email_delivered and out.temp_password is None
        assert cognito.sent[0]["username"] == "pat.lee"

    def test_the_audit_names_support_as_support_and_holds_no_email(self, db, cognito):
        _invite(db)
        a = db.query(AuditLog).filter_by(action_type="survey.contributor.invite").one()
        assert a.after_snapshot["actor_kind"] == "platform_support"
        assert "pat@example.com" not in str(a.after_snapshot)

    def test_an_existing_account_is_never_touched(self, db, cognito):
        cognito.existing.add("pat@example.com")
        with pytest.raises(HTTPException) as e:
            _invite(db)
        assert e.value.status_code == 409
        assert not [c for c in cognito.calls if c[0] in ("create", "add_group")]

    def test_nobody_admits_themselves(self, db, cognito):
        with pytest.raises(HTTPException) as e:
            _invite(db, email="Support@AsheFlow.com")
        assert e.value.status_code == 403 and cognito.calls == []

    def test_an_employee_email_is_refused(self, db, cognito, monkeypatch):
        monkeypatch.setattr(R.settings, "survey_excluded_company_id", str(SEED_COMPANY_ID))
        emp = make_employee(db, role="walker")
        emp.email = "Pat@Example.com"
        db.commit()
        with pytest.raises(HTTPException) as e:
            _invite(db)
        assert e.value.status_code == 403 and cognito.calls == []

    def test_no_half_made_account_when_the_row_fails(self, db, cognito, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("db down")
        monkeypatch.setattr(R, "write_audit", boom)
        with pytest.raises(HTTPException) as e:
            _invite(db)
        assert e.value.status_code == 500
        assert ("delete", "pat.lee") in cognito.calls
        assert db.query(SurveyContributor).count() == 0

    def test_a_failed_email_returns_the_password_once(self, db, cognito, monkeypatch):
        def fail(**kw):
            raise RuntimeError("ses down")
        monkeypatch.setattr(R, "send_credentials_email", fail)
        out = _invite(db)
        assert not out.email_delivered and out.temp_password and len(out.temp_password) == 9

    @pytest.mark.parametrize("over", [
        {"confirm_agreement_signed": False},
        {"agreement_signed_on": date.today() + timedelta(days=1)},
        {"email": "not-an-email"},
        {"name": ""},
        {"role": "super_admin"},
    ])
    def test_malformed_invites_are_refused(self, over):
        body = {**dict(name="Pat Lee", email="pat@example.com", agreement_version="v1",
                       agreement_signed_on=date(2026, 10, 14), confirm_agreement_signed=True), **over}
        with pytest.raises(ValidationError):
            R.ContributorInviteIn(**body)


class TestRevoke:
    def test_support_revokes_and_the_group_goes(self, db, cognito):
        c = _invite(db).contributor
        out = R.revoke_contributor(c.id, staff=SUPPORT, db=db)
        assert out.revoked_at is not None
        assert ("remove_group", "pat.lee", "surveyor") in cognito.calls
        with pytest.raises(HTTPException) as e:
            R.revoke_contributor(c.id, staff=SUPPORT, db=db)
        assert e.value.status_code == 409


class TestTheBoundary:
    def _dep(self, fn, name):
        return inspect.signature(fn).parameters[name].default.dependency

    def test_support_reaches_invite_list_and_revoke(self):
        assert self._dep(R.invite_contributor, "staff") is deps.get_platform_staff
        assert self._dep(R.revoke_contributor, "staff") is deps.get_platform_staff
        assert self._dep(R.list_contributors, "_") is deps.get_platform_staff

    def test_admitting_an_existing_account_stays_super_admin_only(self):
        assert self._dep(R.admit_contributor, "super_admin") is deps.get_super_admin

    def test_support_still_cannot_write_or_read_the_register(self, db):
        with pytest.raises(HTTPException) as e:
            R.get_writer(SUPPORT, db)
        assert e.value.status_code == 403



def test_the_create_suppresses_cognitos_email_and_sends_the_branded_one():
    """ADR-444: Cognito's stock email carries a live credential in plain text.
    The invite must suppress it, pass its own password, and send the branded mail."""
    src = inspect.getsource(R.invite_contributor)
    assert 'MessageAction="SUPPRESS"' in src
    assert "TemporaryPassword=temp_password" in src
    assert "send_credentials_email(" in src
