"""Both clients can answer a Cognito challenge (ADR-362).

The pool config lives in AWS and cannot be asserted from a test that has no
credentials, so what is pinned here is the CLIENT side: the code paths that
were missing when MFA was enabled.

The mobile bug these guard against was live before any MFA work. Cognito
returns EITHER `AuthenticationResult` OR a `ChallengeName`, never both, and the
client read the former unconditionally:

    const { AuthenticationResult } = data;
    await storeTokens(AuthenticationResult);            // undefined
    const base = buildUserFromToken(AuthenticationResult.IdToken);  // TypeError

So a field user issued a temporary password got "undefined is not an object"
instead of a prompt to set one.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MOBILE_AUTH = ROOT / "mobile" / "src" / "contexts" / "AuthContext.tsx"
MOBILE_LOGIN = ROOT / "mobile" / "src" / "screens" / "Auth" / "LoginScreen.tsx"
WEB_LOGIN = ROOT / "frontend" / "src" / "components" / "auth" / "Login.tsx"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} moved — re-pin this test"
    return p.read_text(errors="ignore")


class TestMobileHandlesAChallenge:
    """Phase 2 moved mobile onto Amplify, so these pin the BEHAVIOUR rather than
    the raw protocol.

    The original bug — reading `AuthenticationResult` before checking for a
    `ChallengeName`, and so throwing a TypeError on the temporary-password step
    — is now structurally impossible: Amplify returns `isSignedIn` plus a
    `nextStep` and never hands back a half-parsed response. What still has to
    hold is that every challenge reaches the user as a prompt instead of an
    error, which is what these assert.
    """

    def test_a_challenge_is_never_treated_as_a_completed_sign_in(self):
        src = _read(MOBILE_AUTH)
        idx = src.index("const signIn = useCallback")
        window = src[idx: idx + 900]
        # Presence is not enough: an unguarded `return adoptSession()` leaves
        # `res.isSignedIn` sitting further down the function and a substring
        # check still passes. Pin the GUARD, and that it precedes the adoption.
        assert "if (res.isSignedIn) return adoptSession();" in window, (
            "sign-in must adopt a session ONLY when Amplify says it completed; "
            "an unguarded adoptSession() swallows every challenge"
        )
        assert window.index("res.isSignedIn") < window.index("adoptSession()"), (
            "the session is adopted before the completion check"
        )
        assert "toChallenge(res.nextStep" in window, (
            "a nextStep must become a challenge the login screen can render"
        )

    def test_an_unknown_step_is_an_error_not_a_silent_success(self):
        src = _read(MOBILE_AUTH)
        idx = src.index("const signIn = useCallback")
        window = src[idx: idx + 1100]
        assert "throw new Error" in window, (
            "an unrecognised sign-in step must say so rather than falling "
            "through as if signed in"
        )

    def test_a_session_without_tokens_is_an_error_not_a_crash(self):
        src = _read(MOBILE_AUTH)
        assert "tokens?.idToken?.toString()" in src, (
            "optional chaining is what stops a property-of-undefined crash"
        )
        idx = src.index("const adoptSession")
        assert "throw new Error" in src[idx: idx + 700], (
            "an empty session must raise a readable error"
        )

    def test_every_mfa_step_maps_to_a_prompt(self):
        """The four Amplify steps that must reach the user, not an error box."""
        src = _read(MOBILE_AUTH)
        for step in (
            "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED",
            "CONFIRM_SIGN_IN_WITH_TOTP_CODE",
            "CONFIRM_SIGN_IN_WITH_EMAIL_CODE",
            "CONTINUE_SIGN_IN_WITH_MFA_SELECTION",
        ):
            assert step in src, f"{step} has no mapping, so it surfaces as an error"

    def test_the_login_screen_prompts_instead_of_erroring(self):
        src = _read(MOBILE_LOGIN)
        assert "respondToChallenge" in src, "the screen never answers a challenge"
        assert "setChallenge" in src, "the screen has no challenge state"


class TestWebHandlesAChallenge:
    def test_the_dead_end_catch_all_is_gone(self):
        """It rendered `Action required: CONFIRM_SIGN_IN_WITH_TOTP_CODE` — a
        correct string and an unusable screen."""
        src = _read(WEB_LOGIN)
        # Comments may still describe the old behaviour; what matters is that no
        # JSX/string expression renders it. Strip comments before asserting.
        code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        assert "Action required:" not in code, (
            "the catch-all still surfaces a raw signInStep with no way forward"
        )

    def test_each_mfa_step_is_handled(self):
        src = _read(WEB_LOGIN)
        for step in (
            "CONFIRM_SIGN_IN_WITH_TOTP_CODE",
            "CONFIRM_SIGN_IN_WITH_EMAIL_CODE",
            "CONTINUE_SIGN_IN_WITH_MFA_SELECTION",
            "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED",
        ):
            assert step in src, f"{step} is not handled"

    def test_a_one_time_code_is_not_masked(self):
        """Masking a 6-digit code stops the user checking what they typed, and
        blocks the browser/iOS one-time-code autofill."""
        src = _read(WEB_LOGIN)
        assert "'one-time-code'" in src, "the code field has no autoComplete hint"
        assert "isNewPassword ? (showNewPassword" in src, (
            "the field masks every challenge, not just the password one"
        )


class TestTheLambdaIsNotPinnedToOnePool:
    """The PreSignUp trigger now runs for BOTH pools (ADR-362 D4).

    It read the pool id from its environment, pinned to staging. Attached to
    prod as well, that means a prod federated sign-in has its email checked
    against STAGING's user list: anyone with a staging account is admitted to
    prod, and a legitimate prod user is refused.
    """

    def test_the_pool_comes_from_the_event(self):
        src = _read(ROOT / "infra" / "lambda" / "cognito-pre-signup" / "handler.py")
        assert 'event.get("userPoolId")' in src, (
            "the handler still trusts an environment variable for the pool id"
        )
        assert not re.search(r"UserPoolId=POOL_ID\b", src), (
            "list_users still queries the hardcoded pool"
        )

    def test_no_pool_fails_closed(self):
        src = _read(ROOT / "infra" / "lambda" / "cognito-pre-signup" / "handler.py")
        idx = src.index("def _native_user_exists")
        assert "if not pool_id:" in src[idx: idx + 300], (
            "a missing pool id must block, not fall through to a lookup"
        )
