"""Two guards that each exempt only their own page will ping-pong (ADR-471).

The prod Owner reached /mfa-setup correctly -- ADR-469's fix worked -- and then
the page looped there. Measured in the browser, which is what settled it:

    {path: '/mfa-setup', navType: 'navigate', reloads: 1}

ONE document load, and no failing request in the console. So this was not the
403 interceptor and not location.assign: it was two React-router <Navigate>
components handing control back and forth.

  guard 1 (blocked)      exempts /mfa-setup, sends everything else there
  guard 2 (unconfigured) exempts /setup ONLY

On /mfa-setup, guard 1 correctly declines (already there) and guard 2 fires ->
/setup. On /setup, guard 1 fires -> /mfa-setup. Forever.

Ordering does not fix it: guard 1 is already first, and the loop happens
precisely BECAUSE guard 1 politely declines to act on its own page.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
APP = ROOT / "frontend/src/App.tsx"


def _setup_guard() -> str:
    """The unconfigured-admin redirect, from `if (` to its closing `) {`."""
    src = APP.read_text()
    i = src.index("groups.includes('admin') && !isConfigured")
    return src[i:src.index("{", src.index("/setup'", i))]


def test_the_setup_redirect_stands_down_for_a_blocked_account():
    """THE fix. Without this the two guards hand control back and forth."""
    assert "!mfaStatus?.blocked" in _setup_guard(), (
        "the unconfigured-admin redirect still fires on /mfa-setup, which sends "
        "a blocked admin to /setup and straight back again"
    )


def test_the_blocked_guard_still_exempts_its_own_page():
    """The other half of the pair. Removing this exemption would replace the
    ping-pong with a redirect to itself."""
    src = APP.read_text()
    assert "mfaStatus?.blocked && location.pathname !== '/mfa-setup'" in src


def test_the_blocked_guard_runs_first():
    """ADR-465 D1, unchanged. Ordering was never the bug here, and a future
    reader 'fixing' the loop by reordering would not fix it."""
    src = APP.read_text()
    assert src.index("mfaStatus?.blocked") < \
        src.index("groups.includes('admin') && !isConfigured")


def test_no_pair_of_guards_exempts_only_its_own_path():
    """The general shape, not just this instance.

    Every redirect guard in ProtectedRoute that exempts a path must also decline
    when a HIGHER-priority guard owns the current page. Enumerated rather than
    spot-checked: a third guard added later reintroduces the loop, and the
    author will not remember this incident.
    """
    src = APP.read_text()
    body = src.split("const ProtectedRoute", 1)[1].split("\nconst ", 1)[0]
    redirects = re.findall(r"if \((.*?)\)\s*\{\s*return <Navigate", body, re.S)
    guards = [r for r in redirects if "location.pathname" in r]
    assert len(guards) >= 2, "expected at least the blocked and setup guards"

    # Guard 1 owns /mfa-setup. Every OTHER guard must defer to it.
    for g in guards:
        if "mfaStatus?.blocked" in g and "!mfaStatus?.blocked" not in g:
            continue                      # this IS guard 1
        assert "blocked" in g, (
            f"a redirect guard does not defer to the MFA wall, so it will fire "
            f"on /mfa-setup and loop: {' '.join(g.split())[:120]}"
        )


def test_the_loop_needed_no_network_call():
    """Documents why the console was empty, so the next person does not spend
    the debugging session in the Network tab as I did.

    Both guards are pure render-time redirects. Nothing fetches, so nothing
    fails, so there is nothing to see but Chrome's throttle warning.
    """
    guard = _setup_guard()
    for io in ("axios", "fetch(", "await "):
        assert io not in guard, "the guard performs I/O; the analysis above changes"
