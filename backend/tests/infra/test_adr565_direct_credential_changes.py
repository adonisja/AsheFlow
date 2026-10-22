"""Credential changes made by calling Cognito directly are contained (ADR-565).

The record shape is real -- ADR-558's staging probe produced it:
  DeleteUserAttributes errorCode=NotAuthorizedException userIdentity={'type': 'Unknown', 'principalId': 'Anonymous'}
  additionalEventData={'sub': 'f1bb2510-…'}  accessToken HIDDEN_DUE_TO_SECURITY_REASONS
"""
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "mfa_unenrol_responder" / "handler.py"
SUB = "f1bb2510-70c1-70e3-f31e-42054a10d176"


def _load():
    with patch.dict("os.environ", {"USER_POOL_IDS": "us-east-2_STAGING,us-east-2_PROD", "ALERT_TOPIC_ARN": "arn:t"}):
        spec = importlib.util.spec_from_file_location("responder_565", HANDLER)
        m = importlib.util.module_from_spec(spec)
        sys.modules["responder_565"] = m
        spec.loader.exec_module(m)
    return m


def _event(name, error=None, sub=SUB):
    d = {"eventName": name, "eventID": "e-1", "userIdentity": {"type": "Unknown", "principalId": "Anonymous"},
         "requestParameters": {"accessToken": "HIDDEN_DUE_TO_SECURITY_REASONS"}}
    if sub:
        d["additionalEventData"] = {"sub": sub}
    if error:
        d["errorCode"] = error
    return {"detail": d}


def _run(event):
    m = _load()
    with patch.object(m, "_username_for_sub", side_effect=lambda c, pid, sub: "victim" if pid == "us-east-2_STAGING" else None), \
         patch.object(m, "_contain", return_value={"signed_out": True, "devices_forgotten": 1, "errors": []}) as contain, \
         patch.object(m, "_alert") as alert, patch.object(m.boto3, "client", return_value=MagicMock()):
        out = m.handler(event, None)
    return out, contain, alert


@pytest.mark.parametrize("name", ["ChangePassword", "UpdateUserAttributes", "DeleteUserAttributes", "VerifyUserAttribute"])
def test_a_successful_direct_change_is_contained(name):
    out, contain, alert = _run(_event(name))
    assert out["action"] == "contained"
    contain.assert_called_once()
    assert "victim" not in str(alert.call_args), "no username in the alert (ADR-115 D7)"


def test_a_refused_write_is_contained_too():
    """Since ADR-558 a real token gets NotAuthorizedException on email/stamp writes."""
    out, contain, alert = _run(_event("DeleteUserAttributes", error="NotAuthorizedException"))
    assert out["action"] == "contained" and "refused" in alert.call_args.args[0]


def test_other_errors_are_logged_not_contained():
    out, contain, _alert = _run(_event("UpdateUserAttributes", error="InvalidParameterException"))
    assert out["action"] == "ignored"
    contain.assert_not_called()


def test_an_unattributable_event_alerts():
    out, contain, alert = _run(_event("ChangePassword", sub=None))
    assert out == {"action": "alerted", "reason": "no_sub"}
    contain.assert_not_called()


@pytest.mark.parametrize("ours", ["ForgotPassword", "ConfirmForgotPassword", "AdminUpdateUserAttributes"])
def test_our_own_flows_are_not_watched(ours):
    m = _load()
    assert ours not in m.DIRECT_CREDENTIAL_EVENTS


def test_no_client_calls_a_watched_api():
    """ADR-541 D7's precondition, pinned: if a client starts calling one of these,
    the detector would contain that client's own users."""
    import re
    pattern = re.compile(r"\b(changePassword|updatePassword|updateUserAttributes?|deleteUserAttributes|verifyUserAttribute|confirmUserAttribute)\(")
    hits = [str(p.relative_to(ROOT)) for d in ("frontend/src", "mobile/src")
            for p in (ROOT / d).rglob("*.ts*") if pattern.search(p.read_text(errors="ignore"))]
    assert not hits, hits
