"""sync_adp_pay_periods + the detection guard it repairs (ADR-233).

adp_pay_periods had no write path anywhere in the codebase. detect_timecard_mismatches
resolves a pay period per timecard and `continue`s when none covers the work_date —
a guard sitting ahead of every comparison branch. With the table empty that skip fired
for every timecard, so detection had never created an adjustment while still returning
{"status": "ok"}.

These tests pin: the parsers, the NOT NULL guard on incomplete ADP entries, upsert
(never delete, because timecard_adjustments.pay_period_id is a RESTRICT FK), and that
detection is gated off by default.
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── parsers ──────────────────────────────────────────────────────────────────

def test_parse_date_accepts_iso_and_datetime_prefix():
    from app.tasks import adp_pay_period_sync as m
    assert m._parse_date("2026-07-01") == date(2026, 7, 1)
    # ADP sometimes returns a full timestamp where a date is documented
    assert m._parse_date("2026-07-01T00:00:00Z") == date(2026, 7, 1)


@pytest.mark.parametrize("bad", [None, "", "not-a-date", "07/01/2026", 12345])
def test_parse_date_returns_none_on_unusable(bad):
    from app.tasks import adp_pay_period_sync as m
    assert m._parse_date(bad) is None


def test_parse_datetime_handles_z_suffix():
    """ADP emits 'Z'; fromisoformat rejects it before Python 3.11."""
    from app.tasks import adp_pay_period_sync as m
    got = m._parse_datetime("2026-07-16T23:59:59Z")
    assert got == datetime(2026, 7, 16, 23, 59, 59, tzinfo=timezone.utc)


def test_parse_datetime_forces_tz_aware():
    """close_deadline is compared against datetime.now(timezone.utc);
    a naive value would raise TypeError at comparison time."""
    from app.tasks import adp_pay_period_sync as m
    got = m._parse_datetime("2026-07-16T23:59:59")
    assert got.tzinfo is not None
    assert got.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("bad", [None, "", "nope"])
def test_parse_datetime_returns_none_on_unusable(bad):
    from app.tasks import adp_pay_period_sync as m
    assert m._parse_datetime(bad) is None


# ── task behaviour ───────────────────────────────────────────────────────────

def _integration():
    integ = MagicMock()
    integ.company_id = uuid.uuid4()
    integ.is_enabled = True
    integ.adp_payroll_group_id = "PG-001"
    integ.last_pay_period_sync_at = None
    return integ


def _db_with(integration, existing=None):
    """Session returning `integration` for ADPIntegration and `existing` for lookups."""
    from app.models.adp_integration import ADPIntegration

    db = MagicMock()

    def _query(model):
        q = MagicMock()
        if model is ADPIntegration:
            q.filter.return_value.all.return_value = [integration]
        else:
            q.filter.return_value.first.return_value = existing
        return q

    db.query = _query
    return db


def _run(db, payload):
    from app.tasks import adp_pay_period_sync as m
    with patch.object(m, "SessionLocal", return_value=db), \
         patch.object(m, "fetch_adp_pay_periods", return_value=payload):
        return m.sync_adp_pay_periods()


COMPLETE = {
    "payPeriodID": "PP-202607-01",
    "startDate": "2026-07-01",
    "endDate": "2026-07-15",
    "payDate": "2026-07-20",
    "closeDeadline": "2026-07-16T23:59:59Z",
}


def test_creates_pay_period_from_complete_entry():
    from app.models.adp_pay_period import ADPPayPeriod

    integ = _integration()
    db = _db_with(integ, existing=None)
    out = _run(db, [COMPLETE])

    assert out["status"] == "ok"
    assert out["companies"][str(integ.company_id)] == {
        "created": 1, "updated": 0, "skipped": 0,
    }

    added = [c.args[0] for c in db.add.call_args_list]
    assert len(added) == 1
    row = added[0]
    assert isinstance(row, ADPPayPeriod)
    assert row.company_id == integ.company_id
    assert row.adp_pay_period_id == "PP-202607-01"
    assert row.period_start == date(2026, 7, 1)
    assert row.period_end == date(2026, 7, 15)
    assert row.pay_date == date(2026, 7, 20)
    assert row.close_deadline.tzinfo is not None


def test_accepts_camelcase_id_variant():
    """Field casing is unverified against Workforce Now; accept both spellings."""
    integ = _integration()
    db = _db_with(integ, existing=None)
    entry = {**COMPLETE}
    del entry["payPeriodID"]
    entry["payPeriodId"] = "PP-ALT"

    out = _run(db, [entry])
    assert out["companies"][str(integ.company_id)]["created"] == 1
    assert db.add.call_args_list[0].args[0].adp_pay_period_id == "PP-ALT"


@pytest.mark.parametrize("missing", ["payPeriodID", "startDate", "endDate", "payDate", "closeDeadline"])
def test_skips_incomplete_entry_rather_than_writing_partial_row(missing):
    """Every ADPPayPeriod column is NOT NULL — a partial row would fail the
    insert and abort the whole company's batch."""
    integ = _integration()
    db = _db_with(integ, existing=None)

    entry = {k: v for k, v in COMPLETE.items() if k != missing}
    out = _run(db, [entry])

    assert out["companies"][str(integ.company_id)] == {
        "created": 0, "updated": 0, "skipped": 1,
    }
    db.add.assert_not_called()


def test_one_bad_entry_does_not_discard_the_good_ones():
    integ = _integration()
    db = _db_with(integ, existing=None)
    bad = {k: v for k, v in COMPLETE.items() if k != "payDate"}

    out = _run(db, [bad, COMPLETE])

    assert out["companies"][str(integ.company_id)] == {
        "created": 1, "updated": 0, "skipped": 1,
    }


def test_updates_existing_row_and_never_deletes_it():
    """timecard_adjustments.pay_period_id is a RESTRICT FK — deleting a
    referenced period raises rather than cascading."""
    integ = _integration()
    existing = MagicMock()
    existing.adp_pay_period_id = "STALE"
    db = _db_with(integ, existing=existing)

    out = _run(db, [COMPLETE])

    assert out["companies"][str(integ.company_id)] == {
        "created": 0, "updated": 1, "skipped": 0,
    }
    db.add.assert_not_called()
    db.delete.assert_not_called()
    assert existing.adp_pay_period_id == "PP-202607-01"
    assert existing.period_end == date(2026, 7, 15)


def test_stamps_sync_cursor():
    integ = _integration()
    db = _db_with(integ, existing=None)
    _run(db, [COMPLETE])
    assert integ.last_pay_period_sync_at is not None


def test_one_company_failure_does_not_block_others():
    from app.models.adp_integration import ADPIntegration
    from app.tasks import adp_pay_period_sync as m

    a, b = _integration(), _integration()
    db = MagicMock()

    def _query(model):
        q = MagicMock()
        if model is ADPIntegration:
            q.filter.return_value.all.return_value = [a, b]
        else:
            q.filter.return_value.first.return_value = None
        return q
    db.query = _query

    def _fetch(integration):
        if integration is a:
            raise RuntimeError("ADP unreachable")
        return [COMPLETE]

    with patch.object(m, "SessionLocal", return_value=db), \
         patch.object(m, "fetch_adp_pay_periods", side_effect=_fetch):
        out = m.sync_adp_pay_periods()

    assert str(a.company_id) not in out["companies"]
    assert out["companies"][str(b.company_id)]["created"] == 1
    db.rollback.assert_called_once()
    db.close.assert_called_once()


def test_no_payroll_group_yields_no_writes():
    """fetch returns [] when adp_payroll_group_id is unset; the task must not
    invent rows to fill the gap."""
    integ = _integration()
    integ.adp_payroll_group_id = None
    db = _db_with(integ, existing=None)

    out = _run(db, [])

    assert out["companies"][str(integ.company_id)] == {
        "created": 0, "updated": 0, "skipped": 0,
    }
    db.add.assert_not_called()


# ── the P0 guard this task repairs ───────────────────────────────────────────

def test_detection_is_gated_off_by_default():
    """Populating adp_pay_periods takes detection from zero adjustments/day to
    real volume; the first historical pass can notify a large batch of employees.
    New and existing integrations both start gated."""
    from app.models.adp_integration import ADPIntegration

    col = ADPIntegration.__table__.c.mismatch_detection_enabled
    assert col.nullable is False
    assert col.default.arg is False


def test_detection_skips_company_when_gate_is_off():
    """Populating adp_pay_periods takes detection from zero findings/day to real
    volume, and the first historical pass can notify a large batch of employees.
    Detection stays off per company until an operator has reviewed a dry-run
    count (ADR-233).
    """
    from app.models.adp_integration import ADPIntegration
    from app.models.flex_timesheets import FlexTimesheet
    from app.tasks import adp_mismatch_detect as m

    integ = MagicMock()
    integ.company_id = uuid.uuid4()
    integ.is_enabled = True
    integ.mismatch_detection_enabled = False

    db = MagicMock()
    queried = []

    def _query(model, *a, **k):
        q = MagicMock()
        if model is ADPIntegration:
            q.filter.return_value.all.return_value = [integ]
        else:
            queried.append(model)
            q.filter.return_value.all.return_value = []
        return q
    db.query = _query

    with patch.object(m, "SessionLocal", return_value=db), \
         patch.object(m, "fetch_company_timezones", return_value={}):
        out = m.detect_timecard_mismatches()

    assert out == {"status": "ok", "findings_opened": 0}
    # gated off before any Flex record is read — no findings, no notifications
    assert FlexTimesheet not in queried
    db.add.assert_not_called()
