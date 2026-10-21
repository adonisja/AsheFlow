"""A health check must be able to see, and must say when something new breaks (ADR-535).

Measured 2026-10-17: every check failed on both environments (the EC2 roles
could not read CloudTrail/EventBridge/Lambda/SNS), and ONE critical alert sat
open on staging from 2026-09-07 -- the day the task shipped -- because:
  - the task raised but never cleared (ADR-335 D3's clear was never called);
  - every check shared one alert type, and dedup keeps the FIRST message, so a
    new failure (a dropped sign-in trigger) only bumped a counter.

These run the real task and the real raise/clear against the sqlite test DB,
with only the AWS-facing check functions stubbed.
"""
from unittest.mock import patch

import pytest

from app.models.platform_alert import PlatformAlert
from app.services import integration_alerts as ia
from app.tasks import security_infra_health as h

@pytest.fixture(autouse=True)
def _platform_alerts_table(db):
    """conftest's db builds a fixed table list without platform_alerts; these are
    the first DB-backed platform-alert tests, so create it here rather than
    widen the shared fixture -- and empty it around each test, because the
    table outlives the fixture's own cleanup."""
    PlatformAlert.__table__.create(bind=db.get_bind(), checkfirst=True)
    db.query(PlatformAlert).delete(); db.commit()
    yield
    db.rollback(); db.query(PlatformAlert).delete(); db.commit()


FN_FOR = {"trail": "_check_trail", "responder": "_check_rule_and_lambda", "topic": "_check_topic",
          "containment": "_check_containment_permissions", "pool_triggers": "_check_pool_triggers",
          "client_write_attributes": "_check_client_write_attributes"}   # ADR-558


def _run(db, crash=(), **failing):
    """Run the real task: every check passes unless given as name=[problems],
    or raises if named in `crash`.

    ONE patch per function. An earlier version patched a failing check twice
    (passing, then failing) and stopped them in start order -- the last stop()
    restored the FIRST patch's mock instead of the real function, and the leak
    broke test_adr530_pool_trigger_health.py, which ran next."""
    patches = []
    for name, fn in FN_FOR.items():
        if name in crash:
            patches.append(patch.object(h, fn, side_effect=RuntimeError("boom")))
        else:
            patches.append(patch.object(h, fn, return_value=failing.get(name, [])))
    patches.append(patch.object(h, "SessionLocal", return_value=_NoClose(db)))
    for p in patches: p.start()
    try:
        return h.check_security_infra()
    finally:
        for p in reversed(patches): p.stop()


class _NoClose:
    """The task closes its session; the test still needs to read from it."""
    def __init__(self, db): self._db = db
    def __getattr__(self, k): return getattr(self._db, k)
    def close(self): pass


def _open(db):
    return {a.alert_type: a for a in db.query(PlatformAlert).filter(PlatformAlert.is_resolved.is_(False)).all()}


# ── D2: one alert per check ────────────────────────────────────────────────

def test_a_new_failure_in_another_check_is_a_new_alert(db):
    """THE hiding bug: a dropped trigger merged into the trail's open alert."""
    _run(db, trail=["trail AsheFlow-Trail: AccessDeniedException"])
    _run(db, trail=["trail AsheFlow-Trail: AccessDeniedException"],
         pool_triggers=["PostAuthentication trigger is missing"])
    open_ = _open(db)
    assert set(open_) == {"security_infra.trail", "security_infra.pool_triggers"}
    assert "PostAuthentication" in open_["security_infra.pool_triggers"].message


# ── D3: a passing check clears its own alert ───────────────────────────────

def test_a_check_that_passes_again_clears_its_alert(db):
    _run(db, topic=["topic AsheFlow-SecurityAlerts: no confirmed subscribers"])
    assert "security_infra.topic" in _open(db)
    _run(db)                                               # everything healthy
    assert _open(db) == {}
    closed = db.query(PlatformAlert).filter(PlatformAlert.alert_type == "security_infra.topic").one()
    assert closed.is_resolved and closed.resolved_at is not None


def test_clearing_one_check_leaves_the_others_open(db):
    _run(db, trail=["x"], responder=["y"])
    _run(db, responder=["y"])
    assert set(_open(db)) == {"security_infra.responder"}


# ── D4: the open alert says what is broken NOW ─────────────────────────────

def test_an_open_alert_tracks_the_current_problem(db):
    _run(db, pool_triggers=["PreAuthentication trigger is missing"])
    _run(db, pool_triggers=["PostAuthentication trigger is missing"])
    alert = _open(db)["security_infra.pool_triggers"]
    assert "PostAuthentication" in alert.message and "PreAuthentication" not in alert.message
    assert alert.occurrence_count == 2                      # still one incident, counted


def test_refresh_is_opt_in_so_other_callers_keep_the_first_message(db):
    """Discord/email re-raise the same condition; their first message stands."""
    ia.raise_platform_alert(db, alert_type="discord_integration_failed", message="first")
    db.flush()   # real callers commit between raises; dedup can't see an unflushed add
    ia.raise_platform_alert(db, alert_type="discord_integration_failed", message="second")
    db.flush()
    a = db.query(PlatformAlert).filter(PlatformAlert.alert_type == "discord_integration_failed").one()
    assert a.message == "first" and a.occurrence_count == 2


# ── D5: the legacy shared alert is retired ─────────────────────────────────

def test_the_legacy_shared_alert_is_closed_on_the_first_run(db):
    db.add(PlatformAlert(alert_type="security_infra_degraded", company_id=None,
                         message="MFA unenrolment containment is degraded (ADR-387). trail …: AccessDeniedException",
                         severity="critical"))
    db.commit()
    _run(db)
    assert "security_infra_degraded" not in _open(db)


# ── D6 and robustness ──────────────────────────────────────────────────────

def test_the_result_names_each_check(db):
    r = _run(db, topic=["no subscribers"])
    assert set(r["checks"]) == {"trail", "responder", "topic", "containment", "pool_triggers",
                                "client_write_attributes"}   # ADR-558
    assert r["checks"]["topic"] == ["no subscribers"] and r["healthy"] is False


def test_one_crashing_check_does_not_stop_the_others(db):
    r = _run(db, crash=("trail",), pool_triggers=["PostAuthentication trigger is missing"])
    assert r["checks"]["trail"] == ["check crashed: RuntimeError"]
    assert set(_open(db)) == {"security_infra.trail", "security_infra.pool_triggers"}


def test_alert_types_fit_the_column():
    """alert_type is String(64)."""
    for name in ("trail", "responder", "topic", "containment", "pool_triggers"):
        assert len(h.ALERT_PREFIX + name) <= 64
