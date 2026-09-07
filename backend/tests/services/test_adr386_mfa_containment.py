"""Containing an account whose MFA factor was removed (ADR-386).

Unenrolment cannot be PREVENTED -- Amplify calls Cognito directly with a scope
that cannot be stripped (ADR-377 D1) -- so the control is detect-and-contain.
These tests pin the contain half.

The service is deliberately shared between the admin reset endpoint and the
EventBridge responder (ADR-387). Two implementations would drift, and the one
that drifts is the one nobody exercises by hand.
"""
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.services import mfa_containment


def _client(devices=None, signout_error=None, forget_error=None,
            remaining_factors=None):
    c = MagicMock()
    c.admin_list_devices.return_value = {
        "Devices": [{"DeviceKey": k} for k in (devices or [])]
    }
    # ADR-392: contain(clear_factor=True) reads the account back to confirm the
    # clear actually took. Default: nothing left, i.e. it worked.
    c.admin_get_user.return_value = {
        "UserMFASettingList": list(remaining_factors or [])
    }
    if signout_error:
        c.admin_user_global_sign_out.side_effect = signout_error
    if forget_error:
        c.admin_forget_device.side_effect = forget_error
    return c


def _err(code="InternalErrorException"):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")


class TestBothHalvesRun:
    def test_it_signs_out_and_forgets_every_device(self):
        c = _client(devices=["d1", "d2", "d3"])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2")
        assert r.signed_out is True
        assert r.devices_forgotten == 3
        assert r.fully_contained is True

    def test_sign_out_happens_before_devices_are_forgotten(self):
        """A compromised session stays live while devices are forgotten one API
        call at a time. Ending it first shrinks that window to a single call."""
        order = []
        c = MagicMock()
        c.admin_user_global_sign_out.side_effect = lambda **k: order.append("signout")
        c.admin_list_devices.side_effect = lambda **k: (
            order.append("list") or {"Devices": [{"DeviceKey": "d1"}]}
        )
        c.admin_forget_device.side_effect = lambda **k: order.append("forget")
        with patch("boto3.client", return_value=c):
            mfa_containment.contain("u", "pool", "us-east-2")
        assert order[0] == "signout", f"sign-out must be first, got {order}"

    def test_an_account_with_no_devices_is_still_signed_out(self):
        """Forgetting nothing is not the same as containing nothing. The session
        is the part that matters most."""
        c = _client(devices=[])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2")
        assert r.signed_out is True
        assert r.devices_forgotten == 0
        assert r.fully_contained is True


class TestPartialFailureIsReportedNotSwallowed:
    def test_a_failed_sign_out_is_not_fully_contained(self):
        c = _client(devices=["d1"], signout_error=_err())
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2")
        assert r.signed_out is False
        assert r.fully_contained is False
        assert r.errors

    def test_devices_are_still_forgotten_when_sign_out_fails(self):
        """Half the containment beats none: the remembered device is what lets
        the actor back in without a challenge."""
        c = _client(devices=["d1", "d2"], signout_error=_err())
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2")
        assert r.devices_forgotten == 2

    def test_one_bad_device_does_not_abort_the_rest(self):
        c = MagicMock()
        c.admin_list_devices.return_value = {
            "Devices": [{"DeviceKey": "d1"}, {"DeviceKey": "d2"}]
        }
        c.admin_forget_device.side_effect = [_err(), None]
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2")
        assert r.devices_forgotten == 1
        assert r.fully_contained is False

    def test_it_never_raises(self):
        """Runs on an admin endpoint that must not 500 and a Lambda responding to
        a security event. A partial containment reported honestly beats an
        exception that contains nothing."""
        c = _client(devices=["d1"], signout_error=_err(), forget_error=_err())
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2")
        assert r.fully_contained is False


class TestNoPiiInTheResult:
    def test_errors_carry_types_not_messages(self):
        """An exception message can carry a username or an IP. The audit detail
        and the alert both persist this list (ADR-115 D7)."""
        c = _client(devices=["d1"], signout_error=_err("NotAuthorizedException"))
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("sensitive.user", "pool", "us-east-2")
        joined = " ".join(r.errors)
        assert "sensitive.user" not in joined
        assert "ClientError" in joined


class TestClearFactorSeparatesTheTwoCallers:
    """ADR-389. The two callers want OPPOSITE things and conflating them caused
    a real lockout on `test.user`.

      containment (ADR-387)  the factor is the victim's PROTECTION. An attacker
                             removed it; the account should end up challenged,
                             not unlocked.
      admin reset (ADR-389)  the user LOST their authenticator. Leaving the
                             factor in place leaves them exactly as locked out.
    """

    def test_containment_does_not_clear_the_factor_by_default(self):
        """The security-critical default. If this flips, the EventBridge
        responder starts UNLOCKING accounts an attacker just tampered with."""
        c = _client(devices=["d1"])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2")
        c.admin_set_user_mfa_preference.assert_not_called()
        assert r.factor_cleared is False

    def test_the_admin_reset_path_clears_it(self):
        c = _client(devices=["d1"])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        c.admin_set_user_mfa_preference.assert_called_once()
        kwargs = c.admin_set_user_mfa_preference.call_args.kwargs
        assert kwargs["SoftwareTokenMfaSettings"]["Enabled"] is False
        assert r.factor_cleared is True

    def test_it_clears_EVERY_factor_type_not_just_totp(self):
        """ADR-391. Clearing only the software token left walker.test on
        EMAIL_OTP -- still challenged, after a reset that reported success.

        Cognito treats each factor as an independent preference, so a reset that
        names one is not a reset."""
        c = _client(devices=[])
        with patch("boto3.client", return_value=c):
            mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        kwargs = c.admin_set_user_mfa_preference.call_args.kwargs
        for key in ("SoftwareTokenMfaSettings", "EmailMfaSettings", "SMSMfaSettings"):
            assert key in kwargs, f"{key} not cleared -- the user stays challenged"
            assert kwargs[key]["Enabled"] is False
            assert kwargs[key]["PreferredMfa"] is False

    def test_it_does_not_touch_webauthn(self):
        """A passkey is bound to hardware the user still holds, so it is not
        what strands them. Clearing it would destroy a working credential."""
        c = _client(devices=[])
        with patch("boto3.client", return_value=c):
            mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        assert "WebAuthnMfaSettings" not in \
            c.admin_set_user_mfa_preference.call_args.kwargs

    def test_the_factor_is_cleared_before_sign_out(self):
        """A session issued after the preference change would otherwise survive
        with the old state."""
        order = []
        c = MagicMock()
        c.admin_set_user_mfa_preference.side_effect = lambda **k: order.append("clear")
        c.admin_user_global_sign_out.side_effect = lambda **k: order.append("signout")
        c.admin_list_devices.side_effect = lambda **k: (
            order.append("list") or {"Devices": []})
        with patch("boto3.client", return_value=c):
            mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        assert order[:2] == ["clear", "signout"], order

    def test_a_failed_clear_is_reported_not_swallowed(self):
        """An admin must not read a silent success as "they can sign in now"."""
        c = _client(devices=[])
        c.admin_set_user_mfa_preference.side_effect = _err()
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        assert r.factor_cleared is False
        assert r.fully_contained is False
        assert any("clear_factor" in e for e in r.errors)


class TestTheClearIsVerifiedNotAssumed:
    """ADR-392. Two defects shipped reporting success on an account that was
    still challenged: clearing nothing (ADR-386) and clearing one factor of four
    (ADR-391). Both are invisible unless the account is read BACK.

    `factor_cleared=True` must mean "this account has no blocking factor", not
    "Cognito accepted our request".
    """

    def test_a_clean_account_reports_cleared(self):
        c = _client(devices=[], remaining_factors=[])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        assert r.factor_cleared is True
        assert r.fully_contained is True

    def test_a_surviving_factor_is_NOT_reported_as_cleared(self):
        """THE ADR-391 regression: TOTP cleared, EMAIL_OTP left enrolled, and the
        endpoint said success while the user was still challenged."""
        c = _client(devices=[], remaining_factors=["EMAIL_OTP"])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        assert r.factor_cleared is False
        assert r.fully_contained is False
        assert any("still enrolled" in e and "EMAIL_OTP" in e for e in r.errors), r.errors

    def test_the_surviving_factor_is_NAMED(self):
        """An admin needs to know WHICH factor survived; "reset failed" does not
        tell them whether to look at email, SMS or a stale token."""
        c = _client(devices=[], remaining_factors=["SMS_MFA", "EMAIL_OTP"])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        joined = " ".join(r.errors)
        assert "EMAIL_OTP" in joined and "SMS_MFA" in joined, r.errors

    def test_a_surviving_webauthn_does_not_fail_the_reset(self):
        """WebAuthn is deliberately not cleared (ADR-391) -- a passkey is
        hardware the user still holds. Counting it here would make every reset
        of a passkey user report failure."""
        c = _client(devices=[], remaining_factors=["WEBAUTHN"])
        with patch("boto3.client", return_value=c):
            r = mfa_containment.contain("u", "pool", "us-east-2", clear_factor=True)
        assert r.factor_cleared is True
        assert r.fully_contained is True

    def test_containment_does_not_read_back(self):
        """clear_factor=False never touches the preference, so there is nothing
        to verify -- and the responder's IAM role has no AdminGetUser."""
        c = _client(devices=["d1"])
        with patch("boto3.client", return_value=c):
            mfa_containment.contain("u", "pool", "us-east-2")
        c.admin_get_user.assert_not_called()
