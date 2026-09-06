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


def _client(devices=None, signout_error=None, forget_error=None):
    c = MagicMock()
    c.admin_list_devices.return_value = {
        "Devices": [{"DeviceKey": k} for k in (devices or [])]
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
