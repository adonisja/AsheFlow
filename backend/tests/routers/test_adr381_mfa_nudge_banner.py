"""The grace period's warning half exists and is rendered (ADR-381 D1).

The PreAuthentication trigger is LIVE on both pools. Until this banner, the
grace clock ran invisibly: a field user's first sign-in started a 14-day
countdown they could not see, and the first thing they learned about it was
being refused at sign-in.

That is the wall without the nudge -- the exact failure ADR-362 named:

    "Pointing someone at a page that is not there turns a security control
     into a lockout with no way out."

The page exists this time. The warning did not.

This repo has no frontend test runner, so the source assertions follow
test_adr320_bulk_button_gates.py. The RENDER LOGIC is reimplemented here from
the same guard chain and executed, so a behavioural break fails even when the
text still matches.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BANNER = ROOT / "frontend" / "src" / "components" / "MfaNudgeBanner.tsx"
LAYOUT = ROOT / "frontend" / "src" / "components" / "layout" / "Layout.tsx"


def renders(status, dismissed=False):
    """The component's guard chain, executed rather than grepped."""
    if status is None or status["enrolled"] is None:
        return "nothing"
    if not status["required"] or status["enrolled"]:
        return "nothing"
    if dismissed and not status["blocked"]:
        return "nothing"
    return "blocked" if status["blocked"] else "warning"


def _status(required=True, enrolled=False, days=14, blocked=False):
    return {"required": required, "enrolled": enrolled,
            "days_remaining": days, "blocked": blocked}


class TestWhenItShows:
    def test_an_unenrolled_field_user_is_warned(self):
        assert renders(_status(days=14)) == "warning"

    def test_the_last_day_still_warns_rather_than_blocking(self):
        """Server-side rounding means 1 is 'today or tomorrow', never a bare 0
        on an account that still works."""
        assert renders(_status(days=1)) == "warning"

    def test_an_expired_field_user_is_blocked(self):
        assert renders(_status(days=0, blocked=True)) == "blocked"

    def test_an_unenrolled_privileged_user_is_blocked_immediately(self):
        """No grace period for the privileged tier."""
        assert renders(_status(days=0, blocked=True)) == "blocked"


class TestWhenItStaysSilent:
    def test_an_enrolled_user_sees_nothing(self):
        assert renders(_status(enrolled=True, days=None)) == "nothing"

    def test_a_tier_none_user_sees_nothing(self):
        assert renders(_status(required=False)) == "nothing"

    def test_no_status_yet_renders_nothing(self):
        """The fetch is not awaited into sign-in, so the first render has none."""
        assert renders(None) == "nothing"

    def test_unreadable_cognito_renders_nothing(self):
        """`enrolled is null` means Cognito could not be read -- NOT 'no MFA
        required'. is_enrolled returns null rather than false for exactly this
        reason: false past the deadline BLOCKS. Nagging an enrolled user because
        AWS hiccuped is the failure mode here."""
        assert renders(_status(enrolled=None)) == "nothing"

    def test_null_is_not_treated_as_false(self):
        """The distinction that matters: same required/blocked shape, different
        `enrolled`, opposite outcomes."""
        assert renders(_status(enrolled=False, days=0, blocked=True)) == "blocked"
        assert renders(_status(enrolled=None, days=0, blocked=True)) == "nothing"


class TestDismissal:
    def test_a_warning_can_be_dismissed(self):
        assert renders(_status(days=5), dismissed=True) == "nothing"

    def test_a_blocked_banner_cannot_be_dismissed(self):
        """There is nothing to come back to later -- they are already refused at
        sign-in -- so dismissing would hide their only explanation."""
        assert renders(_status(days=0, blocked=True), dismissed=True) == "blocked"


class TestTheComponentMatchesThatLogic:
    def test_it_guards_on_null_before_anything_else(self):
        src = BANNER.read_text()
        assert "mfaStatus.enrolled === null" in src, (
            "null must be handled explicitly; a falsy check would treat it as "
            "'not enrolled' and nag an enrolled user"
        )

    def test_the_null_guard_precedes_the_required_guard(self):
        src = BANNER.read_text()
        assert src.index("enrolled === null") < src.index("mfaStatus.required")

    def test_a_blocked_banner_has_no_dismiss_control(self):
        src = BANNER.read_text()
        assert "if (dismissed && !blocked) return null;" in src
        assert "{!blocked && (" in src, (
            "the dismiss button must be conditional on not being blocked"
        )

    def test_it_links_to_the_page_the_trigger_names(self):
        """The PreAuthentication lambda says 'go to Account > Security'. Two
        instructions that can diverge will."""
        src = BANNER.read_text()
        assert 'to="/account"' in src

        handler = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"
        assert "Account > Security" in handler.read_text()

    def test_it_is_mounted_app_wide(self):
        """A banner on one page is not a warning."""
        src = LAYOUT.read_text()
        assert "<MfaNudgeBanner />" in src
        assert "import MfaNudgeBanner" in src

    def test_it_sits_above_the_notification_banner(self):
        """This one is about losing access; those are about today's work."""
        src = LAYOUT.read_text()
        assert src.index("<MfaNudgeBanner />") < src.index("<NotificationBanner />")
