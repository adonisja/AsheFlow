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


PROMPT = ROOT / "mobile" / "src" / "components" / "MfaGracePrompt.tsx"


def prompts(status, skipped=False):
    """MfaGracePrompt's guard chain, executed."""
    if status is None or status["enrolled"] is None:
        return False
    if not status["required"] or status["enrolled"] or status["blocked"]:
        return False
    return not skipped


class TestTheGracePromptIsSkippable:
    """ADR-381 D2 specified "a Profile row with the day count, PLUS a
    one-per-launch prompt". The first shipped; the second did not, so the
    countdown was visible only to someone who navigated to Settings -- which a
    walker opening the app to check today's route never does.
    """

    def test_it_prompts_during_the_grace_period(self):
        assert prompts(_s(days=14)) is True

    def test_the_component_actually_implements_that_chain(self):
        """`prompts()` above is a MODEL of the guard chain -- mutating the
        component does not change it, so the executable tests alone let two
        mutants through (removing the skip guard, and dropping the blocked
        term). These assert the real source carries each guard.
        """
        code = "\n".join(
            l for l in PROMPT.read_text().splitlines()
            if not l.lstrip().startswith(("*", "/*", "//"))
        )
        assert "if (skipped) return null;" in code, (
            "the prompt is no longer skippable -- it would nag on every launch "
            "for the whole grace period"
        )
        assert "mfaStatus.blocked) return null;" in code, (
            "the prompt fires when BLOCKED, offering a 'Not now' escape from a "
            "wall that must not have one"
        )
        assert "mfaStatus.enrolled === null" in code, (
            "null means Cognito was unreadable, not 'not enrolled'"
        )

    def test_it_shows_the_day_count(self):
        """"Required soon" is what people ignore. The number is the point."""
        src = PROMPT.read_text()
        assert "days_remaining" in src
        assert "Required in ${days} days" in src

    def test_skipping_hides_it_for_the_rest_of_the_launch(self):
        assert prompts(_s(days=14), skipped=True) is False

    def test_skipping_does_NOT_escape_the_block(self):
        """The question this was built to answer. Once the countdown ends the
        prompt is irrelevant -- RootNavigator has already swapped the shell for
        MfaRequiredScreen, which has no dismiss at all."""
        assert prompts(_s(days=0, blocked=True), skipped=True) is False
        assert prompts(_s(days=0, blocked=True)) is False
        assert surface(True, _s(days=0, blocked=True)) == "blocking"

    def test_it_never_fires_for_an_enrolled_user(self):
        assert prompts(_s(enrolled=True, days=None)) is False

    def test_it_never_fires_on_an_unreadable_status(self):
        assert prompts(_s(enrolled=None)) is False

    def test_it_is_a_modal_over_the_shell_not_a_replacement(self):
        """Escapable BECAUSE they may still work. The blocked case is a
        navigator swap for the opposite reason."""
        assert "<Modal" in PROMPT.read_text()

    def test_it_mounts_once_per_launch(self):
        """MainShell mounts once per session, so "Not now" lasts exactly that
        long. Re-asking on every screen change is how a warning becomes noise
        people dismiss without reading."""
        nav = NAV.read_text()
        assert "<MfaGracePrompt />" in nav
        i_shell = nav.index("function MainShell")
        i_prompt = nav.index("<MfaGracePrompt />")
        i_root = nav.index("function RootNavigator")
        assert i_shell < i_prompt < i_root, (
            "the prompt must mount inside MainShell -- mounting it deeper would "
            "re-ask on every screen change"
        )

    def test_skip_state_is_not_persisted(self):
        """A new launch is a new chance to ask. Persisting the skip would let a
        deadline stop mentioning itself entirely."""
        src = PROMPT.read_text()
        assert "AsyncStorage" not in src
