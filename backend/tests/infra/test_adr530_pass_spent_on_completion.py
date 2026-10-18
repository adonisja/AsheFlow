"""The enrolment pass is spent by a completed sign-in, not an attempted one (ADR-530).

Owner: "if a privileged account clicks that back to sign in button during
registration then they just used up their 1 free MFA pass". True, and so did a
mistyped temporary password, a reload, a closed tab, or a stranger typing the
owner's username: PreAuthentication fires before the password is checked, and
it was where the pass was spent.

These EXECUTE the handler (see test_adr459 for why source-reading was not
enough there).
"""
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"
STAMP = "2026-10-17T10:00:00+00:00"


def _load():
    spec = importlib.util.spec_from_file_location("pre_auth_handler_530", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_auth_handler_530"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ev(trigger, username="new.owner"):
    return {"userPoolId": "us-east-2_TEST", "userName": username,
            "triggerSource": trigger, "request": {}}


PRE = "PreAuthentication_Authentication"
POST = "PostAuthentication_Authentication"


class FakeUser:
    """A Cognito user whose stamp the handler can actually write -- so a
    sequence of attempts plays out the way it would against the pool."""

    def __init__(self, groups, mfa=None, stamp=None):
        self.groups, self.mfa = groups, mfa
        self.attrs = {} if stamp is None else {"custom:mfa_first_seen": stamp}
        self.client = MagicMock()
        self.client.admin_list_groups_for_user.side_effect = lambda **_: {
            "Groups": [{"GroupName": g} for g in self.groups]}
        self.client.admin_get_user.side_effect = lambda **_: {
            "UserMFASettingList": self.mfa,
            "UserAttributes": [{"Name": k, "Value": v} for k, v in self.attrs.items()]}

        def _update(**kw):
            for a in kw["UserAttributes"]:
                self.attrs[a["Name"]] = a["Value"]
        self.client.admin_update_user_attributes.side_effect = _update


def _attach(mod, user):
    mod._client = user.client
    return user


# ── the bug: an attempt that never completes must not spend the pass ────────

@pytest.mark.parametrize("abandoned", [
    "wrong temporary password (Cognito rejects AFTER PreAuth ran)",
    "Back to sign in on Update Password (ADR-529)",
    "reload / closed tab on a challenge",
    "a stranger typing the owner's username",
])
def test_an_attempt_that_never_completes_spends_nothing(abandoned):
    """Each of these is PreAuth with no PostAuth. Then the real sign-in."""
    mod = _load()
    u = _attach(mod, FakeUser(["admin"]))
    assert mod.handler(_ev(PRE), None) is not None      # the abandoned attempt
    assert "custom:mfa_first_seen" not in u.attrs, f"spent by: {abandoned}"
    assert mod.handler(_ev(PRE), None) is not None, (
        f"locked out after: {abandoned}")


def test_preauth_running_twice_in_one_sign_in_is_harmless():
    """Seen on dispatch.test 2026-10-16: the second run refused mid-sign-in."""
    mod = _load()
    _attach(mod, FakeUser(["dispatch"]))
    mod.handler(_ev(PRE), None)
    assert mod.handler(_ev(PRE), None) is not None
    assert mod.handler(_ev(POST), None) is not None


# ── the bound ADR-459 intended still holds ─────────────────────────────────

def test_one_completed_sign_in_then_refused():
    mod = _load()
    u = _attach(mod, FakeUser(["admin"]))
    mod.handler(_ev(PRE), None)
    mod.handler(_ev(POST), None)                        # completed: spent
    assert u.attrs.get("custom:mfa_first_seen")
    with pytest.raises(Exception) as exc:
        mod.handler(_ev(PRE), None)                     # signed out, unenrolled
    assert str(exc.value) == mod.ENROL_HINT


def test_post_does_not_restamp_a_spent_pass():
    """Re-stamping would move the recorded date; keep the first one."""
    mod = _load()
    u = _attach(mod, FakeUser(["admin"], stamp=STAMP))
    mod.handler(_ev(POST), None)
    u.client.admin_update_user_attributes.assert_not_called()


def test_post_ignores_enrolled_and_field_users():
    for groups, mfa in ((["admin"], ["SOFTWARE_TOKEN_MFA"]), (["walker"], None)):
        mod = _load()
        u = _attach(mod, FakeUser(groups, mfa=mfa))
        assert mod.handler(_ev(POST), None) is not None
        u.client.admin_update_user_attributes.assert_not_called()


# ── D2: PostAuthentication never raises ────────────────────────────────────

@pytest.mark.parametrize("broken", ["admin_get_user", "admin_list_groups_for_user",
                                    "admin_update_user_attributes"])
def test_post_never_fails_a_completed_sign_in(broken):
    """A raise here fails the sign-in that just succeeded."""
    mod = _load()
    u = _attach(mod, FakeUser(["admin"]))
    getattr(u.client, broken).side_effect = RuntimeError("cognito is down")
    assert mod.handler(_ev(POST), None) is not None


def test_post_never_raises_the_refusal_either():
    """Even a spent, unenrolled account: refusing is PreAuth's job, and by the
    time PostAuth runs Cognito has already decided."""
    mod = _load()
    _attach(mod, FakeUser(["admin"], stamp=STAMP))
    assert mod.handler(_ev(POST), None) is not None


# ── D3: why the OLD code must never be attached as PostAuthentication ──────

def test_pre_branch_on_a_completed_sign_in_would_refuse():
    """Documents the deploy-order hazard: run the PRE logic after a stamp exists
    (which is what old code attached as PostAuth would do) and it raises. The
    new code routes PostAuth away from it."""
    mod = _load()
    _attach(mod, FakeUser(["admin"], stamp=STAMP))
    with pytest.raises(Exception):
        mod.handler(_ev(PRE), None)
    assert mod.handler(_ev(POST), None) is not None
