"""Our own audited MFA resets don't set off the unenrolment alarm (ADR-553).

Support reset test.surveyor on staging (2026-10-20); a minute later the ADR-387
responder contained the account again and emailed "MFA factor removed: account
contained". CloudTrail showed the caller was our own backend role.
"""
import ast
import importlib.util
import pathlib
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "mfa_unenrol_responder" / "handler.py"
STAGING = "arn:aws:iam::586794453404:role/asheflow-ec2-role-staging"
PROD = "arn:aws:iam::586794453404:role/asheflow-ec2-role-prod"


def _load(trusted: str | None):
    with patch.dict("os.environ", {"TRUSTED_RESET_ROLE_ARNS": trusted} if trusted is not None else {}, clear=False):
        if trusted is None:
            import os; os.environ.pop("TRUSTED_RESET_ROLE_ARNS", None)
        spec = importlib.util.spec_from_file_location("responder_553", HANDLER)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


def _event(identity: dict, name="AdminSetUserMFAPreference"):
    return {"detail": {
        "eventName": name, "eventID": "78f17f43-e931-4c28-89ff-f6f73d118f02",
        "userIdentity": identity,
        "requestParameters": {"softwareTokenMfaSettings": {"enabled": False, "preferredMfa": False},
                              "userPoolId": "us-east-2_SvVO2ofAb"},
        "additionalEventData": {"sub": "d12bd500-00d1-7046-8f81-82a17db16f27"},
    }}


def _role(arn):
    """The shape measured on the real event (CloudTrail lookup, eventID 78f17f43-...)."""
    return {"type": "AssumedRole", "arn": arn.replace(":iam::", ":sts::").replace(":role/", ":assumed-role/") + "/i-0adb5030b967854b2",
            "sessionContext": {"sessionIssuer": {"type": "Role", "arn": arn}}}


def _run(mod, event):
    cog, sns = MagicMock(), MagicMock()
    cog.list_users.return_value = {"Users": [{"Username": "test.surveyor"}]}
    cog.admin_list_devices.return_value = {"Devices": []}
    with patch.object(mod.boto3, "client", side_effect=lambda svc, **k: sns if svc == "sns" else cog), \
         patch.object(mod, "ALERT_TOPIC_ARN", "arn:aws:sns:us-east-2:1:AsheFlow-SecurityAlerts"):
        out = mod.handler(event, None)
    return out, cog, sns


@pytest.mark.parametrize("role", [STAGING, PROD])
def test_our_own_reset_is_neither_contained_nor_alerted(role):
    mod = _load(f"{STAGING},{PROD}")
    out, cog, sns = _run(mod, _event(_role(role)))
    assert out == {"action": "ignored", "reason": "our_reset", "role": role}
    cog.admin_user_global_sign_out.assert_not_called()
    sns.publish.assert_not_called()


@pytest.mark.parametrize("identity,why", [
    ({"type": "Unknown", "principalId": "Anonymous"}, "a user's own unenrolment"),
    (_role("arn:aws:iam::586794453404:role/asheflow-ec2-role"), "the unused legacy role"),
    (_role("arn:aws:iam::586794453404:role/asheflow-ec2-role-staging-copy"), "a look-alike role name"),
    (_role("arn:aws:iam::999999999999:role/asheflow-ec2-role-staging"), "the same name in another account"),
    ({"type": "IAMUser", "arn": "arn:aws:iam::586794453404:user/someone"}, "a console user"),
    ({"type": "AssumedRole", "sessionContext": {}}, "no session issuer"),
    # Probe P3 first passed: the exact ARN is the real guarantee, and the
    # AssumedRole check is a second layer. Pinned: only an assumed-role
    # SESSION of our role counts, whatever else carries the ARN.
    ({"type": "FederatedUser", "sessionContext": {"sessionIssuer": {"arn": STAGING}}},
     "our ARN on something that is not an assumed-role session"),
])
def test_anyone_else_is_still_contained_and_alerted(identity, why):
    mod = _load(f"{STAGING},{PROD}")
    out, cog, sns = _run(mod, _event(identity, name="SetUserMFAPreference"))
    assert out["action"] == "contained", why
    cog.admin_user_global_sign_out.assert_called_once()
    sns.publish.assert_called_once()


@pytest.mark.parametrize("value", [None, "", " , "])
def test_with_nothing_configured_nothing_is_trusted(value):
    """D2: a missing variable restores the old noise, never silence."""
    mod = _load(value)
    out, _cog, sns = _run(mod, _event(_role(STAGING)))
    assert out["action"] == "contained"
    sns.publish.assert_called_once()


# ── D3: "our backend role" really means "an audited reset" ─────────────────

APP = ROOT / "backend" / "app"


def test_the_backend_disables_a_factor_only_inside_containment():
    """The responder trusts the ROLE; this pins that the only code holding it
    that calls AdminSetUserMFAPreference is mfa_containment.contain (plus the
    ADR-388 probe, whose call always fails and is ignored by ADR-407)."""
    hits = sorted(str(p.relative_to(APP)) for p in APP.rglob("*.py")
                  if "admin_set_user_mfa_preference(" in p.read_text())
    assert hits == ["services/mfa_containment.py", "tasks/security_infra_health.py"]


def test_every_factor_clearing_reset_writes_an_audit_row():
    found = []
    for p in (APP / "routers").glob("*.py"):
        tree = ast.parse(p.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
            clears = any(getattr(c.func, "attr", "") == "contain" and any(
                k.arg == "clear_factor" and getattr(k.value, "value", None) is True for k in c.keywords)
                for c in calls)
            if clears:
                found.append(fn.name)
                assert any(getattr(c.func, "id", getattr(c.func, "attr", "")) == "write_audit" for c in calls), (
                    f"{p.name}::{fn.name} clears a factor without an audit row -- ADR-553's trust has no record")
    assert sorted(found) == ["platform_reset_mfa", "reset_contributor_mfa", "reset_employee_mfa"]
