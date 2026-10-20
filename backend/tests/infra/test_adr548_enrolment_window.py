"""The enrolment pass is a 24-hour window, not one sign-in (ADR-548).

prod, 2026-10-20: manager.test was allowed at 12:45:05, the pass was spent at
12:45:06 by the completed sign-in, and the same person was refused at 12:46:27
after pressing the wall's own Sign out button. These EXECUTE the handler.
"""
import importlib.util
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services import mfa_status

ROOT = pathlib.Path(__file__).resolve().parents[3]
HANDLER = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"
NOW = datetime(2026, 10, 20, 12, 46, 27, tzinfo=timezone.utc)
PRE = "PreAuthentication_Authentication"
POST = "PostAuthentication_Authentication"


def _load(now=NOW):
    spec = importlib.util.spec_from_file_location("pre_auth_handler_548", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_auth_handler_548"] = mod
    spec.loader.exec_module(mod)
    mod._now = lambda: now
    return mod


class FakeUser:
    def __init__(self, groups=("management",), mfa=None, stamp=None):
        self.groups, self.mfa = list(groups), mfa
        self.attrs = {} if stamp is None else {"custom:mfa_first_seen": stamp}
        self.client = MagicMock()
        self.client.admin_list_groups_for_user.side_effect = lambda **_: {
            "Groups": [{"GroupName": g} for g in self.groups]}
        self.client.admin_get_user.side_effect = lambda **_: {
            "UserMFASettingList": self.mfa, "UserStatus": "CONFIRMED",
            "UserAttributes": [{"Name": k, "Value": v} for k, v in self.attrs.items()]}

        def _update(**kw):
            for a in kw["UserAttributes"]:
                self.attrs[a["Name"]] = a["Value"]
        self.client.admin_update_user_attributes.side_effect = _update


def _ev(trigger):
    return {"userPoolId": "us-east-2_TEST", "userName": "manager.test",
            "triggerSource": trigger, "request": {}}


def _run(mod, user, trigger=PRE):
    mod._client = user.client
    return mod.handler(_ev(trigger), None)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


# ── the incident, replayed ─────────────────────────────────────────────────

def test_signing_out_of_the_wall_and_back_in_is_not_a_lockout():
    """The exact prod sequence: allow, complete (stamp), sign out, sign in."""
    first = NOW - timedelta(minutes=1, seconds=21)
    mod = _load(now=first)
    u = FakeUser()
    assert _run(mod, u) is not None
    _run(mod, u, POST)
    assert u.attrs["custom:mfa_first_seen"] == _iso(first)
    mod._now = lambda: NOW                                  # 12:46:27
    assert _run(mod, u) is not None, "refused 81 s into the window"


@pytest.mark.parametrize("age", [timedelta(0), timedelta(hours=1),
                                 timedelta(hours=23, minutes=59, seconds=59)])
def test_inside_the_window_is_allowed(age):
    mod = _load()
    assert _run(mod, FakeUser(stamp=_iso(NOW - age))) is not None


@pytest.mark.parametrize("age", [timedelta(hours=24), timedelta(days=3)])
def test_at_or_after_24_hours_is_refused(age):
    mod = _load()
    with pytest.raises(Exception) as exc:
        _run(mod, FakeUser(stamp=_iso(NOW - age)))
    assert str(exc.value) == mod.ENROL_HINT


def test_the_window_does_not_move_on_later_sign_ins():
    """PostAuthentication must not re-stamp: that would slide the window
    forward on every sign-in and make it unbounded."""
    opened = _iso(NOW - timedelta(hours=5))
    mod = _load()
    u = FakeUser(stamp=opened)
    _run(mod, u)
    _run(mod, u, POST)
    assert u.attrs["custom:mfa_first_seen"] == opened


# ── a stamp it cannot trust reads as closed ────────────────────────────────

@pytest.mark.parametrize("stamp", [
    "not a date",
    "2026-10-20T12:00:00",                                   # naive
    _iso(NOW + timedelta(days=365)),                         # forged into the future
])
def test_an_untrustworthy_stamp_closes_the_window(stamp):
    mod = _load()
    with pytest.raises(Exception) as exc:
        _run(mod, FakeUser(stamp=stamp))
    assert str(exc.value) == mod.ENROL_HINT


def test_small_clock_skew_is_tolerated():
    mod = _load()
    assert _run(mod, FakeUser(stamp=_iso(NOW + timedelta(minutes=2)))) is not None


# ── unchanged neighbours ───────────────────────────────────────────────────

def test_an_enrolled_account_is_never_refused_by_an_old_stamp():
    mod = _load()
    u = FakeUser(mfa=["SOFTWARE_TOKEN_MFA"], stamp=_iso(NOW - timedelta(days=30)))
    assert _run(mod, u) is not None


def test_a_field_role_is_never_gated():
    mod = _load()
    assert _run(mod, FakeUser(groups=["walker"], stamp=_iso(NOW - timedelta(days=30)))) is not None


# ── D2: one rule, two copies, kept equal ───────────────────────────────────

def test_the_lambda_and_the_backend_agree_on_the_window():
    mod = _load()
    assert timedelta(hours=mod.SETUP_WINDOW_HOURS) == mfa_status.PRIVILEGED_SETUP_WINDOW


def test_the_refusal_says_the_window_closed_and_names_the_way_out():
    mod = _load()
    assert "24-hour" in mod.ENROL_HINT and "administrator" in mod.ENROL_HINT
    assert "sign in on the web" not in mod.ENROL_HINT.lower(), (
        "a closed window cannot be fixed by signing in")


# ── D3: the backend reads the same window ──────────────────────────────────

@pytest.mark.parametrize("stamp,state", [
    (None, "unopened"),
    (_iso(NOW - timedelta(hours=1)), "open"),
    (_iso(NOW - timedelta(hours=24)), "closed"),
    ("not a date", "closed"),
    (_iso(NOW + timedelta(days=1)), "closed"),
])
def test_the_backend_rule_matches_the_lambda(stamp, state):
    """Same inputs, same verdict, on both copies of the rule."""
    got, _ = mfa_status.setup_window_ends_at(stamp, now=NOW)
    assert got == state
    if stamp is not None:
        mod = _load()
        assert mod._window_open(stamp, NOW) == (state == "open")


def test_mfa_status_carries_the_deadline_only_while_open():
    from unittest.mock import patch
    from app.routers import employees as E
    ends = NOW + timedelta(hours=20)
    base = {"tier": "privileged", "enrolled": False}
    with patch.object(mfa_status, "read_setup_window", return_value=("open", ends)):
        assert E._with_setup_window(dict(base), "m")["setup_window_ends_at"] == ends.isoformat()
    with patch.object(mfa_status, "read_setup_window", return_value=("closed", ends)):
        assert E._with_setup_window(dict(base), "m")["setup_window_ends_at"] is None
    with patch.object(mfa_status, "read_setup_window") as never:
        out = E._with_setup_window({"tier": "privileged", "enrolled": True}, "m")
        assert out["setup_window_ends_at"] is None
        out = E._with_setup_window({"tier": "field", "enrolled": False}, "m")
        assert out["setup_window_ends_at"] is None
        never.assert_not_called()       # no AWS read for anyone not on the wall


def _report_with(db, stamps):
    """Run the ADR-467 report with one management account per stamp."""
    import uuid
    from unittest.mock import patch
    from app.models.employee import Employee
    from app.routers import employees as E
    from tests.conftest import SEED_COMPANY_ID

    admin = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="Admin",
                     role="admin", is_active=True)
    db.add(admin)
    by_name = {}
    for i, stamp in enumerate(stamps):
        e = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=f"M{i}",
                     role="management", is_active=True)
        db.add(e)
        by_name[f"M{i}"] = stamp
    db.commit()

    def get_user(**kw):
        stamp = by_name.get(kw["Username"])
        attrs = [] if stamp is None else [{"Name": "custom:mfa_first_seen", "Value": stamp}]
        return {"UserMFASettingList": None, "UserAttributes": attrs}

    client = MagicMock()
    client.admin_get_user.side_effect = get_user
    fn = getattr(E.get_mfa_enrolment, "__wrapped__", E.get_mfa_enrolment)
    with patch("boto3.client", return_value=client), \
         patch.object(E, "cognito_username_for", side_effect=lambda emp: emp.name), \
         patch.object(mfa_status, "setup_window_ends_at",
                      side_effect=lambda s, now=None: _real(s, NOW)):
        rows = fn(request=MagicMock(), caller=admin, _={}, db=db)
    return {r.name: r.pass_spent for r in rows if r.name.startswith("M")}


_real = mfa_status.setup_window_ends_at


def test_the_lockout_report_does_not_call_someone_mid_setup_locked_out(db):
    """ADR-467's `pass_spent` meant "stamped". Inside the window that is a
    person on the wall with hours left, not a lockout an admin must fix."""
    got = _report_with(db, [
        None,                                     # never signed in
        _iso(NOW - timedelta(hours=2)),           # mid-setup
        _iso(NOW - timedelta(hours=30)),          # window closed: locked out
    ])
    assert got == {"M0": False, "M1": False, "M2": True}


# ── D4/D5: both clients (web AND mobile) ───────────────────────────────────

WEB_CLASSIFIER = ROOT / "frontend" / "src" / "utils" / "signInError.ts"
MOB_CLASSIFIER = ROOT / "mobile" / "src" / "screens" / "Auth" / "signInError.ts"
WEB_LOGIN = ROOT / "frontend" / "src" / "components" / "auth" / "Login.tsx"
MOB_LOGIN = ROOT / "mobile" / "src" / "screens" / "Auth" / "LoginScreen.tsx"
WEB_WALL = ROOT / "frontend" / "src" / "pages" / "MfaRequired.tsx"
MOB_WALL = ROOT / "mobile" / "src" / "screens" / "MfaRequiredScreen.tsx"


def test_the_two_classifiers_are_the_same_file():
    """Twins drift; identical text is the cheapest proof they have not."""
    assert WEB_CLASSIFIER.read_text() == MOB_CLASSIFIER.read_text()


def test_the_lambda_sentence_is_what_the_clients_recognise():
    """The panel appears only if the refusal still contains both words the
    classifier keys on. Rewording ENROL_HINT without this check would silently
    drop every client back to raw red text."""
    import re
    src = WEB_CLASSIFIER.read_text()
    assert "/two-factor/i" in src and "/administrator/i" in src
    hint = _load().ENROL_HINT
    assert re.search("two-factor", hint, re.I) and re.search("administrator", hint, re.I)


@pytest.mark.parametrize("login", [WEB_LOGIN, MOB_LOGIN], ids=["web", "mobile"])
def test_no_sign_in_catch_shows_the_raw_message(login):
    src = login.read_text()
    assert "classifySignInError" in src
    assert "setError(err.message" not in src, (
        "a catch still puts Cognito's raw text (with its trigger wrapper) on screen")
    assert "Two-factor setup needed" in src


@pytest.mark.parametrize("wall", [WEB_WALL, MOB_WALL], ids=["web", "mobile"])
def test_the_wall_states_the_deadline(wall):
    src = wall.read_text()
    assert "setup_window_ends_at" in src
    assert "administrator will need to reset" in src


def test_the_web_wall_no_longer_promises_a_free_sign_out_to_privileged_accounts():
    """The promise may remain only on the field branch, where PreAuthentication
    never refuses. The tier-neutral "will not skip this step" stays outside
    the branch (ADR-469)."""
    src = WEB_WALL.read_text()
    promise = "You will return here next time you sign in."
    assert src.count(promise) == 1
    before = src[:src.index(promise)].splitlines()
    assert "status?.tier === 'field'" in before[-2], "the promise escaped the field branch"
