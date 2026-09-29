"""A completed sign-in must not show the sign-in form (ADR-479).

Reported as "it redirects to the login page for a second" after entering the
emailed code. Nothing redirected -- the user never left /login.

`advance()` cleared challengeStep BEFORE awaiting checkAuth, and challengeStep
is the only thing choosing which form renders. So for the whole of checkAuth --
five serialised network round-trips -- an authenticated user was shown the
logged-out username/password form, Discord and Google buttons and all.

/login is a bare route, so ProtectedRoute's existing spinner never covers this.

These are source-inspecting tests: there is no frontend test runner in this
repo, so they pin the shape of the code rather than exercising it. Weaker than
a render test, and recorded as such in the ADR.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
LOGIN = ROOT / "frontend/src/components/auth/Login.tsx"


def _advance_body() -> str:
    """The `advance` closure, from its declaration to the end of its switch."""
    src = LOGIN.read_text()
    i = src.index("const advance =")
    return src[i:src.index("try {", i)]


def _submit_button() -> str:
    """The submit <button>, element only -- not the comment above it.

    Sliced from the tag itself so an assertion cannot be satisfied by prose in
    a nearby comment. That false pass happened repeatedly while building the
    scorecard work: `le=100` matched inside a docstring, `<select` inside an
    explanatory note.
    """
    src = LOGIN.read_text()
    i = src.index('<button\n              type="submit"')
    return src[i:src.index("</button>", i)]


def test_the_challenge_step_is_not_cleared_before_the_session_exists():
    """THE fix. Clearing it first is what rendered the logged-out form."""
    body = _advance_body()
    assert "setChallengeStep(null); return checkAuth()" not in body, (
        "challengeStep is cleared before checkAuth is awaited -- this renders "
        "the logged-out sign-in form over a completed sign-in"
    )
    assert "return checkAuth();" in body, (
        "the isSignedIn branch no longer calls checkAuth"
    )


def test_nothing_clears_the_step_after_checkauth_either():
    """A .finally(() => setChallengeStep(null)) here looks like the careful
    version and is dead: checkAuth sets isAuthenticated, the effect navigates
    to '/', and Login unmounts before it could run."""
    assert "finally(() => setChallengeStep(null))" not in _advance_body()


def test_the_submit_button_is_disabled_while_in_flight():
    """Without this the form is re-submittable during every challenge, and a
    one-time code sent twice fails with NotAuthorizedException -- surfacing
    'Sign in failed' on a sign-in that actually succeeded."""
    assert "disabled={submitting}" in _submit_button()


def test_the_pending_label_names_what_is_happening():
    """'Loading...' is right for a route transition, where the app does not know
    what it is loading. Here it does."""
    btn = _submit_button()
    assert "Signing you in" in btn
    # The password challenge is not a sign-in, and must not claim to be.
    assert "Saving your password" in btn


def test_submitting_is_cleared_on_every_path():
    """A submitting flag left set on the error path disables the button
    permanently -- the user reads a real error and cannot retry."""
    src = LOGIN.read_text()
    i = src.index("setSubmitting(true)")
    tail = src[i:src.index("const isNewPassword", i)]
    assert "finally {" in tail and "setSubmitting(false)" in tail, (
        "setSubmitting(false) must be in a finally, or a failed sign-in leaves "
        "the button disabled with no way back"
    )
