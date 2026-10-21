"""The mobile app must not render before the MFA answer arrives (ADR-556).

ADR-469 fixed this on web. Mobile kept the fire-and-forget read: `mfaStatus`
was null for the length of /employees/me/mfa-status, RootNavigator's
`Boolean(mfaStatus?.blocked)` read null as "not blocked", and an unenrolled
surveyor saw the survey register before MfaRequiredScreen replaced it
(found on device, 2026-10-21).

The fix keeps ADR-377's rule -- a FAILED read must never block a shift -- by
tracking resolution separately from the answer, exactly as web does.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
AUTH = ROOT / "mobile/src/contexts/AuthContext.tsx"
NAV = ROOT / "mobile/src/navigation/index.tsx"


def _mfa_effect(src: str) -> str:
    """The useEffect that reads mfa-status for the signed-in account."""
    i = src.index("const userId = user?.id ?? null;")
    j = src.index("const refreshMfaStatus", i)
    return src[i:j]


def test_the_navigator_holds_until_the_answer_is_resolved():
    src = NAV.read_text()
    assert re.search(r"if \(isLoading \|\| \(isAuthenticated && !mfaResolved\)\)", src), (
        "RootNavigator must show the spinner, not the app, while the MFA read is "
        "in flight -- otherwise an unenrolled account sees the app first (ADR-556)")


def test_it_holds_on_resolution_not_on_a_non_null_status():
    """Waiting for `mfaStatus !== null` would hang forever when Cognito is down:
    a failed read leaves null by design (ADR-377)."""
    src = NAV.read_text()
    assert "mfaStatus === null" not in src and "mfaStatus == null" not in src
    assert "!mfaStatus)" not in src


def test_a_failed_read_resolves_and_does_not_block():
    eff = _mfa_effect(AUTH.read_text())
    catch = eff[eff.index("} catch {"): eff.index("} finally {")]
    assert "setMfaStatus(null)" in catch, "a failed read must leave null = not blocked"
    fin = eff[eff.index("} finally {"):]
    assert "setMfaResolved(true)" in fin.split("})();")[0], (
        "resolution must be marked in `finally`, so a failure is an answer, not a hang")


def test_the_effect_is_keyed_on_the_account_not_the_object():
    """Sign-in calls setUser twice (base, then firstName). Keyed on `user`, the
    second call would flip mfaResolved back to false and remount the app."""
    eff = _mfa_effect(AUTH.read_text())
    assert "}, [userId]);" in eff and "}, [user]);" not in eff
    assert "setMfaResolved(false);" in eff


def test_refresh_does_not_reset_resolution():
    """MfaRequiredScreen calls refreshMfaStatus after enrolling. If that cleared
    the flag, the spinner would unmount the screen mid-confirmation."""
    src = AUTH.read_text()
    i = src.index("const refreshMfaStatus")
    body = src[i: src.index("}, []);", i)]
    assert "setMfaResolved" not in body


def test_the_flag_is_on_the_context_and_the_fallback():
    src = AUTH.read_text()
    assert re.search(r"mfaResolved: boolean;", src)
    assert "mfaStatus, mfaResolved, refreshMfaStatus" in src
    assert "mfaResolved: false," in src


# ── D2: mobile routes to the wall on the server's refusal ──────────────────

CLIENT = ROOT / "mobile/src/api/client.ts"


def test_the_mobile_client_routes_on_the_refusal_code():
    """The status read can fail and let the app open (ADR-377). The server's
    403 is then the only signal; without this, every call errors and nothing
    says why."""
    src = CLIENT.read_text()
    assert re.search(r"status === 403 && err\.response\?\.data\?\.detail\?\.code === 'mfa_enrolment_required'", src)
    assert "mfaEnrolmentRequiredListeners.forEach(fn => fn())" in src


def test_the_auth_context_marks_the_account_blocked_on_that_signal():
    src = AUTH.read_text()
    i = src.index("useEffect(() => onMfaEnrolmentRequired(")
    body = src[i: src.index("}), []);", i)]
    assert "blocked: true" in body, "the refusal must put the person on the wall"
    assert "setMfaResolved(true)" in body


# ── D3: the reset request takes over the sign-in card ──────────────────────

WEB_LOGIN = ROOT / "frontend/src/components/auth/Login.tsx"
MOBILE_LOGIN = ROOT / "mobile/src/screens/Auth/LoginScreen.tsx"


def _between(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i: src.index(end, i)]


def test_web_renders_the_request_instead_of_the_form():
    src = WEB_LOGIN.read_text()
    # The request is the first branch of the card body; the form is the else.
    branch = _between(src, "{resetOpen ? (", ") : (")
    assert "<ResetRequest" in branch and "<form" not in branch
    assert src.index("{resetOpen ? (") < src.index("<form onSubmit={handleSubmit}")
    # The code step offers only the link now, not the panel.
    assert "<ResetRequestLink onOpen=" in src
    assert src.count("<ResetRequest\n") + src.count("<ResetRequest ") == 1


def test_mobile_renders_the_request_instead_of_the_challenge_and_form():
    src = MOBILE_LOGIN.read_text()
    assert src.index("{resetOpen ? (") < src.index("{challenge ? (")
    branch = _between(src, "{resetOpen ? (", ") : (")
    assert "<ResetRequest" in branch and "<TextInput" not in branch
    assert src.count("<ResetRequestLink onPress=") == 2   # code step + setup-closed


@pytest.mark.parametrize("path,clears", [
    (WEB_LOGIN, "backToSignIn();"),
    (MOBILE_LOGIN, "setChallenge(null);"),
], ids=["web", "mobile"])
def test_success_returns_to_sign_in_and_keeps_the_username(path, clears):
    """Owner, 2026-10-21: back to the sign-in screen with the username filled
    in, plus the next step."""
    src = path.read_text()
    on_sent = _between(src, "onSent={result => {", "}}")
    assert clears in on_sent and "setResetOpen(false)" in on_sent and "setResetSent(result)" in on_sent
    assert "setUsername" not in on_sent
    if path == WEB_LOGIN:
        assert "setUsername" not in _between(src, "const backToSignIn = () => {", "};")
    assert "title={`Request sent to ${resetSent.sentTo}`}" in src


@pytest.mark.parametrize("comp", [ROOT / "frontend/src/components/auth/ResetRequest.tsx",
                                  ROOT / "mobile/src/screens/Auth/ResetRequest.tsx"], ids=["web", "mobile"])
def test_the_panel_hands_the_servers_sentence_back(comp):
    """D4: the next step is written once, on the server, which knows the kind.
    D5: who it went to is the notice's title, so the body doesn't repeat it."""
    src = comp.read_text()
    assert "onSent({ sentTo: data.sent_to, nextStep: data.next_step ?? data.detail })" in src
    assert "'done'" not in src, "a 'done' step would leave the person on the code screen again"


# ── D5: one notice, honest sign-out wording, toggle order, two-line link ───

WEB_NOTICE = ROOT / "frontend/src/components/auth/SignInNotice.tsx"
MOBILE_NOTICE = ROOT / "mobile/src/screens/Auth/SignInNotice.tsx"


@pytest.mark.parametrize("login,notice", [(WEB_LOGIN, WEB_NOTICE), (MOBILE_LOGIN, MOBILE_NOTICE)],
                         ids=["web", "mobile"])
def test_every_sign_in_notice_is_the_shared_component(login, notice):
    src = login.read_text()
    for title in ('title="Two-factor setup needed"', 'title="You were signed out on every device"',
                  "title={`Request sent to ${resetSent.sentTo}`}"):
        assert title in src, title
    # The hand-rolled tinted boxes are gone.
    assert "noticeBox" not in src and "bg-success/5 text-success px-4" not in src
    n = notice.read_text()
    assert "alert" in n and ("status" in n or "summary" in n), "warnings alert, the rest are polite"


def test_mobile_sign_out_is_a_card_notice_not_a_native_alert():
    """The Alert blocked the form until dismissed and was the only place the
    reason was said."""
    src = AUTH.read_text()
    block = _between(src, "useEffect(() => onCredentialsChanged(", "}), []);")
    assert "Alert.alert" not in block and "setSessionNotice(" in block
    # Audience read BEFORE the user is cleared.
    assert block.index("setSessionNotice(") < block.index("setUser(null)")


@pytest.mark.parametrize("path", [WEB_LOGIN, MOBILE_LOGIN, AUTH, ROOT / "frontend/src/api/axiosClient.ts"],
                         ids=["web-login", "mobile-login", "mobile-auth", "web-axios"])
def test_the_sign_out_wording_names_two_factor_too(path):
    """One stamp ends sessions for a password change, an email change and a
    two-factor reset (account_security.mark_sessions_ended), all under the one
    `credentials_changed` code. Wording that names only "password or email"
    misreports the reset (owner's screenshot, 2026-10-21)."""
    src = path.read_text()
    assert "password or email was changed" not in src
    if path in (WEB_LOGIN, MOBILE_LOGIN):
        assert "password, email or two-factor sign-in was changed" in src
        assert "Contact AsheFlow support straight away." in src   # platform accounts have no manager


def test_the_web_audience_is_recorded_before_sign_out():
    src = (ROOT / "frontend/src/api/axiosClient.ts").read_text()
    assert src.index("asheflow_session_ended_audience") < src.index("await signOut()")


def test_mobile_show_password_follows_the_password_field():
    """Owner, 2026-10-21: Tab from username must land on the password, not on
    a Show button that sat between them in the label row."""
    src = MOBILE_LOGIN.read_text()
    pw = src.index("ref={pwRef}")
    toggle = src.index("accessibilityLabel=\"Show password\"")
    assert pw < toggle
    assert "s.labelRow" not in src


@pytest.mark.parametrize("comp", [ROOT / "frontend/src/components/auth/ResetRequest.tsx",
                                  ROOT / "mobile/src/screens/Auth/ResetRequest.tsx"], ids=["web", "mobile"])
def test_the_reset_link_is_two_lines_with_the_action_coloured(comp):
    src = comp.read_text()
    link = src[src.index("export function ResetRequestLink"): src.index("type Props")]
    assert "Can't use your authenticator?</" in link and ">Request a reset</" in link
    assert "Can't use your authenticator? Request a reset</" not in link
