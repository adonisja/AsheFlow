"""The authenticator setup key is opened or copied, never retyped (ADR-557).

Owner, 2026-10-21: "writing it down causes a lot of errors". A phone can't
scan its own screen, so on mobile the 32-character key is the enrolment path,
and a mistyped character gives codes that never match with nothing to say why.

The URI and grouping are unit-tested by Jest
(mobile/src/components/__tests__/setupKeyFormat.test.ts), which CI does NOT
run; these pin the wiring, which it does.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
M_KEY = ROOT / "mobile/src/components/SetupKey.tsx"
M_FMT = ROOT / "mobile/src/components/setupKeyFormat.ts"
W_KEY = ROOT / "frontend/src/components/auth/SetupKey.tsx"


@pytest.mark.parametrize("path", [
    ROOT / "mobile/src/components/MfaEnrolment.tsx",
    ROOT / "mobile/src/screens/Auth/LoginScreen.tsx",
    ROOT / "frontend/src/components/auth/Login.tsx",
    ROOT / "frontend/src/components/SecurityPanel.tsx",
], ids=["mobile-wall", "mobile-signin", "web-signin", "web-security-panel"])
def test_every_place_the_key_appears_uses_the_component(path):
    src = path.read_text()
    assert "<SetupKey secret=" in src
    # The old bare displays are gone: a selectable Text or <code> of the raw key.
    assert "{secret}</Text>" not in src and "{challenge.totpSecret}\n" not in src
    assert "{totpSecret}\n" not in src and "{setupSecret}\n" not in src


def test_mobile_opens_the_key_in_the_authenticator():
    src = M_KEY.read_text()
    assert "Linking.openURL(otpauthUri(secret, account))" in src
    # openURL's rejection is the signal; canOpenURL needs per-platform
    # scheme declarations and answers "no" without them.
    assert "Linking.canOpenURL" not in src
    assert "setNoApp(true)" in src


def test_mobile_copies_the_raw_key_and_clears_it_later():
    src = M_KEY.read_text()
    assert "const raw = rawKey(secret);" in src and "Clipboard.setString(raw)" in src
    clear = src[src.index("CLEAR_AFTER_MS))") - 300: src.index("CLEAR_AFTER_MS))")]
    assert "=== raw" in clear and "Clipboard.setString('')" in clear, \
        "only clear the clipboard if it still holds OUR key"


def test_the_uri_is_the_standard_key_uri_format():
    src = M_FMT.read_text()
    assert re.search(r"otpauth://totp/\$\{label\}\?secret=\$\{encodeURIComponent\(rawKey\(secret\)\)\}&issuer=", src)


def test_web_copies_without_the_display_spacing():
    src = W_KEY.read_text()
    assert "navigator.clipboard.writeText(secret.replace(/\\s+/g, ''))" in src
    assert "<a href={uri}" in src, "the same otpauth link the QR encodes"


@pytest.mark.parametrize("path", [ROOT / "mobile/src/screens/MfaRequiredScreen.tsx",
                                  ROOT / "frontend/src/pages/MfaRequired.tsx"], ids=["mobile", "web"])
def test_the_wall_points_at_the_request_not_an_administrator(path):
    """Since ADR-551 every account kind can request a reset from the sign-in
    screen, and surveyors have no administrator."""
    src = path.read_text()
    assert "an administrator will need to reset your setup" not in src
    assert src.count("request a reset from the sign-in screen") == 2


def test_email_codes_stay_reachable_from_the_authenticator_screen():
    """Owner, 2026-10-21: "it removed the 'Email me a code' option". It hadn't:
    the way back was a link under the code field, and the taller key block plus
    an auto-focused keyboard pushed it out of view. Email is the option for
    anyone who doesn't want an authenticator app, so it must stay visible."""
    src = (ROOT / "mobile/src/components/MfaEnrolment.tsx").read_text()
    key_view = src[src.index("if (secret) {"): src.index("</ScrollView>", src.index("if (secret) {"))]
    assert "Use email codes instead" in key_view
    assert key_view.index("Use email codes instead") < key_view.index("<SetupKey"), \
        "the switch sits above the key block, where nothing can push it off screen"
    assert "autoFocus" not in key_view.replace("No autoFocus", ""), \
        "no code exists until the key is added; an open keyboard hid the screen"
    # And the choice screen still leads with email.
    assert src.index("Email me a code each sign-in") > src.index("</ScrollView>", src.index("if (secret) {"))
