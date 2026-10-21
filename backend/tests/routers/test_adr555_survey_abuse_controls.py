"""Survey abuse controls (ADR-555): rate limits, withdrawing a contributor's
records (append-only), and an alert on unusual volume.

Drives the real handlers on the ADR-513 fixtures (areas, claims, walks).
"""
import ast
import inspect
import pathlib
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import deps
from app.models.audit_log import AuditLog
from app.models.survey_register import (
    SurveyContributor, SurveyObservation, SurveyObservationWithdrawal, SurveyWithdrawal, live_observations,
)
from app.routers import survey_register as R
from app.services import survey_progress
from tests.routers.test_adr513_survey_areas import (  # noqa: F401  (fixtures + helpers)
    OWNER, _area, _block, _claim_and_walk, _record, _tables, city,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
SUB = "surveyor-sub-555"
W = R.Writer(sub=SUB, owner=False)


def _contributor(db):
    c = SurveyContributor(id=uuid.uuid4(), cognito_sub=SUB, display_name="Rogue", cognito_username="rogue",
                          agreement_version="v1", agreement_signed_on=date(2026, 10, 1))
    db.add(c); db.commit()
    return c


def _done_block(db):
    """A contributor walks a whole block, locking every door on it."""
    c = _contributor(db)
    area = _area(db)
    claim, walk = _claim_and_walk(db, W, area)
    for i in range(len(walk.addresses)):
        _record(db, W, walk, i)
    return c, area, walk


def _state(db, area):
    b = _block(db, area)
    return survey_progress.progress_for(db, b.borough, b.block_key, [], R._now()).state


def _withdraw(db, c, n, **over):
    today = date.today()
    body = {"from_date": today - timedelta(days=1), "to_date": today, "reason": "Account was hijacked overnight",
            "expected_count": n, **over}
    return R.withdraw_records(c.id, R.WithdrawIn(**body), owner=OWNER, db=db)


# ── D2: withdrawal ─────────────────────────────────────────────────────────

def test_withdrawing_reopens_the_doors_and_keeps_the_evidence(db):
    c, area, walk = _done_block(db)
    assert _state(db, area) == "done"
    n = len(walk.addresses)
    prev = R.preview_withdrawal(c.id, from_date=date.today() - timedelta(days=1), to_date=date.today(),
                                _owner=OWNER, db=db)
    assert prev.count == n
    out = _withdraw(db, c, n)
    assert out.count == n and out.blocks_affected == 1
    assert _state(db, area) == "open", "withdrawn records must stop locking their doors"
    assert db.query(SurveyObservation).count() == n, "append-only: the rows themselves remain"
    assert db.query(SurveyObservationWithdrawal).count() == n


def test_every_reader_stops_counting_withdrawn_records(db):
    c, area, walk = _done_block(db)
    _withdraw(db, c, len(walk.addresses))
    assert R.list_observations(bin=None, block_key=None, limit=100, writer=R.Writer(sub=OWNER["id"], owner=True), db=db) == []
    from app.models.survey_register import SurveyWalk
    out = R._walk_out(db, db.get(SurveyWalk, walk.id))
    assert out.block_state == "open" and out.recorded == []
    # The duplicate check no longer sees the withdrawn door, so it can be re-recorded honestly.
    assert db.query(SurveyObservation.id).filter(SurveyObservation.walk_id == walk.id, live_observations()).count() == 0


def test_a_stale_preview_cannot_take_more_than_was_shown(db):
    c, _area_, walk = _done_block(db)
    with pytest.raises(HTTPException) as exc:
        _withdraw(db, c, len(walk.addresses) - 1)
    assert exc.value.status_code == 409
    assert db.query(SurveyWithdrawal).count() == 0


def test_withdrawing_twice_finds_nothing_left(db):
    c, _a, walk = _done_block(db)
    _withdraw(db, c, len(walk.addresses))
    prev = R.preview_withdrawal(c.id, from_date=date.today() - timedelta(days=1), to_date=date.today(),
                                _owner=OWNER, db=db)
    assert prev.count == 0


@pytest.mark.parametrize("over,why", [
    ({"from_date": date(2026, 1, 2), "to_date": date(2026, 1, 1)}, "start after end"),
    ({"from_date": date(2024, 1, 1), "to_date": date(2026, 1, 1)}, "more than a year"),
    ({"expected_count": 0}, "nothing to withdraw"),
    ({"reason": "short"}, "a reason under 10 characters"),
])
def test_every_scope_is_required_and_bounded(over, why):
    body = {"from_date": date(2026, 1, 1), "to_date": date(2026, 1, 2), "reason": "Account was hijacked",
            "expected_count": 1, **over}
    with pytest.raises(ValidationError):
        R.WithdrawIn(**body)


def test_one_audit_row_per_batch_with_the_count(db):
    c, _a, walk = _done_block(db)
    out = _withdraw(db, c, len(walk.addresses))
    rows = db.query(AuditLog).filter(AuditLog.action_type == "survey.records.withdraw").all()
    assert len(rows) == 1 and rows[0].after_snapshot["count"] == out.count
    assert "address" not in str(rows[0].after_snapshot).lower(), "ids and counts only (ADR-493 D8)"


@pytest.mark.parametrize("fn", [R.withdraw_records, R.preview_withdrawal])
def test_only_a_super_admin_can_withdraw(fn):
    """Support helps people, never records (ADR-545)."""
    params = inspect.signature(fn).parameters
    dep = (params.get("owner") or params.get("_owner")).default
    assert dep.dependency is deps.get_super_admin


# ── D2: the completeness walk ──────────────────────────────────────────────

APP = ROOT / "backend" / "app"


def _queries_of_observations(path):
    """Every statement in `path` that calls .query(...) mentioning SurveyObservation."""
    tree = ast.parse(path.read_text())
    src = path.read_text()
    for stmt in ast.walk(tree):
        if not isinstance(stmt, (ast.Assign, ast.Return, ast.Expr, ast.AnnAssign, ast.AugAssign)):
            continue
        for call in ast.walk(stmt):
            if (isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "query"
                    and "SurveyObservation" in ast.get_source_segment(src, call)
                    and "SurveyObservationWithdrawal" not in ast.get_source_segment(src, call)):
                yield path.name, stmt.lineno, ast.get_source_segment(src, stmt)
                break


def test_the_walk_finds_the_readers():
    found = [q for p in APP.rglob("*.py") for q in _queries_of_observations(p)]
    assert len(found) >= 7, found   # six readers + the volume count + the withdrawal range


def test_every_query_of_observations_excludes_withdrawn_ones():
    """A reader that forgets the filter would keep counting withdrawn records --
    and keep their doors locked. The query that SELECTS records to withdraw is
    the one place it is allowed, and it applies the filter too (live only)."""
    missing = [f"{n}:{line}" for p in APP.rglob("*.py") for n, line, seg in _queries_of_observations(p)
               if "live_observations()" not in seg]
    assert not missing, "SurveyObservation queried without live_observations() (ADR-555): " + ", ".join(missing)


# ── D1: rate limits ────────────────────────────────────────────────────────

def test_locate_and_observation_writes_are_rate_limited():
    src = (APP / "routers" / "survey_register.py").read_text()
    assert '@limiter.limit("20/minute")\ndef survey_locate(' in src
    assert '@limiter.limit("60/minute")\ndef record_observation(' in src


def test_the_daily_account_cap_refuses_past_the_limit():
    r = MagicMock(); r.incr.side_effect = [1, 2, 3]
    with patch("app.core.security._get_redis", return_value=r):
        assert [R._account_daily_ok("s", "locate", 2) for _ in range(3)] == [True, True, False]
    r.expire.assert_called_once()


def test_the_daily_cap_fails_open_when_the_counter_is_down():
    with patch("app.core.security._get_redis", side_effect=ConnectionError("down")):
        assert R._account_daily_ok("s", "locate", 1) is True


def test_locate_over_the_cap_is_a_429():
    with patch.object(R, "_account_daily_ok", return_value=False):
        with pytest.raises(HTTPException) as exc:
            R.survey_locate.__wrapped__(request=None, address="1 Main St", borough="manhattan", writer=W)
    assert exc.value.status_code == 429


# ── D3: the volume alert ───────────────────────────────────────────────────

def test_a_burst_of_doors_raises_one_alert(db):
    with patch.object(R, "VOLUME_ALERT_AT", 3), \
         patch("app.services.integration_alerts.raise_platform_alert") as alert:
        _done_block(db)                                      # 3 doors in seconds
    kinds = [c.kwargs["alert_type"] for c in alert.call_args_list]
    assert "survey.volume_unusual" in kinds
    assert alert.call_args.kwargs["subject_ref"] == "rogue"


def test_normal_pace_raises_nothing(db):
    with patch("app.services.integration_alerts.raise_platform_alert") as alert:
        _done_block(db)
    assert not alert.called
