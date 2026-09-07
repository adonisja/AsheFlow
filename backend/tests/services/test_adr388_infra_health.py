"""The containment chain is watched (ADR-388).

WHY THIS EXISTS
ADR-387's containment runs through trail -> EventBridge -> Lambda -> SNS -> human.
Break any link and unenrolments stop being contained SILENTLY. The account's
previous trail proved this is not hypothetical: `IsLogging: true` for twelve
months while writing to a deleted bucket.

These tests pin the cases that CANNOT be fault-injected against live AWS without
breaking production infrastructure -- a stale delivery time, a delivery error, a
pending-only SNS subscription.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.tasks import security_infra_health as h


NOW = datetime.now(timezone.utc)


def _trail_status(**over):
    base = {"IsLogging": True, "LatestDeliveryError": None,
            "LatestDeliveryTime": NOW - timedelta(minutes=5)}
    base.update(over)
    return base


class TestTheTrailCheckCatchesTheTruEvalFailure:
    def test_a_healthy_trail_is_clean(self):
        c = MagicMock(); c.get_trail_status.return_value = _trail_status()
        with patch("boto3.client", return_value=c):
            assert h._check_trail("us-east-2") == []

    def test_is_logging_true_is_not_enough(self):
        """THE regression. TruEval's trail reported IsLogging:true for a year
        while writing to a deleted bucket. Only LatestDeliveryError showed it."""
        c = MagicMock()
        c.get_trail_status.return_value = _trail_status(
            IsLogging=True, LatestDeliveryError="NoSuchBucket")
        with patch("boto3.client", return_value=c):
            problems = h._check_trail("us-east-2")
        assert any("NoSuchBucket" in p for p in problems), problems

    def test_a_stale_delivery_is_caught(self):
        """The other half of the same failure: no error, but nothing delivered
        for a year."""
        c = MagicMock()
        c.get_trail_status.return_value = _trail_status(
            LatestDeliveryTime=NOW - timedelta(days=365))
        with patch("boto3.client", return_value=c):
            problems = h._check_trail("us-east-2")
        assert any("last delivered" in p for p in problems), problems

    def test_a_trail_that_never_delivered_is_caught(self):
        c = MagicMock()
        c.get_trail_status.return_value = _trail_status(LatestDeliveryTime=None)
        with patch("boto3.client", return_value=c):
            problems = h._check_trail("us-east-2")
        assert any("never delivered" in p for p in problems), problems

    def test_not_logging_is_caught(self):
        c = MagicMock()
        c.get_trail_status.return_value = _trail_status(IsLogging=False)
        with patch("boto3.client", return_value=c):
            assert any("not logging" in p for p in h._check_trail("us-east-2"))

    def test_a_naive_timestamp_does_not_crash(self):
        """boto3 usually returns tz-aware datetimes, but a naive one would raise
        on subtraction and take the whole health check down with it."""
        c = MagicMock()
        c.get_trail_status.return_value = _trail_status(
            LatestDeliveryTime=datetime.now(timezone.utc).replace(tzinfo=None))
        with patch("boto3.client", return_value=c):
            h._check_trail("us-east-2")  # must not raise


class TestTheTopicCheckCatchesAVoidPublish:
    def _sns(self, subs):
        c = MagicMock()
        pag = MagicMock()
        pag.paginate.return_value = [{"Topics": [
            {"TopicArn": "arn:aws:sns:us-east-2:1:AsheFlow-SecurityAlerts"}]}]
        c.get_paginator.return_value = pag
        c.list_subscriptions_by_topic.return_value = {"Subscriptions": subs}
        return c

    def test_a_confirmed_subscriber_is_clean(self):
        c = self._sns([{"SubscriptionArn": "arn:aws:sns:us-east-2:1:t:sub-1"}])
        with patch("boto3.client", return_value=c):
            assert h._check_topic("us-east-2") == []

    def test_a_pending_subscription_delivers_nothing(self):
        """PendingConfirmation is a real subscription row that delivers NOTHING.
        Publishing still 'succeeds' — the same green-while-blind shape."""
        c = self._sns([{"SubscriptionArn": "PendingConfirmation"}])
        with patch("boto3.client", return_value=c):
            problems = h._check_topic("us-east-2")
        assert any("no confirmed subscribers" in p for p in problems), problems

    def test_no_subscriptions_at_all_is_caught(self):
        c = self._sns([])
        with patch("boto3.client", return_value=c):
            assert any("no confirmed subscribers" in p
                       for p in h._check_topic("us-east-2"))


class TestItRaisesOneAlertForSuperAdmins:
    def test_a_healthy_chain_raises_nothing(self):
        with patch.object(h, "_check_trail", return_value=[]), \
             patch.object(h, "_check_rule_and_lambda", return_value=[]), \
             patch.object(h, "_check_topic", return_value=[]), \
             patch.object(h, "raise_platform_alert") as alert:
            r = h.check_security_infra()
        assert r["healthy"] is True
        alert.assert_not_called()

    def test_problems_become_one_platform_wide_critical_alert(self):
        """company_id=None: a broken trail is not one tenant's problem, and
        raise_platform_alert dedups platform-wide alerts against each other."""
        with patch.object(h, "_check_trail", return_value=["trail broken"]), \
             patch.object(h, "_check_rule_and_lambda", return_value=["rule gone"]), \
             patch.object(h, "_check_topic", return_value=[]), \
             patch.object(h, "SessionLocal"), \
             patch.object(h, "raise_platform_alert") as alert:
            r = h.check_security_infra()
        assert r["healthy"] is False
        assert len(r["problems"]) == 2
        kwargs = alert.call_args.kwargs
        assert kwargs["severity"] == "critical"
        assert kwargs["company_id"] is None
        assert "trail broken" in kwargs["message"]
        assert "rule gone" in kwargs["message"]

    def test_an_aws_failure_is_a_problem_not_a_crash(self):
        """The check runs unattended. An exception here means no alert AND no
        health signal, which is worse than a false positive."""
        c = MagicMock()
        c.get_trail_status.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException"}}, "GetTrailStatus")
        with patch("boto3.client", return_value=c):
            problems = h._check_trail("us-east-2")
        assert any("AccessDenied" in p for p in problems)


class TestThePermissionProbe:
    """ADR-390. Every other check verifies infrastructure EXISTS; this one
    verifies we are still ALLOWED to use it.

    That gap was real: admin_set_user_mfa_preference shipped in application code
    without the matching IAM grant (ADR-389), and nothing found out until a human
    clicked Reset and got a 502. CI cannot catch it -- every mock returns success
    for a call the production role cannot make.
    """

    def _client(self, **codes):
        """A client whose three probed calls raise the given error codes.
        UserNotFoundException is the PERMITTED case: IAM is evaluated before the
        user lookup, so a bogus username proves permission without mutating."""
        c = MagicMock()
        for meth, code in codes.items():
            getattr(c, meth).side_effect = ClientError(
                {"Error": {"Code": code, "Message": "x"}}, "Op")
        return c

    ALL_OK = dict(
        admin_set_user_mfa_preference="UserNotFoundException",
        admin_user_global_sign_out="UserNotFoundException",
        admin_list_devices="UserNotFoundException",
    )

    def test_all_permitted_is_clean(self):
        with patch("boto3.client", return_value=self._client(**self.ALL_OK)):
            assert h._check_containment_permissions("r", "p") == []

    def test_the_adr389_regression_is_caught(self):
        """THE case: admin_set_user_mfa_preference not granted.

        Asserts the ADR-389 wording, not merely that SOME problem came back. A
        denial and an incidental API error are different operational situations,
        and the generic `else` branch would satisfy a looser assertion -- which
        it did: dropping the AccessDenied branch entirely once passed this test.
        """
        codes = dict(self.ALL_OK, admin_set_user_mfa_preference="AccessDeniedException")
        with patch("boto3.client", return_value=self._client(**codes)):
            problems = h._check_containment_permissions("r", "p")
        assert any("AdminSetUserMFAPreference" in p
                   and "containment cannot run" in p
                   for p in problems), problems

    def test_a_denial_is_distinguished_from_an_incidental_error(self):
        """A revoked permission needs a human NOW; a transient InternalError does
        not. Reporting both identically loses that."""
        denied = dict(self.ALL_OK, admin_list_devices="AccessDeniedException")
        other = dict(self.ALL_OK, admin_list_devices="InternalErrorException")
        with patch("boto3.client", return_value=self._client(**denied)):
            d = h._check_containment_permissions("r", "p")
        with patch("boto3.client", return_value=self._client(**other)):
            o = h._check_containment_permissions("r", "p")
        assert any("containment cannot run" in p for p in d), d
        assert not any("containment cannot run" in p for p in o), o

    def test_a_revoked_sign_out_is_caught(self):
        """Sign-out is the half that ends a live attacker session."""
        codes = dict(self.ALL_OK, admin_user_global_sign_out="AccessDeniedException")
        with patch("boto3.client", return_value=self._client(**codes)):
            assert any("AdminUserGlobalSignOut" in p
                       for p in h._check_containment_permissions("r", "p"))

    def test_a_revoked_device_list_is_caught(self):
        codes = dict(self.ALL_OK, admin_list_devices="NotAuthorizedException")
        with patch("boto3.client", return_value=self._client(**codes)):
            assert any("AdminListDevices" in p
                       for p in h._check_containment_permissions("r", "p"))

    def test_the_probe_never_mutates_a_real_account(self):
        """The username must be one no real account can hold. If this probe ever
        targeted a real user it would sign them out once an hour."""
        c = self._client(**self.ALL_OK)
        with patch("boto3.client", return_value=c):
            h._check_containment_permissions("r", "p")
        for call in c.admin_set_user_mfa_preference.call_args_list:
            assert "does-not-exist" in call.kwargs["Username"]
        for call in c.admin_user_global_sign_out.call_args_list:
            assert "does-not-exist" in call.kwargs["Username"]

    def test_a_probe_user_that_exists_is_itself_a_problem(self):
        """If the sentinel resolves, the probe is mutating something and must
        say so rather than reporting healthy."""
        c = MagicMock()  # no side effects: every call "succeeds"
        with patch("boto3.client", return_value=c):
            problems = h._check_containment_permissions("r", "p")
        assert len(problems) == 3
        assert all("unexpectedly exists" in p for p in problems), problems
