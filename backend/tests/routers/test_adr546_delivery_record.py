"""Every email leaves a delivery record (ADR-546).

2026-10-19: a survey-release email left SES (1 attempt, 0 bounces) and never
arrived, and nothing recorded what happened after SES accepted it. Senders now
log the SES MessageId; the SNS handler logs Delivery / DeliveryDelay / Reject
against it, by domain, never by address.
"""
import inspect
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.routers import sns_events as SE
from app.services import email as EM

ADDR = "someone+tag@gmail.com"


def _event(kind, **extra):
    return {"eventType": kind, "mail": {"messageId": "0100-abc", "destination": [ADDR]}, **extra}


class TestTheHandlerLogsDeliveryAgainstTheMessageId:
    def test_delivery_logs_id_domain_and_smtp_not_the_address(self, caplog):
        caplog.set_level(logging.INFO, logger=SE.logger.name)
        assert SE._log_delivery(_event("Delivery", delivery={
            "timestamp": "2026-10-19T11:52:07Z", "processingTimeMillis": 812,
            "smtpResponse": "250 2.0.0 OK 1729338727 gsmtp"}))
        text = caplog.text
        assert "MessageId=0100-abc" in text and "gmail.com" in text and "250 2.0.0 OK" in text
        assert ADDR not in text and "someone" not in text   # Dimension 7

    def test_delay_and_reject_are_logged(self, caplog):
        caplog.set_level(logging.INFO, logger=SE.logger.name)
        assert SE._log_delivery(_event("DeliveryDelay", deliveryDelay={"delayType": "TransientCommunicationFailure"}))
        assert SE._log_delivery(_event("Reject", reject={"reason": "Bad content"}))
        assert "TransientCommunicationFailure" in caplog.text and "Bad content" in caplog.text

    def test_bounces_and_complaints_still_go_to_the_bounce_path(self):
        assert SE._log_delivery(_event("Bounce")) is False
        assert SE._log_delivery(_event("Complaint")) is False

    def test_the_rate_limit_covers_an_event_per_email(self):
        src = inspect.getsource(SE)
        assert '@limiter.limit("600/minute")' in src


class TestEverySendLogsItsMessageId:
    def test_every_send_site_is_followed_by_a_messageid_log(self):
        """Walks the module: each send_email call has a _log_ses_sent after it."""
        src = inspect.getsource(EM)
        sends = src.count("resp = client.send_email(")
        logs = src.count("_log_ses_sent(") - 1   # minus the definition
        assert sends == 7 and logs == sends, (sends, logs)

    def test_a_security_email_logs_the_id_and_account_not_the_address(self, caplog):
        caplog.set_level(logging.INFO, logger=EM.logger.name)
        client = MagicMock()
        client.send_email.return_value = {"MessageId": "0100-xyz"}
        with patch.object(EM.boto3, "client", return_value=client):
            EM._send_security_email(to_email=ADDR, subject="S", text="t", html_body="h", account_ref="acct-1")
        assert "MessageId=0100-xyz" in caplog.text and "account=acct-1" in caplog.text
        assert ADDR not in caplog.text


# ── D4: the release page says "emailed" only when it was ───────────────────

from app.routers import survey_register as R  # noqa: E402
from tests.routers.test_adr513_survey_areas import (  # noqa: E402,F401
    _area, _claim_and_walk, _tables, city, SUPPORT,
)
from tests.routers.test_adr545_survey_support import _contributor  # noqa: E402


class TestReleaseReportsWhatHappened:
    def _held(self, db):
        c = _contributor(db)
        claim, _ = _claim_and_walk(db, R.Writer(sub=c.cognito_sub, owner=False), _area(db))
        return claim

    def test_sent(self, db):
        claim = self._held(db)
        with patch.object(R, "send_claim_released_notice"):
            out = R.staff_release_claim(claim.id, R.StaffReleaseIn(reason="Idle two days, freeing"), staff=SUPPORT, db=db)
        assert out.holder_emailed is True

    def test_failed_send_is_not_reported_as_emailed(self, db):
        claim = self._held(db)
        with patch.object(R, "send_claim_released_notice", side_effect=RuntimeError("ses down")):
            out = R.staff_release_claim(claim.id, R.StaffReleaseIn(reason="Idle two days, freeing"), staff=SUPPORT, db=db)
        assert out.holder_emailed is False

    def test_the_notice_names_the_block_once(self, db):
        claim = self._held(db)
        with patch.object(R, "send_claim_released_notice") as send:
            R.staff_release_claim(claim.id, R.StaffReleaseIn(reason="Idle two days, freeing"), staff=SUPPORT, db=db)
        block = send.call_args.kwargs["block"]
        assert block.count("W 32 ST") <= 1, block
