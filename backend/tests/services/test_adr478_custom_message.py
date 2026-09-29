"""Every Cognito email looks like us (ADR-478).

A sign-in code arrived as Cognito's stock plain text -- no header, no brand --
and it is the email a privileged user sees most often. The pool had no
CustomMessage trigger, so every Cognito-generated message used AWS's default.

ADR-456 suppressed the one message we COULD suppress (admin-create temp
password). Suppression only works where we create the user; a sign-in code is
generated inside the auth flow and can only be rewritten. That is this trigger.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
LAMBDA_DIR = ROOT / "infra/lambda/cognito-custom-message"
sys.path.insert(0, str(LAMBDA_DIR))

import handler as H  # noqa: E402


def _event(source: str, code: str = "{####}", link: str = ""):
    return {
        "triggerSource": source,
        "request": {"codeParameter": code, "linkParameter": link},
        "response": {},
    }


CODE_SOURCES = [
    "CustomMessage_Authentication",
    "CustomMessage_ForgotPassword",
    "CustomMessage_UpdateUserAttribute",
    "CustomMessage_VerifyUserAttribute",
    "CustomMessage_SignUp",
    "CustomMessage_ResendCode",
]


# ── D1/D3: every source Cognito generates is branded ────────────────────────

@pytest.mark.parametrize("source", CODE_SOURCES)
def test_every_source_is_rendered(source):
    out = H.lambda_handler(_event(source), None)
    assert out["response"]["emailSubject"], source
    assert out["response"]["emailMessage"], source


@pytest.mark.parametrize("source", CODE_SOURCES)
def test_every_rendered_email_carries_the_brand(source):
    """Navy as the FIELD, violet as the ACCENT. The gradient templates use the
    accent as the whole identity, which is why they read as somebody else's
    email (send_owner_invite_email's docstring)."""
    body = H.lambda_handler(_event(source), None)["response"]["emailMessage"]
    assert H.NAVY in body, "no navy header"
    assert "AsheFlow" in body


@pytest.mark.parametrize("source", CODE_SOURCES)
def test_no_gradient_header(source):
    body = H.lambda_handler(_event(source), None)["response"]["emailMessage"]
    assert "linear-gradient" not in body


def test_the_code_placeholder_survives_rendering():
    """Cognito substitutes {####}. Escaping or dropping it sends an email with
    no code in it -- worse than the plain default, because it looks correct."""
    body = H.lambda_handler(_event("CustomMessage_Authentication"), None)
    assert "{####}" in body["response"]["emailMessage"]


# ── D2: the copy differs by what the reader is doing ────────────────────────

def test_each_source_says_something_different():
    """One shared message for signing in, recovering an account and confirming
    an address either says too little or claims the wrong thing."""
    subjects = {
        s: H.lambda_handler(_event(s), None)["response"]["emailSubject"]
        for s in CODE_SOURCES
    }
    assert subjects["CustomMessage_Authentication"] != subjects["CustomMessage_ForgotPassword"]
    assert "sign-in" in subjects["CustomMessage_Authentication"].lower()
    assert "password" in subjects["CustomMessage_ForgotPassword"].lower()


def test_a_reset_says_nothing_has_changed_yet():
    """Someone who did not request it needs to know they can ignore it safely."""
    body = H.lambda_handler(_event("CustomMessage_ForgotPassword"), None)["response"]["emailMessage"]
    assert "nothing has changed yet" in body


def test_a_sign_in_code_warns_about_an_unexpected_one():
    """An unexpected sign-in code means someone has the password. Saying so is
    the difference between a notification and a warning."""
    body = H.lambda_handler(_event("CustomMessage_Authentication"), None)["response"]["emailMessage"]
    assert "did not try to sign in" in body


# ── D3: ADR-456's suppression survives ──────────────────────────────────────

def test_admin_create_user_is_returned_untouched():
    """THE special case. ADR-456 suppresses this so send_credentials_email can
    send the branded version; rewriting it here reintroduces the double email
    that ADR removed."""
    out = H.lambda_handler(_event("CustomMessage_AdminCreateUser"), None)
    assert out["response"] == {}, "the suppressed source was rewritten"


def test_the_suppressed_set_is_named_not_implied():
    assert "CustomMessage_AdminCreateUser" in H.SUPPRESSED_SOURCES


def test_an_unknown_source_falls_through():
    """Cognito's default is plain, and plain beats a message written for a
    different situation."""
    out = H.lambda_handler(_event("CustomMessage_SomethingNew"), None)
    assert out["response"] == {}


# ── D4: it fails OPEN ───────────────────────────────────────────────────────

def test_a_malformed_event_does_not_raise():
    """A raise BLOCKS the message: a locked-out user with no code, or a password
    that cannot be reset. An ugly email is a bad day; a missing one is an
    incident."""
    for bad in ({}, {"triggerSource": "CustomMessage_Authentication"}, None):
        H.lambda_handler(bad, None)      # must not raise


def test_a_rendering_failure_returns_the_event(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("template exploded")

    monkeypatch.setattr(H, "_render", boom)
    out = H.lambda_handler(_event("CustomMessage_Authentication"), None)
    assert out["response"] == {}, "a failure must leave Cognito's default"


# ── D5/D6: presentation and logging ─────────────────────────────────────────

def test_the_code_is_on_its_own_line_not_inline():
    """Cognito's default buries it in a sentence, which is why it is easy to
    misread over a phone."""
    body = H.lambda_handler(_event("CustomMessage_Authentication"), None)["response"]["emailMessage"]
    assert "letter-spacing:7px" in body
    assert "font-size:30px" in body


def test_nothing_sensitive_is_logged():
    """A code in CloudWatch is a credential in CloudWatch (ADR-466)."""
    src = (LAMBDA_DIR / "handler.py").read_text()
    log_lines = [l for l in src.splitlines() if "logger." in l and "#" not in l.split("logger.")[0]]
    assert log_lines
    for line in log_lines:
        for leak in ("code", "params", "link", "email", "userName"):
            assert f", {leak}" not in line, f"log line may carry {leak}: {line.strip()}"


def test_html_in_a_code_is_escaped():
    """codeParameter is Cognito's, but the shell is shared with sources that
    interpolate a link -- escaping is the habit, not the exception."""
    body = H._code_block("<script>x</script>")
    assert "<script>" not in body
