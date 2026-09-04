"""Clearing a day with no Discord posts is not a Discord failure (ADR-367).

`discord_cleared` started as False and only became True after a successful bot
call -- but the call is skipped entirely when there are no message ids to
retract. So clearing a day that was never published to Discord reported:

    "The day was cleared, but Discord could not be reached.
     Crew posts may still be visible there."

Nothing had gone wrong. Verified on staging when this was found: no bot request
attempted, no error on either side, no alert_admins_integration_down.

Why it is worth a test rather than a one-line fix: the warning exists (ADR-328
D5) because a clear CAN succeed in the database while leaving crew posts
standing, and the crew reads Discord. Firing it on every unpublished day teaches
dispatchers to dismiss it, so the real one gets dismissed too.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUTER = ROOT / "backend" / "app" / "routers" / "dispatch.py"
PAGE = ROOT / "frontend" / "src" / "pages" / "DispatchDashboard.tsx"


def _clear_source() -> str:
    tree = ast.parse(ROUTER.read_text(errors="ignore"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "clear_daily_dispatch"
    )
    return ast.unparse(fn)


class TestTheFlagHasThreeStates:
    def test_it_starts_as_none_not_false(self):
        """False at the top is indistinguishable from a failed call, because
        the call may never happen."""
        src = _clear_source()
        assert re.search(r"discord_cleared:\s*bool\s*\|\s*None\s*=\s*None", src), (
            "discord_cleared must start as None -- 'never asked' is not 'failed'"
        )

    def test_false_is_set_only_once_the_bot_is_actually_called(self):
        """False must mean 'we asked and it did not work'. Setting it before the
        _has_messages branch restores the original bug."""
        src = _clear_source()
        i = src.index("if _has_messages:")
        window = src[i: i + 400]
        assert "discord_cleared = False" in window, (
            "False is not set inside the branch that calls the bot, so it either "
            "never means 'failed' or means it too early"
        )
        # And it must NOT also be set before the branch.
        assert "discord_cleared = False" not in src[:i], (
            "discord_cleared is set False before the bot call, which is the "
            "original defect"
        )

    def test_true_still_requires_a_successful_call(self):
        src = _clear_source()
        i = src.index("discord_cleared = True")
        window = src[max(0, i - 300): i]
        assert "status == 200" in window, (
            "True must require a 200 from the bot, not merely reaching the call"
        )


class TestTheFrontendDistinguishesNullFromFalse:
    def test_it_compares_explicitly(self):
        """null is falsy. `if (!discord_cleared)` would warn on every clear of
        an unpublished day -- the exact bug, reintroduced by a tidy-up."""
        page = PAGE.read_text(errors="ignore")
        assert "discord_cleared === false" in page, (
            "the warning must key on an explicit === false"
        )
        assert not re.search(r"if\s*\(\s*!\s*res\.data\??\.discord_cleared", page), (
            "a falsy check on a three-state field reintroduces the bug"
        )

    def test_the_reason_is_recorded_at_the_call_site(self):
        """Whoever simplifies this next needs the reason in front of them."""
        page = PAGE.read_text(errors="ignore")
        i = page.index("discord_cleared === false")
        window = page[max(0, i - 500): i]
        assert "ADR-367" in window, (
            "no note explaining why the comparison cannot be simplified"
        )


class TestTheTypeScriptTypeMatches:
    """types.ts is hand-maintained with no codegen (CLAUDE.md Dimension 9), so a
    backend type change drifts silently. Here it declared `boolean` while the
    API returned null -- TypeScript would have rejected a legitimate `=== null`
    check while happily allowing the falsy test that causes the bug.
    """

    def test_the_field_is_nullable_in_types_ts(self):
        types = (ROOT / "frontend" / "src" / "api" / "types.ts").read_text(errors="ignore")
        i = types.index("interface ClearDispatchResponse")
        window = types[i: i + 900]
        assert re.search(r"discord_cleared:\s*boolean\s*\|\s*null", window), (
            "types.ts still declares discord_cleared as a plain boolean; the API "
            "returns null when there was nothing to retract"
        )
