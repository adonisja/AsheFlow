"""The setup redirect must not race the MFA answer (ADR-469).

A prod Owner signed in and the browser began throttling navigation. The cycle:

  AuthContext fires /employees/me/mfa-status WITHOUT awaiting it
    -> mfaStatus is null on the first render
    -> ProtectedRoute's `mfaStatus?.blocked` is falsy, so it FALLS THROUGH
    -> the unconfigured-admin guard sends them to /setup
    -> /setup calls /companies/my-config, which is gated by require_mfa_enrolled
    -> 403 mfa_enrolment_required
    -> the interceptor calls window.location.assign('/mfa-setup'), a FULL
       document navigation, which remounts AuthContext with mfaStatus null
    -> repeat

It burned the account's ADR-459 one-time enrolment pass without ever letting
them enrol, leaving them in the ADR-466 locked-out state.

ADR-465's guard ORDER was right, and tested. What was never tested is that the
value it routes on has ARRIVED. A guard that reads a not-yet-fetched value is a
guard that does not run.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
AUTH = ROOT / "frontend/src/contexts/AuthContext.tsx"
APP = ROOT / "frontend/src/App.tsx"
AXIOS = ROOT / "frontend/src/api/axiosClient.ts"


def _auth() -> str:
    return AUTH.read_text()


# ── the timing fix ──────────────────────────────────────────────────────────

def test_the_mfa_status_fetch_is_awaited():
    """Fire-and-forget is what let routing run before the answer arrived."""
    src = _auth()
    assert "await axiosClient.get('/employees/me/mfa-status')" in src, (
        "mfa-status is not awaited, so mfaStatus is null on the first render "
        "and the blocked guard falls through to the /setup redirect"
    )


def test_the_fetch_is_not_fire_and_forget():
    """Pins the specific shape that regressed, not just the presence of await."""
    src = _auth()
    assert "void axiosClient" not in src or "mfa-status" not in \
        src.split("void axiosClient", 1)[-1].split(";", 1)[0], (
        "the mfa-status call is back to void/fire-and-forget"
    )


def test_a_failed_read_still_means_not_blocked():
    """ADR-377's rule, kept: null is "could not tell", never "blocked".

    An AWS hiccup must not wall the company. This is what made the original
    fire-and-forget defensible for a BANNER -- it is still right, it just is not
    a reason to skip the await.
    """
    src = _auth()
    block = src.split("mfa-status", 1)[1].split("finally", 1)[0]
    assert "setMfaStatus(null)" in block


# ── the failure fix ─────────────────────────────────────────────────────────

def test_resolution_is_tracked_separately_from_the_answer():
    """`mfaStatus === null` cannot distinguish "not yet" from "failed".

    Gating the setup redirect on null would trade the redirect loop for an
    unconfigured admin hung on a spinner forever whenever Cognito is
    unreachable -- a worse failure, because nothing recovers it.
    """
    src = _auth()
    assert "mfaResolved" in src
    assert "const [mfaResolved, setMfaResolved] = useState(false)" in src


def test_resolution_is_marked_on_both_arms():
    """A failed read is an ANSWER. Marking it only on success is the hang."""
    src = _auth()
    tail = src.split("mfa-status", 1)[1]
    fin = tail.split("finally", 1)
    assert len(fin) == 2, "the resolved flag is not set in a finally block"
    assert "setMfaResolved(true)" in fin[1].split("}", 2)[0]


def test_the_flag_is_exported_on_the_context():
    src = _auth()
    assert re.search(r"mfaResolved:\s*boolean", src), "not on the context type"
    assert re.search(r"^\s*mfaResolved,\s*$", src, re.M), "not in the value"


# ── the guard that was losing the race ──────────────────────────────────────

def test_the_setup_redirect_waits_for_the_mfa_answer():
    src = APP.read_text()
    guard = src.split("groups.includes('admin') && !isConfigured", 1)[1] \
               .split("{", 1)[0]
    assert "mfaResolved" in guard, (
        "the unconfigured-admin redirect still fires before the MFA answer "
        "arrives, which is the loop"
    )


def test_it_waits_on_resolution_not_on_a_non_null_status():
    """The distinction that keeps a Cognito outage from hanging setup."""
    src = APP.read_text()
    guard = src.split("groups.includes('admin') && !isConfigured", 1)[1] \
               .split("{", 1)[0]
    assert "mfaStatus !== null" not in guard, (
        "gating on null hangs an unconfigured admin whenever the status read "
        "fails; gate on mfaResolved instead"
    )


def test_the_blocked_guard_still_runs_first():
    """ADR-465 D1. Order was never the bug, and must not be 'fixed'."""
    src = APP.read_text()
    assert src.index("mfaStatus?.blocked") < \
        src.index("groups.includes('admin') && !isConfigured")


def test_the_interceptor_still_redirects_on_the_code():
    """The loop is closed at the source, so this stays as ADR-465 built it --
    a blocked session mid-flight must still reach the wall."""
    src = AXIOS.read_text()
    assert "mfa_enrolment_required" in src
    assert "window.location.assign('/mfa-setup')" in src
