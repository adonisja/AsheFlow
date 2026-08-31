"""A heartbeat finds the outage before a dispatcher does (ADR-337).

Every integration alert before this fired only when someone USED the
integration — Discord on a publish, SES on an invite, Cognito on an offboarding.
That is how a revoked Discord token crash-looped the bot for weeks and surfaced
when a dispatcher reported that messages had stopped.

It also left SES and Cognito alerts unable to close themselves: Discord clears
on the next successful bot call (ADR-335 D3), but the next email may be days
away. A board tidied by hand is one people stop believing.
"""
import ast
import inspect
import os

import pytest

from app.celery_app import celery_app
from app.tasks import integration_health as H


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


BOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "bot", "main.py")


def _bot_src() -> str:
    p = os.path.abspath(BOT)
    if not os.path.exists(p):
        pytest.fail(f"bot/main.py not found at {p}")
    return open(p).read()


# ── D1: it is actually scheduled AND registered ──────────────────────────────

def test_the_task_is_on_the_beat_schedule():
    assert "check-integration-health" in celery_app.conf.beat_schedule


def test_the_task_module_is_in_the_worker_include_list():
    """A beat entry naming a module the worker never imports fails silently at
    runtime — the schedule fires and nothing is registered to run."""
    assert "app.tasks.integration_health" in celery_app.conf.include


def test_the_scheduled_name_matches_the_registered_task():
    """A typo here is a task that is scheduled and never runs."""
    entry = celery_app.conf.beat_schedule["check-integration-health"]["task"]
    assert entry == "app.tasks.integration_health.check_integration_health"


# ── D2: the probes prove the credential, not the socket ──────────────────────

def test_the_discord_probe_reads_readiness_not_liveness():
    """THE lesson from the original incident. The container answered and the
    hostname resolved while the bot crash-looped on an invalid token — a
    liveness probe would have reported healthy the whole time."""
    src = _code_only(H._probe_discord)
    assert "discord_ready" in src, "the probe accepts a reachable process as healthy"


def test_the_bot_reports_is_ready_not_just_that_it_answered():
    src = _bot_src()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "handle_health"), None)
    assert fn is not None, "the bot has no health endpoint"
    body = ast.unparse(fn)
    assert "discord_ready" in body

    # `ready` must be ASSIGNED from is_ready(), not merely mentioned. A mutation
    # setting `ready = True` while the docstring still said is_ready() passed —
    # restoring the exact original incident, where the container answered while
    # the bot was logged out.
    tree_fn = ast.parse(body)
    assigns = [
        ast.unparse(n.value) for n in ast.walk(tree_fn)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "ready" for t in n.targets)
    ]
    assert assigns, "`ready` is never assigned"
    assert any("is_ready" in a for a in assigns), (
        f"readiness is not derived from bot.is_ready(): {assigns}"
    )


def test_the_health_route_is_registered_as_a_GET():
    assert 'add_get("/internal/health"' in _bot_src()


def test_the_probes_are_read_only():
    """A health check with side effects becomes a thing people disable."""
    src = inspect.getsource(H)
    assert "get_send_quota" in src, "SES probe is not the read-only quota call"
    assert "describe_user_pool" in src
    for mutating in ("send_email", "admin_disable_user", "admin_create_user", "delete_"):
        assert mutating not in src, f"probe calls {mutating}"


def test_probes_are_bounded_by_a_timeout():
    """A hanging probe delays the other two and the beat schedule."""
    src = _code_only(H._probe_discord)
    assert "timeout=" in src


# ── D3: it raises AND clears ─────────────────────────────────────────────────

def test_a_healthy_probe_clears_the_alert():
    """The half that matters most: it is what makes SES and Cognito alerts
    self-closing, since neither has a natural heartbeat of its own."""
    src = _code_only(H.check_integration_health)
    assert "clear_integration_alert" in src


def test_an_unhealthy_probe_raises_the_same_type_the_use_paths_raise():
    """So a probe failure and a real failure collapse into ONE incident via the
    ADR-335 dedup, rather than creating a parallel set of rows."""
    src = inspect.getsource(H)
    for t in ("DISCORD_INTEGRATION_FAILED", "EMAIL_DELIVERY_FAILED",
              "IDENTITY_REVOCATION_FAILED"):
        assert t in src, f"{t} is not probed"


# ── D4: platform-scoped ──────────────────────────────────────────────────────

def test_alerts_are_raised_with_no_company():
    """These are PLATFORM credentials (ADR-336 D3). This is the first producer
    to exercise ADR-335's `.is_(None)` dedup branch — which is why that branch
    was written and tested rather than assumed."""
    tree = ast.parse(_code_only(H.check_integration_health))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) in ("raise_platform_alert", "clear_integration_alert")]
    assert calls, "no alerts are raised or cleared"
    for c in calls:
        kw = {k.arg: ast.unparse(k.value) for k in c.keywords}
        assert kw.get("company_id") == "None", (
            f"a platform probe scoped its alert to a company: {ast.unparse(c)}"
        )


def test_adp_is_not_probed():
    """Its credentials are per-company (ADR-336 D3) — a failure is that tenant's
    own admin's to fix and must not reach a cross-tenant board."""
    # Asserted on the PROBE TUPLE, not the source text. A substring check
    # matched the comment explaining that ADP is deliberately absent — ninth
    # prose-vs-code false positive this week, in a test written minutes after
    # recording the lesson about it.
    probed = {alert_type for _fn, alert_type, _msg in H._PROBES}
    assert not any("adp" in t.lower() for t in probed), (
        f"ADP is being probed by the platform heartbeat: {probed}"
    )
    assert len(probed) == 3, f"expected exactly the three platform integrations, got {probed}"


# ── D5: one probe failing must not skip the others ───────────────────────────

def test_each_probe_is_independently_guarded():
    """Otherwise an SES outage silently becomes "Cognito was never checked"."""
    tree = ast.parse(_code_only(H.check_integration_health))
    loop = next((n for n in ast.walk(tree) if isinstance(n, ast.For)), None)
    assert loop is not None, "probes are not iterated"
    handlers = [n for n in ast.walk(loop) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "no per-probe exception handling — one failure skips the rest"

    # The catch-all must be BARE `Exception`, not a narrow type. A mutation
    # replacing it with ZeroDivisionError left the string "Exception" elsewhere
    # in the loop and passed — the guard was present and useless.
    caught = {ast.unparse(h.type) for h in handlers if h.type is not None}
    assert "Exception" in caught, (
        f"no bare-Exception catch-all; an unexpected probe error takes out the "
        f"others (handlers catch {caught})"
    )


def test_the_task_never_raises():
    """It shares a worker with five other scheduled tasks."""
    tree = ast.parse(_code_only(H.check_integration_health))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Raise)], (
        "the health check can break the worker it runs in"
    )


def test_the_session_is_always_closed():
    src = _code_only(H.check_integration_health)
    assert "finally" in src and "db.close()" in src
