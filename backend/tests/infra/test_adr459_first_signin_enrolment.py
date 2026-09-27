"""A privileged account can reach enrolment on its first sign-in (ADR-459).

These EXECUTE the handler with a stubbed Cognito client. ADR-362's tests read
the source, which is why the deadlock survived: every string they assert was
present and correct, and the flow was still impossible.
"""
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"


def _load():
    """Fresh module per test: the handler caches its boto3 client globally."""
    spec = importlib.util.spec_from_file_location("pre_auth_handler", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_auth_handler"] = mod
    spec.loader.exec_module(mod)
    return mod


def _event(username="nicoy.hunt"):
    return {"userPoolId": "us-east-2_TEST", "userName": username, "request": {}}


def _stub(mod, *, groups, mfa_list=None, attrs=None):
    client = MagicMock()
    client.admin_list_groups_for_user.return_value = {
        "Groups": [{"GroupName": g} for g in groups]
    }
    client.admin_get_user.return_value = {
        "UserMFASettingList": mfa_list,
        "UserAttributes": [{"Name": k, "Value": v} for k, v in (attrs or {}).items()],
    }
    mod._client = client
    return client


# ── the deadlock this ADR exists to remove ──────────────────────────────────

def test_a_new_owner_is_allowed_through_to_enrol():
    """The bug: every Owner of every new tenant was refused on first sign-in."""
    mod = _load()
    client = _stub(mod, groups=["admin"], mfa_list=None, attrs={})
    out = mod.handler(_event(), None)
    assert out is not None, "a brand-new Owner is still locked out"
    client.admin_update_user_attributes.assert_called_once()


def test_the_exemption_is_spent_on_use():
    """One sign-in wide. The stamp is what stops it being replayed."""
    mod = _load()
    client = _stub(mod, groups=["admin"], mfa_list=None, attrs={})
    mod.handler(_event(), None)
    kwargs = client.admin_update_user_attributes.call_args.kwargs
    assert kwargs["Username"] == "nicoy.hunt"
    names = [a["Name"] for a in kwargs["UserAttributes"]]
    assert mod.FIRST_SEEN_ATTR in names


def test_a_second_attempt_with_no_factor_is_refused():
    """Once they have been inside the app, the message is true and enforced."""
    mod = _load()
    _stub(mod, groups=["admin"], mfa_list=None,
          attrs={mod.FIRST_SEEN_ATTR: "2026-09-27T10:00:00+00:00"})
    with pytest.raises(Exception) as exc:
        mod.handler(_event(), None)
    assert str(exc.value) == mod.ENROL_HINT


# ── the enforcement ADR-362 built must still hold ───────────────────────────

def test_an_enrolled_privileged_user_passes_untouched():
    mod = _load()
    client = _stub(mod, groups=["admin"], mfa_list=["SOFTWARE_TOKEN_MFA"], attrs={})
    assert mod.handler(_event(), None) is not None
    client.admin_update_user_attributes.assert_not_called()


def test_a_field_role_is_never_gated_here():
    """Field staff are governed by the grace period, not this trigger."""
    mod = _load()
    client = _stub(mod, groups=["walker"], mfa_list=None, attrs={})
    assert mod.handler(_event("walker.test"), None) is not None
    client.admin_update_user_attributes.assert_not_called()


@pytest.mark.parametrize(
    "group", ["super_admin", "admin", "management", "dispatch", "platform_support"]
)
def test_every_privileged_group_still_gets_exactly_one_pass(group):
    """The exemption must not quietly widen to a permanent bypass."""
    mod = _load()
    _stub(mod, groups=[group], mfa_list=None,
          attrs={mod.FIRST_SEEN_ATTR: "2026-09-27T10:00:00+00:00"})
    with pytest.raises(Exception):
        mod.handler(_event(), None)


# ── failure modes ───────────────────────────────────────────────────────────

def test_a_failed_stamp_still_lets_the_user_in():
    """Refusing a sign-in because bookkeeping failed rebuilds the lockout."""
    mod = _load()
    client = _stub(mod, groups=["admin"], mfa_list=None, attrs={})
    client.admin_update_user_attributes.side_effect = RuntimeError("throttled")
    assert mod.handler(_event(), None) is not None


def test_it_still_fails_open_on_an_unexpected_error():
    """ADR-362's rule: a bug here must not lock out the whole company."""
    mod = _load()
    client = _stub(mod, groups=["admin"], mfa_list=None, attrs={})
    client.admin_get_user.side_effect = RuntimeError("cognito is down")
    assert mod.handler(_event(), None) is not None


def test_the_refusal_is_not_swallowed_by_the_fail_open_path():
    """The one case that must fail CLOSED."""
    mod = _load()
    _stub(mod, groups=["admin"], mfa_list=None,
          attrs={mod.FIRST_SEEN_ATTR: "2026-09-27T10:00:00+00:00"})
    with pytest.raises(Exception) as exc:
        mod.handler(_event(), None)
    assert str(exc.value) == mod.ENROL_HINT
