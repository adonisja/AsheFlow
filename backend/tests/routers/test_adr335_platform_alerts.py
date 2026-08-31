"""Super admins can finally receive the alert only they can act on (ADR-335).

ADR-323 alerted company admins when Discord went down. ADR-324 D2 found that
audience incomplete — a company admin cannot rotate a Discord bot token — and
found the blocker structural: Notification.employee_id is non-nullable with an
FK to employees, and a super admin has no Employee row by design
(get_super_admin, deps.py:247). The shape was decided and deferred; this builds
it.
"""
import ast
import inspect
import os

import pytest

from app.models.platform_alert import PlatformAlert
from app.routers import platform_alerts as P
from app.services import integration_alerts as IA


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


# ── D1: the shape that makes a super admin reachable ─────────────────────────

def test_company_id_is_nullable_by_design():
    """The one place a null company_id is CORRECT rather than a Dim 1 defect: a
    Discord outage is one incident across every tenant."""
    assert PlatformAlert.__table__.columns["company_id"].nullable is True


def test_resolved_by_is_not_a_foreign_key():
    """ADR-274 D13 — writing a super admin's Cognito sub into an employees FK
    raises ForeignKeyViolation and 500s the endpoint. The company audits did
    exactly that and staging caught it."""
    for col in ("resolved_by_sub", "resolved_by_email"):
        assert not PlatformAlert.__table__.columns[col].foreign_keys, (
            f"{col} has an FK — a super admin has no Employee row"
        )


def test_it_is_a_separate_table_not_a_nullable_notification_column():
    """ADR-324 rejected Option A: making Notification.employee_id nullable would
    force every existing notification read to learn to exclude platform rows."""
    from app.models.notification import Notification
    assert Notification.__table__.columns["employee_id"].nullable is False


# ── D2: dedup on the open incident ───────────────────────────────────────────

def test_dedup_is_on_the_unresolved_incident_not_a_reader():
    """ADR-323 D4 deduped a Notification on is_read — right for an inbox. A
    platform alert is a CONDITION; the key is the open incident."""
    src = _code_only(IA.raise_platform_alert)
    assert "PlatformAlert.is_resolved.is_(False)" in src
    assert "is_read" not in src


def test_a_platform_wide_alert_dedups_against_platform_wide_alerts():
    """`== None` does not match NULL in SQL. Without the is_() branch every
    platform-wide failure would insert a new row instead of deduping."""
    src = _code_only(IA.raise_platform_alert)
    assert "PlatformAlert.company_id.is_(None)" in src


def test_a_repeat_records_occurrence_and_recency():
    """"first seen 09:12, 47 occurrences, still failing" is a different picture
    from "an alert exists", and they are indistinguishable without these."""
    src = _code_only(IA.raise_platform_alert)
    assert "occurrence_count += 1" in src
    assert "last_seen_at" in src


def test_raising_never_breaks_the_caller():
    """It runs on paths already handling a failure.

    Asserted on ast.Raise NODES. A substring check for "raise" matched the log
    MESSAGE — "could not raise platform alert" — which is prose, not control
    flow. Seventh instance this week of text matching a grep aimed at code.
    """
    tree = ast.parse(_code_only(IA.raise_platform_alert))
    handlers = [h for h in ast.walk(tree) if isinstance(h, ast.ExceptHandler)]
    assert handlers, "no exception handling at all"
    for h in handlers:
        assert not [n for n in ast.walk(h) if isinstance(n, ast.Raise)], (
            "the handler re-raises — an alerting bug must not break the caller"
        )


# ── D3: it closes itself ─────────────────────────────────────────────────────

def test_a_recovered_integration_closes_its_own_alert():
    """A condition that only a human can close is stale within a day, and a
    stale incident board teaches its reader to distrust it."""
    src = _code_only(IA.clear_integration_alert)
    assert "is_resolved = True" in src
    assert "resolved_at" in src


def test_a_self_resolve_records_no_human():
    """resolved_by_sub distinguishes "the condition ended" from "someone closed
    it" — so the auto path must not set it."""
    src = _code_only(IA.clear_integration_alert)
    assert "resolved_by_sub" not in src


def test_every_bot_success_path_clears(): 
    """Raised in three places, so cleared in three places — otherwise an alert
    outlives the outage on whichever path recovers."""
    from app.routers import dispatch as D
    src = inspect.getsource(D)
    assert src.count("clear_integration_alert(db") >= 3


# ── D4: both audiences, one call ─────────────────────────────────────────────

def test_one_call_alerts_both_audiences():
    """So a future integration cannot alert one and forget the other."""
    src = _code_only(IA.alert_admins_integration_down)
    assert "raise_platform_alert(db" in src
    assert "Employee.role == 'admin'" in src or 'Employee.role == "admin"' in src


# ── D5: the endpoints ────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", ["list_platform_alerts", "resolve_platform_alert"])
def test_the_endpoints_are_super_admin_only(fn):
    """Never RoleChecker — a company admin must not read another tenant's
    incidents, and a platform alert has no tenant to check against."""
    sig = inspect.signature(getattr(P, fn))
    deps = [str(p.default) for p in sig.parameters.values() if p.default is not inspect._empty]
    assert any("get_super_admin" in d for d in deps), f"{fn} is not super-admin gated"
    assert not any("RoleChecker" in d for d in deps)


def test_resolve_is_idempotent_guarded():
    """A one-way state stamp: a double click must not overwrite who closed it."""
    src = _code_only(P.resolve_platform_alert)
    assert "HTTP_409_CONFLICT" in src
    assert "is_resolved" in src


def test_manual_resolve_records_the_cognito_identity_as_text():
    src = _code_only(P.resolve_platform_alert)
    assert "resolved_by_sub = _super.get('id')" in src or 'resolved_by_sub = _super.get("id")' in src
    assert "actor_id=None" in src, "a super admin must leave actor_id NULL (ADR-274 D13)"


def test_the_request_body_is_typed_and_closed():
    """Dimension 9."""
    R = P.ResolveRequest
    assert R.model_config.get("extra") == "forbid"
    note = R.model_fields["note"]
    assert any(getattr(m, "max_length", None) == 500 for m in note.metadata), "note is unbounded"
    for name, f in R.model_fields.items():
        assert "Any" not in str(f.annotation)


def test_the_read_is_bounded():
    """An unbounded list endpoint is a slow query waiting to happen."""
    sig = inspect.signature(P.list_platform_alerts)
    assert "limit" in sig.parameters
