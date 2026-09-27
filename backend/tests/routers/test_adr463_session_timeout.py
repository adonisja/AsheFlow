"""Every session ends, and the two tiers end differently (ADR-463).

The frontend has no test runner (ADR-311), so the policy is asserted here
against the module's source. The arithmetic itself is exercised by a runtime
probe in the journal; these pin the VALUES and the wiring, which are what drift.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
POLICY = ROOT / "frontend/src/utils/sessionPolicy.ts"
HOOK = ROOT / "frontend/src/hooks/useSessionTimeout.ts"
APP = ROOT / "frontend/src/App.tsx"
LOGIN = ROOT / "frontend/src/components/auth/Login.tsx"
MOBILE_TOKENS = ROOT / "mobile/src/api/tokenRefresh.ts"


def test_privileged_is_twelve_hours_and_thirty_minutes():
    src = POLICY.read_text()
    m = re.search(r"const PRIVILEGED: SessionLimits = \{([^}]+)\}", src)
    assert m, "PRIVILEGED limits not found"
    assert "12 * HOUR" in m.group(1), "privileged absolute cap is not 12h"
    assert "30 * MINUTE" in m.group(1), "privileged idle cap is not 30min"


def test_field_is_a_day_with_no_idle_clock():
    """A 30-minute idle timer would sign a walker out between two buildings."""
    src = POLICY.read_text()
    m = re.search(r"const FIELD: SessionLimits = \{([^}]+)\}", src)
    assert m, "FIELD limits not found"
    assert "24 * HOUR" in m.group(1), "field absolute cap is not 24h"
    assert "idleMs: null" in m.group(1), "field tier has an idle clock"


def test_the_privileged_set_matches_the_preauth_trigger():
    """Borrowing employees.py's shorter PRIVILEGED_ROLES would put a super
    admin on the field tier's looser clock -- the opposite of intended."""
    policy = POLICY.read_text()
    # Parse the ARRAY, not a character window: the declaration is preceded by a
    # doc comment, and a fixed-width slice silently matched nothing -- which
    # made the test compare an empty set and fail for the wrong reason.
    array = policy.split("export const PRIVILEGED_GROUPS = [")[1].split("]")[0]
    listed = set(re.findall(r"'([a-z_]+)'", array))
    trigger = (ROOT / "infra/lambda/cognito-pre-auth/handler.py").read_text()
    expected = set(re.findall(r'"([a-z_]+)",', trigger.split("PRIVILEGED_GROUPS = {")[1].split("}")[0]))
    assert listed == expected, f"client {listed} != trigger {expected}"


def test_the_absolute_clock_is_anchored_to_auth_time():
    """Anchoring to page load restarts the clock on every refresh, which is
    what makes an absolute timeout decorative."""
    assert "auth_time" in HOOK.read_text()


def test_a_missing_auth_time_does_not_end_the_session():
    """An unexpected token shape must not sign everyone out."""
    src = POLICY.read_text()
    m = re.search(r"export function expiryReason\(.*?\n\}", src, re.S)
    assert m, "expiryReason not found"
    assert "authTimeMs !== null &&" in m.group(0), (
        "a null auth_time would be treated as an expired session"
    )


def test_the_hook_is_mounted_behind_authentication():
    src = APP.read_text()
    assert "SessionGuard" in src and "useSessionTimeout" in src, "the hook has no caller"
    assert "<SessionGuard>{children}</SessionGuard>" in src, (
        "SessionGuard does not wrap the protected tree"
    )


def test_an_idle_signout_is_warned_before_it_happens():
    """A session that vanishes silently reads as a crash."""
    assert "WARN_BEFORE_MS" in HOOK.read_text()
    assert "Stay signed in" in APP.read_text()


def test_the_login_screen_says_why_the_session_ended():
    src = LOGIN.read_text()
    assert "sessionEnded" in src
    for reason in ("idle", "absolute"):
        assert f"'{reason}'" in src, f"the {reason} case is not explained"


def test_activity_writes_are_throttled_not_discarded():
    """The throttle bounds how often the timestamp is refreshed, never whether
    activity counts. Discarding events inside the window leaves lastActivity
    stale, so a user who is active could still be signed out."""
    src = HOOK.read_text()
    assert "ACTIVITY_THROTTLE_MS" in src
    m = re.search(r"const ACTIVITY_THROTTLE_MS = ([^;]+);", src)
    assert m, "throttle constant not found"
    # Must be far below the 30-minute idle cap, or the coalescing window itself
    # becomes a meaningful slice of the clock it is protecting.
    #
    # Evaluated, not substring-matched: `"1000" in "30 * 1000"` is trivially
    # true, so the first version of this assertion passed on a 30x-too-coarse
    # value -- caught only by probing it.
    expr = m.group(1).strip()
    assert re.fullmatch(r"[\d\s*]+", expr), f"unexpected throttle expression: {expr}"
    ms = eval(expr)  # noqa: S307 - digits and '*' only, guarded above
    assert ms <= 5_000, f"throttle is {ms}ms; activity precision is too coarse"


def test_reading_counts_as_activity():
    """Scrolling a long dispatch table without clicking is not idleness.

    A pointerdown/keydown-only list signs out the reader mid-page.
    """
    src = HOOK.read_text()
    events = src.split("const ACTIVITY_EVENTS = [")[1].split("]")[0]
    for needed in ("scroll", "pointermove", "wheel", "touchstart"):
        assert needed in events, f"{needed} is not treated as activity"


def test_activity_clears_a_visible_warning():
    """Making a demonstrably-present user click 'Stay signed in' is theatre."""
    assert "setIdleWarningSeconds(prev =>" in HOOK.read_text()


# ── D6: mobile ──────────────────────────────────────────────────────────────

def test_mobile_has_an_absolute_session_cap():
    """The inactivity window alone bounds nothing for a daily user: a walker
    who opens the app each morning refreshes forever."""
    src = MOBILE_TOKENS.read_text()
    m = re.search(r"ABSOLUTE_SESSION_LIMIT_MS = ([^;]+);", src)
    assert m, "mobile has no absolute session cap"
    assert "24 * 60 * 60 * 1000" in m.group(1), f"cap is {m.group(1).strip()}, not 24h"


def test_mobile_checks_the_cap_before_the_freshness_shortcut():
    """getValidIdToken returns a still-valid token unexamined. Testing the cap
    after that lets a session outlive the limit by up to the token's full hour.
    """
    src = MOBILE_TOKENS.read_text()
    body = src.split("export async function getValidIdToken")[1]
    cap = body.index("isPastAbsoluteLimit")
    fresh = body.index("tokenExpiresAt(idToken) - Date.now()")
    assert cap < fresh, "the absolute cap is checked after the freshness shortcut"


def test_mobile_anchors_on_auth_time_not_issue_time():
    """A refresh mints a token with a new `iat`; anchoring there restarts the
    clock on every refresh and the cap never fires."""
    src = MOBILE_TOKENS.read_text()
    fn = src.split("export function isPastAbsoluteLimit")[1].split("\n}")[0]
    assert "tokenAuthTime" in fn
    assert "iat" not in fn


def test_a_missing_auth_time_does_not_strand_a_walker():
    """An unexpected token shape must not sign someone out mid-route."""
    src = MOBILE_TOKENS.read_text()
    fn = src.split("export function isPastAbsoluteLimit")[1].split("\n}")[0]
    assert "if (!authTime) return false;" in fn


def test_mobile_does_not_carry_the_privileged_tier():
    """The app is walkers, drivers, captains and field supervisors. Importing
    the 12h/30min rule would sign a walker out mid-shift for a threat this app
    does not run (ADR-463 D6)."""
    src = MOBILE_TOKENS.read_text()
    assert "30 * 60 * 1000" not in src, "mobile has picked up the 30-minute idle rule"
