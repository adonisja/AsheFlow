"""A dead integration must reach an admin who can fix it (ADR-323).

Written after a revoked Discord bot token crash-looped the bot for weeks. The
failure was logged at every call site and never escalated, so it surfaced only
when a dispatcher happened to hit the one endpoint that refused rather than
degraded.
"""
import ast
import inspect

import pytest

from app.services import integration_alerts as IA
from app.routers import dispatch as D


def _code_only(obj) -> str:
    """Source with docstrings stripped — grep matches its own prose otherwise."""
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── Dimension 1: the highest-risk line in the change ─────────────────────────

def test_the_admin_query_is_company_scoped():
    """Unscoped, this mails every admin of every tenant about one company's
    outage — a cross-tenant leak dressed as an alert."""
    src = _code_only(IA.alert_admins_integration_down)
    assert "Employee.company_id == company_id" in src


# ── D3: admins only, deliberately narrower than the ADP precedent ────────────

def test_management_is_not_alerted():
    """Diverges from adp.py's ["admin", "management"] ON PURPOSE. Rotating a bot
    token is an admin task; alerting someone with no lever on it trains them to
    dismiss alerts. Asserted so the narrower list cannot be "helpfully" widened
    back without failing a test that explains why."""
    src = _code_only(IA.alert_admins_integration_down)
    # ast.unparse normalises quotes to single, so match quote-agnostically.
    assert "Employee.role == 'admin'" in src or 'Employee.role == "admin"' in src
    assert "management" not in src
    assert "role.in_" not in src


def test_only_active_admins():
    src = _code_only(IA.alert_admins_integration_down)
    assert "Employee.is_active" in src


# ── D4: dedup, so one outage is not one row per click ────────────────────────

def test_dedup_is_on_unread_not_a_time_window():
    """A dead integration is a continuous condition, not an event. Unread means
    an admin acting on it is not re-alerted, while one who dismissed it without
    fixing it is — which is the correct behaviour."""
    src = _code_only(IA.alert_admins_integration_down)
    assert "Notification.is_read == False" in src
    assert "timedelta" not in src


def test_dedup_is_per_recipient():
    """An admin with no unread alert must still get one when a colleague already
    has theirs — so the existence check is keyed on employee_id."""
    src = _code_only(IA.alert_admins_integration_down)
    assert "Notification.employee_id == admin.id" in src


# ── Alerting must never become the failure ───────────────────────────────────

def test_the_alerter_never_raises():
    """This runs on paths that are ALREADY handling a failure. An alerting bug
    must not become the thing that breaks the request."""
    src = _code_only(IA.alert_admins_integration_down)
    assert "except Exception:" in src
    assert "return 0" in src


# ── D2: the leak this ADR was written from ───────────────────────────────────

def test_finalize_returns_no_exception_text_or_upstream_body():
    """The operator saw `Cannot connect to host bot:8001 ssl:default [Name or
    service not known]` in a browser — an internal hostname, port and resolver
    error. The body and the exception are logged, never returned."""
    src = _code_only(D.finalize_dispatch)
    assert "detail=f\"Could not reach the Discord bot: {e}\"" not in src
    assert "Bot webhook returned {resp.status}: {body}" not in src
    assert "An administrator has been notified" in src


def test_finalize_refuses_with_503_and_says_nothing_was_finalized():
    """"Nothing was finalized" is the operationally important sentence: without
    it a dispatcher cannot tell a failed finalize from a half-finished one, and
    the safe assumption (that some of it landed) is the wrong one."""
    src = _code_only(D.finalize_dispatch)
    assert "HTTP_503_SERVICE_UNAVAILABLE" in src
    assert "Nothing was finalized" in src
    assert "HTTP_502_BAD_GATEWAY" not in src


# ── D1: the ordering that makes refusing correct ─────────────────────────────

def test_finalize_still_refuses_rather_than_degrading():
    """Finalize must NOT be "fixed" to degrade like publish. Its bot call is the
    first irreversible step and gates the status flip, so a failure has written
    nothing and is already retryable. Degrading would flip status while crews
    were never posted — the stranded state publish's own comment exists to
    prevent."""
    src = _code_only(D.finalize_dispatch)
    bot_call = src.index("/internal/finalize")
    flip = src.index('status = \'completed\'') if "status = 'completed'" in src else src.index('status = "completed"')
    assert bot_call < flip, (
        "the bot call must stay AHEAD of the status flip — that ordering is what "
        "makes a failed finalize atomic and retryable (ADR-323 D1)"
    )


# ── D5: alerting is orthogonal to whether the request survives ───────────────

@pytest.mark.parametrize("fn_name", ["publish_dispatch", "finalize_dispatch"])
def test_every_bot_failure_path_alerts(fn_name):
    """Degrading for the caller is not a reason to stay silent with the
    operator. Had this existed, the outage would have surfaced on the first
    publish after the token was revoked."""
    src = _code_only(getattr(D, fn_name))
    assert "alert_admins_integration_down" in src


def test_publish_still_degrades_rather_than_failing():
    """Publish flips status BEFORE the bot call and re-publish 409s, so a
    refusal there strands the day. It must keep succeeding."""
    src = _code_only(D.publish_dispatch)
    assert "HTTP_503_SERVICE_UNAVAILABLE" not in src


def test_alert_rows_are_committed_on_every_path():
    """The publish paths commit their own work BEFORE the bot call and return
    without another commit, so alert rows would sit in the session and be
    silently discarded. An alerting mechanism that drops its alerts is worse
    than none. (This was a real bug in the first draft, caught by the audit.)"""
    for fn in (D.publish_dispatch, D.finalize_dispatch):
        tree = ast.parse(_code_only(fn))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        alerts = [c for c in calls
                  if getattr(c.func, "id", None) == "alert_admins_integration_down"]
        assert alerts, f"{fn.__name__} does not alert"

        src = _code_only(fn)
        for chunk in src.split("alert_admins_integration_down")[1:]:
            head = chunk[:400]
            assert "db.commit()" in head, (
                f"{fn.__name__}: no commit follows the alert — the rows are discarded"
            )
