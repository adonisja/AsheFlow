"""A temporary-password sign-in does not spend the pass (ADR-533).

Measured on staging 2026-10-17 (pass.check, fresh admin, real invite path):

    22:28:10.291  pre-auth:  allowing pass.check to enrol
    22:28:10.909  post-auth: pass.check completed its one unenrolled sign-in; pass spent

PostAuthentication fired 0.6 s after the temporary password checked out --
while the user was on "Update Password", before they pressed Back. ADR-530
assumed it waited for every challenge. These replay that order.
"""
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"
PRE, POST = "PreAuthentication_Authentication", "PostAuthentication_Authentication"


def _load():
    spec = importlib.util.spec_from_file_location("pre_auth_handler_533", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_auth_handler_533"] = mod
    spec.loader.exec_module(mod)
    return mod


class Pool:
    """One privileged, unenrolled user whose status and stamp really change."""

    def __init__(self, status):
        self.status, self.attrs = status, {}
        c = MagicMock()
        c.admin_list_groups_for_user.side_effect = lambda **_: {"Groups": [{"GroupName": "admin"}]}
        c.admin_get_user.side_effect = lambda **_: {
            "UserStatus": self.status, "UserMFASettingList": None,
            "UserAttributes": [{"Name": k, "Value": v} for k, v in self.attrs.items()]}
        c.admin_update_user_attributes.side_effect = (
            lambda **kw: self.attrs.update({a["Name"]: a["Value"] for a in kw["UserAttributes"]}))
        self.client = c

    def ev(self, trigger, with_status_attr=True):
        req = {"userAttributes": {"cognito:user_status": self.status}} if with_status_attr else {}
        return {"userPoolId": "us-east-2_TEST", "userName": "pass.check",
                "triggerSource": trigger, "request": req}


def _setup(status):
    mod, pool = _load(), Pool(status)
    mod._client = pool.client
    return mod, pool


def test_the_staging_sequence_no_longer_spends_the_pass():
    """Temp password accepted -> PostAuth fires -> user presses Back."""
    mod, pool = _setup("FORCE_CHANGE_PASSWORD")
    mod.handler(pool.ev(PRE), None)
    mod.handler(pool.ev(POST), None)                       # fired at 22:28:10.909
    assert mod.FIRST_SEEN_ATTR not in pool.attrs, "spent on a temporary-password sign-in"
    assert mod.handler(pool.ev(PRE), None) is not None, "locked out after Back"


def test_the_status_is_read_from_admin_get_user_when_the_event_lacks_it():
    """We have not yet SEEN the event's attribute in production; don't depend on it."""
    mod, pool = _setup("FORCE_CHANGE_PASSWORD")
    mod.handler(pool.ev(POST, with_status_attr=False), None)
    assert mod.FIRST_SEEN_ATTR not in pool.attrs


def test_an_admin_forced_reset_is_the_same_shape():
    mod, pool = _setup("RESET_REQUIRED")
    mod.handler(pool.ev(POST), None)
    assert mod.FIRST_SEEN_ATTR not in pool.attrs


def test_once_the_password_is_their_own_the_next_completion_spends_it():
    """The bound ADR-459 intended still holds, one step later."""
    mod, pool = _setup("FORCE_CHANGE_PASSWORD")
    mod.handler(pool.ev(POST), None)                       # temp password: not spent
    pool.status = "CONFIRMED"                              # they set their own password
    mod.handler(pool.ev(POST), None)                       # a completed sign-in
    assert pool.attrs.get(mod.FIRST_SEEN_ATTR)
    # ADR-548: the stamp opens a 24-hour window; refused once it has passed.
    from datetime import datetime, timedelta
    opened = datetime.fromisoformat(pool.attrs[mod.FIRST_SEEN_ATTR])
    mod._now = lambda: opened + timedelta(hours=24)
    with pytest.raises(Exception) as exc:
        mod.handler(pool.ev(PRE), None)                    # a day on, never enrolled
    assert str(exc.value) == mod.ENROL_HINT


def test_confirmed_users_are_still_stamped_immediately():
    """Permanent-password accounts (seed scripts, ADR-526) behave as in ADR-530."""
    mod, pool = _setup("CONFIRMED")
    mod.handler(pool.ev(POST), None)
    assert pool.attrs.get(mod.FIRST_SEEN_ATTR)


def test_the_post_branch_still_never_raises():
    mod, pool = _setup("FORCE_CHANGE_PASSWORD")
    pool.client.admin_get_user.side_effect = RuntimeError("cognito is down")
    assert mod.handler(pool.ev(POST), None) is not None
