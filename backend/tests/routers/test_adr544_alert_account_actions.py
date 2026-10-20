"""From an account alert, a super admin can email a reminder or sign the account out (ADR-544).

Owner, 2026-10-19: "We should be able to send the account a message from here."
Real handlers on sqlite; Cognito, SES and containment stubbed at their real names.
"""
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.models.audit_log import AuditLog
from app.models.platform_alert import PlatformAlert
from app.routers import platform_alerts as PA
from app.services.mfa_containment import ContainmentResult
from tests.conftest import SEED_COMPANY_ID, make_employee

SUPER = {"id": "sub-adon", "email": "adon@example.com", "cognito_groups": ["super_admin"], "username": "adon"}


@pytest.fixture(autouse=True)
def _platform_alerts_table(db):
    PlatformAlert.__table__.create(bind=db.get_bind(), checkfirst=True)
    db.query(PlatformAlert).delete(); db.commit()   # the table outlives the db fixture's cleanup
    yield
    db.rollback(); db.query(PlatformAlert).delete(); db.commit()


def _alert(db, *, ref="pass.check", kind="employee", type_="mfa.privileged_unprotected", company=SEED_COMPANY_ID):
    a = PlatformAlert(alert_type=type_, company_id=company, message="m", severity="critical",
                      subject_kind=kind if ref else None, subject_ref=ref, subject_role="admin" if ref else None)
    db.add(a); db.commit(); db.refresh(a)
    return a


def _cognito(email="pass@example.com", verified="true"):
    c = MagicMock()
    c.admin_get_user.return_value = {"UserAttributes": [
        {"Name": "email", "Value": email}, {"Name": "email_verified", "Value": verified}]}
    return c


class TestRemind:
    def test_it_emails_the_verified_address_and_records_who(self, db):
        a = _alert(db)
        with patch.object(PA.boto3, "client", return_value=_cognito()), \
             patch("app.services.email.send_mfa_setup_reminder") as send:
            out = PA.remind_alert_account(alert_id=a.id, _super=SUPER, db=db)
        assert send.call_args.kwargs["to_email"] == "pass@example.com"
        assert out.reminder_count == 1 and out.reminded_by_email == "adon@example.com"
        [log] = db.query(AuditLog).filter(AuditLog.action_type == "platform_alert.account_reminded").all()
        assert log.after_snapshot["reminder_count"] == 1

    def test_a_second_reminder_within_a_day_is_refused(self, db):
        a = _alert(db)
        a.reminded_at = datetime.now(timezone.utc) - timedelta(hours=23); db.commit()
        with patch.object(PA.boto3, "client", return_value=_cognito()), \
             patch("app.services.email.send_mfa_setup_reminder") as send:
            with pytest.raises(HTTPException) as exc:
                PA.remind_alert_account(alert_id=a.id, _super=SUPER, db=db)
        assert exc.value.status_code == 429
        send.assert_not_called()

    def test_after_a_day_it_can_be_sent_again(self, db):
        a = _alert(db)
        a.reminded_at = datetime.now(timezone.utc) - timedelta(hours=25); a.reminder_count = 1; db.commit()
        with patch.object(PA.boto3, "client", return_value=_cognito()), \
             patch("app.services.email.send_mfa_setup_reminder"):
            out = PA.remind_alert_account(alert_id=a.id, _super=SUPER, db=db)
        assert out.reminder_count == 2

    def test_no_verified_email_points_to_sign_out(self, db):
        a = _alert(db)
        with patch.object(PA.boto3, "client", return_value=_cognito(verified="false")), \
             patch("app.services.email.send_mfa_setup_reminder") as send:
            with pytest.raises(HTTPException) as exc:
                PA.remind_alert_account(alert_id=a.id, _super=SUPER, db=db)
        assert exc.value.status_code == 409 and "Sign them out" in exc.value.detail
        send.assert_not_called()

    def test_an_infrastructure_alert_has_no_one_to_remind(self, db):
        a = _alert(db, ref=None, type_="email_delivery_failed")
        with pytest.raises(HTTPException) as exc:
            PA.remind_alert_account(alert_id=a.id, _super=SUPER, db=db)
        assert exc.value.status_code == 400

    def test_the_reminder_links_to_the_setup_page(self):
        from app.services import email as EM
        sent = {}
        with patch.object(EM, "_send_security_email", side_effect=lambda **kw: sent.update(kw)):
            EM.send_mfa_setup_reminder(to_email="x@example.com", account_ref="x")
        assert "/mfa-setup" in sent["text"] and "/mfa-setup" in sent["html_body"]
        assert "logo-light@2x.png" in sent["html_body"]   # the reviewed security layout


class TestSignOut:
    def _contain(self, signed_out=True):
        return ContainmentResult(devices_forgotten=2, signed_out=signed_out, factor_cleared=False, errors=[])

    def test_it_contains_without_clearing_the_factor_and_stamps_the_employee(self, db):
        e = make_employee(db, role="admin"); e.username = "pass.check"; db.commit()
        a = _alert(db)
        with patch.object(PA.mfa_containment, "contain", return_value=self._contain()) as contain:
            out = PA.sign_out_alert_account(alert_id=a.id, _super=SUPER, db=db)
        assert contain.call_args.kwargs["clear_factor"] is False
        assert contain.call_args.kwargs["username"] == "pass.check"
        db.refresh(e)
        assert e.tokens_valid_after is not None
        assert out.sessions_ended_by_email == "adon@example.com"
        [log] = db.query(AuditLog).filter(AuditLog.action_type == "platform_alert.account_signed_out").all()
        assert log.after_snapshot["devices_forgotten"] == 2

    def test_an_employee_in_another_company_is_not_stamped(self, db):
        """Dimension 1: the lookup is scoped to the alert's company."""
        import uuid
        e = make_employee(db, role="admin"); e.username = "pass.check"; db.commit()
        a = _alert(db, company=uuid.uuid4())
        with patch.object(PA.mfa_containment, "contain", return_value=self._contain()):
            PA.sign_out_alert_account(alert_id=a.id, _super=SUPER, db=db)
        db.refresh(e)
        assert e.tokens_valid_after is None

    def test_a_failed_sign_out_is_reported_but_still_audited(self, db):
        a = _alert(db, kind="platform", company=None, ref="adon")
        with patch.object(PA.mfa_containment, "contain", return_value=self._contain(signed_out=False)):
            with pytest.raises(HTTPException) as exc:
                PA.sign_out_alert_account(alert_id=a.id, _super=SUPER, db=db)
        assert exc.value.status_code == 502
        db.refresh(a)
        assert a.sessions_ended_at is None   # the card must not claim what didn't happen
        assert db.query(AuditLog).filter(AuditLog.action_type == "platform_alert.account_signed_out").count() == 1


def test_both_actions_are_super_admin_only():
    """ADR-343: platform support never acts on an account."""
    for fn in (PA.remind_alert_account, PA.sign_out_alert_account):
        dep = inspect.signature(fn).parameters["_super"].default.dependency
        assert dep is PA.get_super_admin, fn.__name__
