"""Per-role MFA enforcement and device trust (ADR-362 phase 2).

Three things are pinned here, each of which fails in a way that is hard to see:

  1. The PreAuthentication trigger runs on EVERY sign-in. If it fails closed on
     an unexpected error it locks the whole company out of a system people
     depend on at 04:00 — including the admin who would fix it.
  2. It must read the invoking pool from the event. Attached to both pools with
     a hardcoded id, it checks the wrong pool's groups.
  3. Enrolment must exist before enforcement. The refusal message names
     "Account > Security"; if that page does not exist the control is a lockout
     with no way out.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRE_AUTH = ROOT / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"
SECURITY_PANEL = ROOT / "frontend" / "src" / "components" / "SecurityPanel.tsx"
ACCOUNT = ROOT / "frontend" / "src" / "pages" / "Account.tsx"
MOBILE_AUTH = ROOT / "mobile" / "src" / "contexts" / "AuthContext.tsx"
TOKEN_REFRESH = ROOT / "mobile" / "src" / "api" / "tokenRefresh.ts"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} is missing — re-pin this test"
    return p.read_text(errors="ignore")


class TestPreAuthFailsOpen:
    def test_an_unexpected_error_allows_the_sign_in(self):
        src = _read(PRE_AUTH)
        assert "return event" in src.split("except Exception")[-1], (
            "an unexpected error must allow the sign-in; failing closed here "
            "locks out every user including the admin who would fix it"
        )

    def test_the_deliberate_refusal_still_raises(self):
        """Fail-open must not swallow the refusal it exists to make."""
        src = _read(PRE_AUTH)
        tail = src.split("except Exception")[-1]
        assert "raise" in tail and "ENROL_HINT" in tail, (
            "the explicit refusal is swallowed by the fail-open handler"
        )

    def test_a_field_role_is_never_gated(self):
        src = _read(PRE_AUTH)
        assert "if not (groups & PRIVILEGED_GROUPS):" in src, (
            "field roles must pass without a factor"
        )

    def test_privileged_groups_cover_every_cross_tenant_role(self):
        src = _read(PRE_AUTH)
        for g in ("super_admin", "admin", "management", "dispatch", "platform_support"):
            assert f'"{g}"' in src, f"{g} can reach tenant data but is not gated"


class TestPreAuthIsNotPinnedToOnePool:
    def test_the_pool_comes_from_the_event(self):
        src = _read(PRE_AUTH)
        assert 'event.get("userPoolId")' in src, (
            "attached to both pools, an env-pinned id checks the wrong one"
        )
        assert not re.search(r'os\.environ\[["\']USER_POOL_ID', src), (
            "the handler still reads a hardcoded pool id"
        )


class TestEnrolmentExistsBeforeEnforcement:
    def test_the_security_panel_exists(self):
        src = _read(SECURITY_PANEL)
        assert "setUpTOTP" in src and "verifyTOTPSetup" in src, (
            "no TOTP enrolment path"
        )
        assert "updateMFAPreference" in src, (
            "enrolling without setting a preference registers a factor that is "
            "never challenged — it looks like MFA and is not"
        )

    def test_it_is_reachable_from_the_account_page(self):
        """The refusal message sends people to Account > Security."""
        src = _read(ACCOUNT)
        assert "SecurityPanel" in src, "the panel is not mounted anywhere"

    def test_the_secret_is_shown_beside_the_qr(self):
        """A desktop authenticator, or a camera that will not focus in a dim
        warehouse, needs a string to paste."""
        src = _read(SECURITY_PANEL)
        assert "sharedSecret" in src, "no manual-entry key alongside the QR"


class TestMobileUsesTheSharedProtocol:
    def test_sign_in_goes_through_amplify(self):
        """A remembered device returns DEVICE_SRP_AUTH, not tokens. Hand-rolling
        SRP-6a in JS is security crypto we would own and get wrong."""
        src = _read(MOBILE_AUTH)
        assert "amplifySignIn" in src, "mobile still hand-rolls InitiateAuth"
        assert "rememberDevice" in src, (
            "without rememberDevice a field user is challenged on every sign-in"
        )

    def test_remember_device_cannot_fail_the_sign_in(self):
        src = _read(MOBILE_AUTH)
        # The CALL, not the import: a bare index() finds the import list first.
        idx = src.index("await rememberDevice()")
        window = src[idx - 200: idx + 200]
        assert "try {" in window and "catch" in window, (
            "a failed rememberDevice must cost an extra prompt, never a blocked "
            "sign-in"
        )

    def test_a_missing_refresh_token_asks_amplify_before_signing_out(self):
        """Amplify keeps the refresh token in its own storage and never hands it
        out, so an absent key does NOT mean signed out."""
        src = _read(TOKEN_REFRESH)
        idx = src.index("if (!refreshToken)")
        window = src[idx: idx + 900]
        assert "fetchAuthSession" in window, (
            "clearing here signs a walker out roughly an hour into their shift"
        )
        assert window.index("fetchAuthSession") < window.index("clearTokens"), (
            "clearTokens runs before Amplify is asked"
        )
