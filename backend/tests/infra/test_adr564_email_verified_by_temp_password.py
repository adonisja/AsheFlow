"""Signing in with the emailed temporary password verifies the email (ADR-564 D2/D3).

Every create path now makes the address UNverified; PostAuthentication flips it
when a FORCE_CHANGE_PASSWORD sign-in completes -- that password was emailed to
the address, so the sign-in proves the inbox. CloudWatch, 30 days: the event
carried cognito:user_status on all 13 sign-ins (pass.check:
"status event=FORCE_CHANGE_PASSWORD user=FORCE_CHANGE_PASSWORD").
"""
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"
POST = "PostAuthentication_Authentication"


def _load():
    spec = importlib.util.spec_from_file_location("pre_auth_handler_564", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_auth_handler_564"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(status, verified="false", handed_over=None, groups=("walker",), in_event=True):
    mod, c = _load(), MagicMock()
    attrs = {"email": "new@person.example", "email_verified": verified}
    if handed_over:
        attrs["custom:pw_handed_over"] = handed_over
    c.admin_get_user.return_value = {"UserStatus": status, "UserMFASettingList": None,
                                     "UserAttributes": [{"Name": k, "Value": v} for k, v in attrs.items()]}
    c.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": g} for g in groups]}
    mod._client = c
    ev_attrs = {**attrs, "cognito:user_status": status} if in_event else {}
    out = mod.handler({"userPoolId": "us-east-2_TEST", "userName": "new.person", "triggerSource": POST,
                       "request": {"userAttributes": ev_attrs}}, None)
    writes = [a for call in c.admin_update_user_attributes.call_args_list for a in call.kwargs["UserAttributes"]]
    return out, writes


def test_the_temporary_password_sign_in_verifies_the_address():
    out, writes = _run("FORCE_CHANGE_PASSWORD")
    assert {"Name": "email_verified", "Value": "true"} in writes and out is not None


def test_it_verifies_field_accounts_too_not_only_privileged():
    """The pass logic returns early for field roles; verification must not."""
    _out, writes = _run("FORCE_CHANGE_PASSWORD", groups=("walker",))
    assert {"Name": "email_verified", "Value": "true"} in writes


@pytest.mark.parametrize("status", ["CONFIRMED", "RESET_REQUIRED"])
def test_other_sign_ins_prove_nothing_about_the_inbox(status):
    _out, writes = _run(status)
    assert {"Name": "email_verified", "Value": "true"} not in writes


def test_a_handed_over_password_does_not_verify():
    """ADR-394: when the credentials email fails, an admin passes the password on."""
    _out, writes = _run("FORCE_CHANGE_PASSWORD", handed_over="1")
    assert {"Name": "email_verified", "Value": "true"} not in writes


def test_a_missing_status_in_the_event_falls_back_to_a_lookup():
    _out, writes = _run("FORCE_CHANGE_PASSWORD", in_event=False)
    assert {"Name": "email_verified", "Value": "true"} in writes


def test_a_failure_never_fails_the_sign_in():
    mod = _load()
    c = MagicMock()
    c.admin_update_user_attributes.side_effect = RuntimeError("cognito down")
    c.admin_list_groups_for_user.return_value = {"Groups": []}
    mod._client = c
    ev = {"userPoolId": "p", "userName": "u", "triggerSource": POST, "request": {"userAttributes": {
        "cognito:user_status": "FORCE_CHANGE_PASSWORD", "email": "a@b.c", "email_verified": "false"}}}
    assert mod.handler(ev, None) is ev
