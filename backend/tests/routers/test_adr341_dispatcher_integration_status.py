"""A dispatcher learns about an outage they cannot query (ADR-341).

Two gaps ADR-340 recorded. The harder one is a scoping tension the ADR-335 model
creates: the heartbeat's row is company_id NULL (ADR-337 D4), and every
company-scoped read filters company_id == caller.company_id — which excludes
exactly the row a dispatcher needs.
"""
import ast
import inspect
import os
import re

import pytest

import app.routers.dispatch as D

FE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src")


def _code_only(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


def _read(rel: str) -> str:
    p = os.path.abspath(os.path.join(FE, rel))
    if not os.path.exists(p):
        pytest.fail(f"{rel} not found at {p}")
    return open(p).read()


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


# ── Route ordering: this shipped broken and was caught before merge ──────────

def test_the_literal_route_is_not_shadowed_by_the_date_parameter():
    """THE bug this nearly shipped with.

    FastAPI matches in REGISTRATION order, so `/dispatch/integration-status`
    declared after `/dispatch/{dispatch_date}` is swallowed and parsed as a
    date — a 422 for every call. It was registered at index 28 against the date
    route's index 2 until it was moved.

    Asserted on the router's own path order, because a request-level test
    returns 401 from auth before routing resolves the parameter and would look
    like a pass.
    """
    paths = [getattr(r, "path", "") for r in D.router.routes]
    assert "/dispatch/integration-status" in paths, "the route is not registered"
    literal = paths.index("/dispatch/integration-status")
    param = paths.index("/dispatch/{dispatch_date}")
    assert literal < param, (
        f"/dispatch/integration-status (index {literal}) is registered AFTER "
        f"/dispatch/{{dispatch_date}} (index {param}) and will 422 as a bad date"
    )


# ── D2: mine OR platform-wide ────────────────────────────────────────────────

def test_the_query_admits_platform_wide_alerts():
    """The failure mode: without the is_(None) arm the endpoint reports HEALTHY
    during a total Discord outage, because the heartbeat's row belongs to no
    company. Wrong exactly when it matters most."""
    src = _code_only(D.get_integration_status)
    assert "PlatformAlert.company_id.is_(None)" in src, (
        "platform-wide alerts are excluded — a total outage would read as healthy"
    )


def test_the_query_still_excludes_other_tenants():
    """Dim 1 — admitting NULL must not admit everyone else's rows."""
    src = _code_only(D.get_integration_status)
    assert "PlatformAlert.company_id == caller.company_id" in src
    assert "or_(" in src, "the two arms are not OR'd — one of them is unreachable"


def test_it_is_scoped_to_discord_only():
    """SES and Cognito failures are real and are not a dispatcher's business:
    they cannot resend an invite from this screen. Noise here is noise they
    learn to ignore."""
    src = _code_only(D.get_integration_status)
    assert "DISCORD_INTEGRATION_FAILED" in src
    for other in ("EMAIL_DELIVERY_FAILED", "IDENTITY_REVOCATION_FAILED"):
        assert other not in src


def test_only_open_alerts_count():
    src = _code_only(D.get_integration_status)
    assert "is_resolved.is_(False)" in src


# ── D1: a boolean, not a feed ────────────────────────────────────────────────

def test_it_returns_a_flag_and_a_timestamp_not_rows():
    """A cross-tenant infrastructure view on a dispatch board hands detail to
    someone with no ability to act on it."""
    src = _code_only(D.get_integration_status)
    assert "'discord_healthy': row is None" in src
    assert "'since'" in src
    for leaked in ("occurrence_count", "severity", "resolved_by"):
        assert leaked not in src, f"{leaked} is exposed to a dispatcher"


# ── D4: the banner says the consequence ──────────────────────────────────────

def test_the_banner_names_the_in_app_fallback():
    """"Discord integration failed" is unusable. That crews ARE still notified
    (ADR-324 D1) is the fact that changes what a dispatcher does next."""
    code = _strip_comments(_read("pages/DispatchDashboard.tsx"))
    assert "still notified in the app" in code


def test_the_banner_sits_above_the_action_buttons():
    """ADR-333 — a message far from the control it concerns is one nobody reads."""
    code = _strip_comments(_read("pages/DispatchDashboard.tsx"))
    banner = code.index("discordDown && (")
    actions = code.index("Row 3 — workflow actions") if "Row 3 — workflow actions" in code \
        else code.index("handleRunDispatch}")
    assert banner < actions, "the banner renders below the buttons it qualifies"


def test_the_status_fetch_is_best_effort():
    """A dispatcher must still see their board if this one call fails."""
    code = _strip_comments(_read("pages/DispatchDashboard.tsx"))
    i = code.index("integration-status")
    assert ".catch(" in code[i:i + 400], "a failed status call would surface as an error"


# ── D5: the notification list ────────────────────────────────────────────────

def test_failure_notifications_are_matched_before_the_suffix_branches():
    """The chain is first-match-wins, so a future `..._failed_rejected` would
    take the _rejected branch and render as a routine denial. The ordering is
    load-bearing."""
    code = _strip_comments(_read("pages/NotificationsHistory.tsx"))
    failed = code.index("type.endsWith('_failed')")
    rejected = code.index("type.endsWith('_rejected')")
    assert failed < rejected, "_failed is matched after _rejected"


def test_revocation_failure_is_danger_not_warning():
    """An offboarded employee who can still sign in (ADR-336 D2) is a different
    severity from an email that did not send."""
    code = _strip_comments(_read("pages/NotificationsHistory.tsx"))
    i = code.index("identity_revocation_failed")
    assert "text-danger" in code[i:i + 220]


def test_the_alert_types_have_human_labels():
    """labelForType would render "Discord Integration Failed" — a system string,
    not something that happened to this company."""
    code = _strip_comments(_read("pages/NotificationsHistory.tsx"))
    assert "FAILURE_LABELS" in code
    assert "Discord is down" in code
