"""The MFA unenrol responder's decision logic (ADR-387).

The Lambda lives outside the app (infra/lambda/) because it runs standalone with
no VPC access, so it is loaded here by path. What is tested is the branching --
which events it acts on, which it ignores, and which it ALERTS on -- because
that is where a wrong answer is silent.

The alert-on-unattributable path matters most: additionalEventData.sub is the
ONLY identifier in the event (userIdentity is Anonymous, username is redacted),
so if AWS changes that payload the responder must shout rather than shrug.
"""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HANDLER = (Path(__file__).resolve().parents[3]
            / "infra" / "lambda" / "mfa_unenrol_responder" / "handler.py")


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("unenrol_responder", _HANDLER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _event(*, sub="s-1", enabled=False, pool="us-east-2_TEST",
           name="SetUserMFAPreference", settings_key="softwareTokenMfaSettings"):
    detail = {
        "eventName": name,
        "eventID": "evt-1",
        "requestParameters": {
            settings_key: {"enabled": enabled, "preferredMfa": enabled},
            "userPoolId": pool,
        },
    }
    if sub is not None:
        detail["additionalEventData"] = {"sub": sub}
    return {"detail": detail}


class TestItActsOnlyOnRemovals:
    def test_a_disable_is_contained(self, mod):
        c = MagicMock()
        c.list_users.return_value = {"Users": [{"Username": "walker.test"}]}
        c.admin_list_devices.return_value = {"Devices": [{"DeviceKey": "d1"}]}
        with patch.object(mod.boto3, "client", return_value=c):
            r = mod.handler(_event(enabled=False), None)
        assert r["action"] == "contained"
        assert r["signed_out"] is True
        assert r["devices_forgotten"] == 1

    def test_an_enable_is_ignored(self, mod):
        """Someone enrolling is the happy path. The same API sets both."""
        with patch.object(mod.boto3, "client") as bc:
            r = mod.handler(_event(enabled=True), None)
        assert r["action"] == "ignored"
        bc.assert_not_called()

    def test_disabling_email_also_counts(self, mod):
        """An email-only account turning email off is equally unprotected.
        Checking only softwareTokenMfaSettings would miss it."""
        c = MagicMock()
        c.list_users.return_value = {"Users": [{"Username": "u"}]}
        c.admin_list_devices.return_value = {"Devices": []}
        with patch.object(mod.boto3, "client", return_value=c):
            r = mod.handler(
                _event(enabled=False, settings_key="emailMfaSettings"), None)
        assert r["action"] == "contained"

    def test_the_admin_variant_is_contained_too(self, mod):
        c = MagicMock()
        c.list_users.return_value = {"Users": [{"Username": "u"}]}
        c.admin_list_devices.return_value = {"Devices": []}
        with patch.object(mod.boto3, "client", return_value=c):
            r = mod.handler(
                _event(enabled=False, name="AdminSetUserMFAPreference"), None)
        assert r["action"] == "contained"


class TestItNeverFailsSilently:
    def test_a_missing_sub_alerts(self, mod):
        """additionalEventData.sub is the ONLY identifier. Its absence means the
        payload shape changed, which a human must see."""
        with patch.object(mod, "_alert") as alert:
            r = mod.handler(_event(sub=None), None)
        assert r["action"] == "alerted"
        assert r["reason"] == "no_sub"
        alert.assert_called_once()

    def test_a_sub_in_no_pool_alerts(self, mod):
        c = MagicMock()
        c.list_users.return_value = {"Users": []}
        with patch.object(mod.boto3, "client", return_value=c), \
             patch.object(mod, "_alert") as alert:
            r = mod.handler(_event(), None)
        assert r["action"] == "alerted"
        assert r["reason"] == "sub_not_found"
        alert.assert_called_once()

    def test_containment_alerts_even_on_success(self, mod):
        """A silent successful containment is a security action nobody knows
        happened."""
        c = MagicMock()
        c.list_users.return_value = {"Users": [{"Username": "u"}]}
        c.admin_list_devices.return_value = {"Devices": []}
        with patch.object(mod.boto3, "client", return_value=c), \
             patch.object(mod, "_alert") as alert:
            mod.handler(_event(), None)
        alert.assert_called_once()


class TestContainmentOrderMatchesTheService:
    def test_sign_out_precedes_forgetting_devices(self, mod):
        """Same invariant as mfa_containment.contain(): the session is live while
        devices are forgotten one call at a time."""
        order = []
        c = MagicMock()
        c.list_users.return_value = {"Users": [{"Username": "u"}]}
        c.admin_user_global_sign_out.side_effect = lambda **k: order.append("signout")
        c.admin_list_devices.side_effect = lambda **k: (
            order.append("list") or {"Devices": [{"DeviceKey": "d1"}]})
        c.admin_forget_device.side_effect = lambda **k: order.append("forget")
        with patch.object(mod.boto3, "client", return_value=c), \
             patch.object(mod, "_alert"):
            mod.handler(_event(), None)
        assert order[0] == "signout", f"sign-out must be first, got {order}"

    def test_no_username_reaches_the_alert_body(self, mod):
        """ADR-115 D7 -- the sub is an opaque id; the username is not."""
        c = MagicMock()
        c.list_users.return_value = {"Users": [{"Username": "sensitive.person"}]}
        c.admin_list_devices.return_value = {"Devices": []}
        with patch.object(mod.boto3, "client", return_value=c), \
             patch.object(mod, "_alert") as alert:
            mod.handler(_event(), None)
        body = str(alert.call_args)
        assert "sensitive.person" not in body
