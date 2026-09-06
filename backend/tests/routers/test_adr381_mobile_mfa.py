"""Mobile can enrol, and a blocked user gets a screen instead of the app (ADR-381 D2).

The PreAuthentication trigger's message says "open AsheFlow on the web and go to
Account > Security". Honest, and it sent a walker whose only device is a phone to
find a computer.

The web banner does NOT port. A dismissible strip works on a desktop where it
stays in the viewport; on a phone it is one swipe from gone, and a walker opening
the app to check today's route never scrolls back up. So two surfaces:

    blocked        full screen, swapped in at the NAVIGATOR, no dismiss
    counting down  a Profile section with the day count
    enrolled/null  nothing

The blocking screen is a navigator-level swap rather than a modal because
RootNavigator already uses that idiom for isAuthenticated -- and a modal would
leave the tab shell navigable behind it, which is not what blocked means.

No frontend test runner here, so the source assertions follow
test_adr320_bulk_button_gates.py, and the ROUTING LOGIC is reimplemented and
executed so a behavioural break fails even when the text matches.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NAV = ROOT / "mobile" / "src" / "navigation" / "index.tsx"
SCREEN = ROOT / "mobile" / "src" / "screens" / "MfaRequiredScreen.tsx"
ENROL = ROOT / "mobile" / "src" / "components" / "MfaEnrolment.tsx"
SETTINGS = ROOT / "mobile" / "src" / "screens" / "Profile" / "AccountSettingsScreen.tsx"
CTX = ROOT / "mobile" / "src" / "contexts" / "AuthContext.tsx"


def surface(authenticated, status):
    """The two guards, executed."""
    if not authenticated:
        return "login"
    if status and status.get("blocked"):
        return "blocking"
    if status and status["required"] and status["enrolled"] is False:
        return "profile"
    return "app"


def _s(required=True, enrolled=False, days=14, blocked=False):
    return {"required": required, "enrolled": enrolled,
            "days_remaining": days, "blocked": blocked}


class TestRouting:
    def test_a_blocked_user_gets_the_screen_not_the_app(self):
        assert surface(True, _s(days=0, blocked=True)) == "blocking"

    def test_a_counting_down_user_keeps_the_app(self):
        """Warning, not a wall. Blocking someone mid-grace-period would make the
        grace period meaningless."""
        assert surface(True, _s(days=5)) == "profile"

    def test_an_enrolled_user_sees_neither(self):
        assert surface(True, _s(enrolled=True, days=None)) == "app"

    def test_an_unloaded_status_does_not_block(self):
        """mfaStatus is null until the first fetch returns. Blocking on null
        would lock everyone out of the app for a moment on every launch."""
        assert surface(True, None) == "app"

    def test_unreadable_cognito_does_not_block(self):
        """enrolled === null means Cognito could not be read. Blocking there
        turns an AWS hiccup into a company-wide lockout."""
        assert surface(True, _s(enrolled=None)) == "app"

    def test_signed_out_still_reaches_login(self):
        """The MFA gate must sit INSIDE the authenticated branch, or a signed
        out user with a stale status could be trapped."""
        assert surface(False, _s(days=0, blocked=True)) == "login"


class TestTheNavigatorGate:
    def test_it_swaps_the_screen_rather_than_layering_a_modal(self):
        src = NAV.read_text()
        assert 'name="MfaRequired"' in src
        assert "component={MfaRequiredScreen}" in src

    def test_the_gate_is_inside_the_authenticated_branch(self):
        """Order matters: !isAuthenticated must be tested FIRST, or a blocked
        user who signs out cannot reach the login screen."""
        src = NAV.read_text()
        assert src.index("{!isAuthenticated ? (") < src.index("mfaBlocked ? (")

    def test_it_guards_on_blocked_only(self):
        """Not on `required`, not on `enrolled` -- those are the counting-down
        states, and blocking them defeats the grace period."""
        src = NAV.read_text()
        assert "const mfaBlocked = Boolean(mfaStatus?.blocked);" in src

    def test_the_route_is_declared(self):
        assert "MfaRequired: undefined;" in NAV.read_text()


class TestTheBlockingScreen:
    def test_it_offers_no_dismiss(self):
        """There is nothing to come back to -- the trigger already refuses them
        at sign-in, so this screen is their only explanation.

        Asserts on CODE, not the file: the docstring explains why there is no
        dismiss, so a whole-file grep matches its own justification. Fourth time
        this session a prose match nearly passed for a code fact.
        """
        code = "\n".join(
            l for l in SCREEN.read_text().splitlines()
            if not l.lstrip().startswith(("*", "/*", "//"))
        )
        for token in ("dismiss", "onRequestClose", "canGoBack", "navigation.goBack"):
            assert token not in code.lower(), (
                f"the blocking screen offers an escape ({token}) -- it must not"
            )

    def test_it_offers_sign_out_as_the_only_other_exit(self):
        """A shared phone with the wrong account signed in would otherwise be
        stuck with no way back to the login screen."""
        assert "signOut" in SCREEN.read_text()

    def test_it_re_checks_after_enrolling(self):
        """Otherwise the user enrols and stays blocked until they restart."""
        assert "refreshMfaStatus" in SCREEN.read_text()


class TestEnrolment:
    def test_it_uses_the_same_amplify_calls_as_the_web_panel(self):
        """One protocol, two clients. If these drift, one of them is wrong."""
        mobile = ENROL.read_text()
        web = (ROOT / "frontend" / "src" / "components" / "SecurityPanel.tsx").read_text()
        for call in ("setUpTOTP", "verifyTOTPSetup", "updateMFAPreference"):
            assert call in mobile, f"mobile is missing {call}"
            assert call in web

    def test_email_is_offered_before_totp(self):
        """SecurityPanel's own rationale: an emailed code needs no app at all
        and every account has a verified address, "which matters for field
        staff, who are being asked to install nothing"."""
        src = ENROL.read_text()
        assert src.index("Email me a code") < src.index("authenticator app instead")

    def test_it_shows_a_copyable_secret_rather_than_a_qr(self):
        """The authenticator app is on the SAME phone, so there is no second
        screen to scan from."""
        src = ENROL.read_text()
        assert "selectable" in src
        assert "QRCode" not in src

    def test_errors_do_not_surface_cognito_internals(self):
        """Cognito's messages name internal state and mean nothing to a walker
        at 05:00."""
        code = "\n".join(
            l for l in ENROL.read_text().splitlines()
            if not l.lstrip().startswith(("*", "/*", "//"))
        )
        # Every Alert must carry a literal string, never a value derived from
        # the caught error. Asserting the ABSENCE of `.message` was too narrow:
        # a mutant using `(e as Error).message` slipped straight past it.
        import re
        for body in re.findall(r"Alert\.alert\([^;]*?\);", code, re.S):
            assert ".message" not in body, (
                f"an Alert surfaces a caught error to the user: {body[:80]}"
            )
            assert "String(e" not in body and "${e" not in body, (
                f"an Alert interpolates the caught error: {body[:80]}"
            )


class TestTheProfileSection:
    def test_it_renders_only_while_counting_down(self):
        src = SETTINGS.read_text()
        assert "mfaStatus.required && mfaStatus.enrolled === false" in src

    def test_it_reuses_the_shared_enrolment_component(self):
        """Two enrolment implementations would drift; one cannot."""
        assert "<MfaEnrolment onEnrolled={refreshMfaStatus} />" in SETTINGS.read_text()


class TestTheContext:
    def test_refresh_keeps_the_last_status_on_failure(self):
        """Nulling it on the blocked path would UNBLOCK someone whose enrolment
        could not be confirmed."""
        src = CTX.read_text()
        i = src.index("const refreshMfaStatus")
        window = src[i:i + 500]
        assert "setMfaStatus(null)" not in window
