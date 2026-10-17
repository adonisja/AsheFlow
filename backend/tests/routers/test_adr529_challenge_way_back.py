"""A sign-in challenge has a way back (ADR-529).

Owner, prod: "Enter your code" had no exit. The only control was the submit
button, and nothing ever set challengeStep back to null. Mobile has had
"Start over" since ADR-362; the web never did.

Source-inspecting, like test_adr479: there is no frontend test runner, so
these pin the shape of the code. Each slice is taken from code, not from the
comments around it, so prose cannot satisfy an assertion.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
LOGIN = ROOT / "frontend/src/components/auth/Login.tsx"
MOBILE = ROOT / "mobile/src/screens/Auth/LoginScreen.tsx"


def _src() -> str:
    return LOGIN.read_text()


def _back_fn() -> str:
    s = _src()
    i = s.index("const backToSignIn = () => {")
    return s[i:s.index("};", i)]


def _back_button() -> str:
    """The <button> whose handler is backToSignIn, tag to close."""
    s = _src()
    i = s.index("onClick={backToSignIn}")
    start = s.rindex("<button", 0, i)
    return s[start:s.index("</button>", i)]


def test_every_challenge_step_renders_the_way_back():
    """Gated on challengeStep alone, so no step can be left without it."""
    s = _src()
    i = s.index("onClick={backToSignIn}")
    guard = s[s.rindex("{", 0, s.rindex("<button", 0, i)) : i]
    assert re.search(r"\{challengeStep && \(", guard), guard
    assert "Back to sign in" in _back_button()


def test_it_is_a_plain_button_not_a_submit():
    """Inside the <form>: a missing type would submit the challenge instead."""
    assert 'type="button"' in _back_button()


def test_it_cannot_fire_while_a_submit_is_in_flight():
    """ADR-529 D2 -- backing out mid-confirm recreates the ADR-479 flash."""
    assert "disabled={submitting}" in _back_button()


def test_it_clears_everything_the_challenge_put_on_screen():
    body = _back_fn()
    for setter in (
        "setChallengeStep(null)", "setNewPassword('')", "setPassword('')",
        "setMfaOptions([])", "setTotpSetupUri(null)", "setTotpSecret('')",
        "setTotpQr('')", "setError('')", "setSuccessMsg('')",
    ):
        assert setter in body, f"backToSignIn does not reset: {setter}"


def test_it_keeps_the_username():
    """A retry or a typo fix is one field away, same as mobile."""
    assert "setUsername" not in _back_fn()


def test_it_does_not_pretend_to_sign_out():
    """ADR-529 D4: signOut() does not clear Amplify's sign-in store, so calling
    it would imply a cleanup that does not happen."""
    assert "signOut" not in _back_fn()


def test_the_idle_notice_is_hidden_during_a_challenge():
    """ADR-529 D3: in red over a code field it reads as this attempt failing."""
    assert "{sessionEnded && !challengeStep && (" in _src()


def test_mobile_still_has_its_way_back():
    """Parity: the web copied this from mobile; don't let mobile lose it."""
    assert re.search(r"onPress=\{\(\) => \{ setChallenge\(null\);", MOBILE.read_text())
