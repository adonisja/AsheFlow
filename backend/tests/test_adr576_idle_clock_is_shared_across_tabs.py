"""ADR-576: the idle clock reads activity from every tab, not just its own.

One Amplify session is shared by every tab, and signOut() revokes its refresh
token. A per-tab idle clock let a background tab end the session the person was
working in. The frontend has no test runner (ADR-463's file says why), so the
wiring is pinned against the source; the arithmetic was probed at runtime
(journal 2026-10-23).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = (ROOT / "frontend/src/utils/sessionPolicy.ts").read_text()
HOOK = (ROOT / "frontend/src/hooks/useSessionTimeout.ts").read_text()


def _tick_body() -> str:
    return HOOK.split("const tick = setInterval(", 1)[1].split("}, TICK_MS);", 1)[0]


def test_activity_is_written_where_every_tab_can_read_it():
    assert "export const LAST_ACTIVITY_KEY" in POLICY
    mark = HOOK.split("const markActive = () => {", 1)[1].split("};", 1)[0]
    assert "shareActivity(now)" in mark, "markActive must publish activity to the other tabs"
    stay = HOOK.split("staySignedIn: () => {", 1)[1].split("}", 1)[0]
    assert "shareActivity(" in stay, "'Stay signed in' must reach the other tabs too"


def test_the_idle_decision_uses_the_latest_activity_across_tabs():
    tick = _tick_body()
    assert "latestActivity(lastActivity.current, sharedActivity())" in tick
    assert "expiryReason(limits.current, authTime.current, last, now)" in tick
    assert "msUntilIdleSignOut(limits.current, last, now)" in tick
    # The old per-tab read must be gone from the decision.
    assert not re.search(r"expiryReason\([^)]*lastActivity\.current", tick)


def test_storage_failure_falls_back_to_the_tabs_own_clock():
    for fn in ("function shareActivity", "function sharedActivity"):
        body = HOOK.split(fn, 1)[1].split("\n}", 1)[0]
        assert "try" in body and "catch" in body, f"{fn} must not throw when storage is blocked"
    rule = POLICY.split("export function latestActivity", 1)[1]
    assert "shared > ownMs ? shared : ownMs" in rule, "a shared value may only make the session LESS idle"
