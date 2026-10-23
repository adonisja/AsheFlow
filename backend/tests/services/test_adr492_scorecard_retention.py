"""ADR-492 — individual scorecards are kept 13 months unless a decision holds them.

Every branch of the purge is a row that must survive or must not, so these run
against real rows: a mock can confirm a filter was called, not that the held
scorecard is still there afterwards.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.scorecard import Scorecard, ScorecardMetric
from app.models.scorecard_appeal import ScorecardAppeal, ScorecardAppealItem
from app.models.scorecard_import import ScorecardImportPending
from app.routers import scorecards as sc_router
from app.schemas.scorecard import RetentionHoldIn
from app.tasks import cleanup
from tests.conftest import SEED_COMPANY_ID, make_employee, sqlite_mirror_with_defaults


@pytest.fixture(autouse=True)
def _tables(db):
    for model in (Scorecard, ScorecardMetric, ScorecardAppeal, ScorecardAppealItem, ScorecardImportPending):
        sqlite_mirror_with_defaults(model.__table__).create(db.get_bind())


def _week(days_ago: int) -> str:
    y, w, _ = (date.today() - timedelta(days=days_ago)).isocalendar()
    return f"{y}-W{w:02d}"


OLD, RECENT = _week(420), _week(30)     # past the 396-day window / well inside it


def _card(db, emp, week, scope="individual", **kw):
    sc = Scorecard(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, week=week, scope=scope,
                   employee_id=emp.id if scope == "individual" else None, **kw)
    db.add(sc)
    db.add(ScorecardMetric(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, scorecard_id=sc.id,
                           key="dcr", label="DCR", value="99%", sort_order=0))
    db.commit()
    return sc


def _appeal(db, sc, status):
    a = ScorecardAppeal(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, scorecard_id=sc.id,
                        week=sc.week, scope=sc.scope, status=status)
    db.add(a)
    db.add(ScorecardAppealItem(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, appeal_id=a.id,
                               metric_key="dcr", metric_label="DCR"))
    db.commit()
    return a


def _purge(db, **settings):
    s = {"scorecard_retention_days": 396, "scorecard_pending_retention_days": 56, **settings}
    with patch.object(cleanup, "SessionLocal", return_value=db), patch.object(db, "close"), \
         patch.multiple(cleanup.settings, **s):
        return cleanup.purge_expired_scorecards()


def _exists(db, sc):
    # The identity key, not `sc.id`: after expire_all, reading an attribute of a
    # row the purge deleted raises ObjectDeletedError instead of answering.
    from sqlalchemy import inspect
    sid = inspect(sc).identity[0]
    db.expire_all()
    return db.query(Scorecard).filter_by(id=sid).first() is not None


@pytest.fixture
def emp(db):
    return make_employee(db, role="driver", name="DA")


class TestTheThirteenMonthWindow:
    def test_an_old_individual_scorecard_and_its_children_are_deleted(self, db, emp):
        old = _card(db, emp, OLD)
        _appeal(db, old, "lost")                       # resolved: does not hold
        out = _purge(db)
        assert not _exists(db, old)
        assert out["scorecards"] == 1 and out["metrics"] == 1
        assert out["appeals"] == 1 and out["appeal_items"] == 1
        assert db.query(ScorecardMetric).count() == 0, "children deleted explicitly, not left orphaned"

    def test_a_recent_scorecard_is_kept(self, db, emp):
        recent = _card(db, emp, RECENT)
        _purge(db)
        assert _exists(db, recent)

    def test_company_scorecards_are_exempt(self, db, emp):
        company = _card(db, emp, OLD, scope="company")
        _purge(db)
        assert _exists(db, company)

    def test_an_unparseable_week_is_kept_and_counted(self, db, emp):
        weird = _card(db, emp, "not-a-week")
        out = _purge(db)
        assert _exists(db, weird) and out["unparseable_weeks_kept"] == 1

    def test_zero_disables_the_window(self, db, emp):
        old = _card(db, emp, OLD)
        _purge(db, scorecard_retention_days=0)
        assert _exists(db, old)


class TestWhatStopsTheClock:
    def test_a_dated_hold_in_the_future_keeps_it(self, db, emp):
        held = _card(db, emp, OLD, retention_hold_until=date.today() + timedelta(days=10))
        _purge(db)
        assert _exists(db, held)

    def test_a_lapsed_hold_does_not(self, db, emp):
        lapsed = _card(db, emp, OLD, retention_hold_until=date.today() - timedelta(days=1))
        _purge(db)
        assert not _exists(db, lapsed)

    def test_an_indefinite_hold_keeps_it(self, db, emp):
        held = _card(db, emp, OLD, retention_hold_indefinite=True)
        _purge(db)
        assert _exists(db, held)

    @pytest.mark.parametrize("status", ["draft", "submitted"])
    def test_an_open_appeal_keeps_it(self, db, emp, status):
        disputed = _card(db, emp, OLD)
        _appeal(db, disputed, status)
        _purge(db)
        assert _exists(db, disputed)


class TestUnmatchedImports:
    def _pending(self, db, tid, days_ago):
        db.add(ScorecardImportPending(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, week=_week(days_ago), transporter_id=tid,
            payload={}, reason="unknown_transporter_id",
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago)))
        db.commit()

    def test_grouped_by_id_on_the_newest_row(self, db):
        self._pending(db, "GONE", 70)
        self._pending(db, "GONE", 63)
        self._pending(db, "STILL", 90)   # old row ...
        self._pending(db, "STILL", 7)    # ... but the ID was seen last week
        out = _purge(db)
        left = {r.transporter_id for r in db.query(ScorecardImportPending)}
        assert left == {"STILL"} and db.query(ScorecardImportPending).count() == 2
        assert out["pending_ids"] == 1 and out["pending_rows"] == 2


class TestDeclaringAHold:
    def _mgr(self, db):
        return make_employee(db, role="management", name="Mgr")

    def _set(self, db, sc, mgr, **body):
        return sc_router.set_retention_hold(scorecard_id=sc.id, body=RetentionHoldIn(**body),
                                            caller=mgr, _={}, db=db)

    def test_personnel_decision_holds_one_year_from_the_decision(self, db, emp):
        mgr, sc = self._mgr(db), _card(db, emp, RECENT)
        decided = date.today() - timedelta(days=20)
        out = self._set(db, sc, mgr, kind="personnel_decision", decision_date=decided)
        assert out["retention_hold_until"] == decided + timedelta(days=365)
        assert db.query(AuditLog).filter_by(action_type="scorecard.retention_hold.set").count() == 1

    def test_a_hold_cannot_be_shortened(self, db, emp):
        mgr, sc = self._mgr(db), _card(db, emp, RECENT)
        self._set(db, sc, mgr, kind="personnel_decision", decision_date=date.today())
        with pytest.raises(HTTPException) as exc:
            self._set(db, sc, mgr, kind="personnel_decision", decision_date=date.today() - timedelta(days=100))
        assert exc.value.status_code == 409

    def test_legal_charge_is_indefinite_and_outranks_a_date(self, db, emp):
        mgr, sc = self._mgr(db), _card(db, emp, RECENT)
        assert self._set(db, sc, mgr, kind="legal_charge")["retention_hold_indefinite"] is True
        with pytest.raises(HTTPException) as exc:
            self._set(db, sc, mgr, kind="personnel_decision", decision_date=date.today())
        assert exc.value.status_code == 409

    def test_company_scorecards_cannot_be_held(self, db, emp):
        mgr, sc = self._mgr(db), _card(db, emp, RECENT, scope="company")
        with pytest.raises(HTTPException) as exc:
            self._set(db, sc, mgr, kind="legal_charge")
        assert exc.value.status_code == 422

    def test_release(self, db, emp):
        mgr, sc = self._mgr(db), _card(db, emp, RECENT)
        self._set(db, sc, mgr, kind="legal_charge")
        out = sc_router.release_retention_hold(scorecard_id=sc.id, caller=mgr, _={}, db=db)
        assert out["retention_hold_indefinite"] is False and out["retention_hold_until"] is None
        with pytest.raises(HTTPException) as exc:
            sc_router.release_retention_hold(scorecard_id=sc.id, caller=mgr, _={}, db=db)
        assert exc.value.status_code == 409

    # ADR-573: dates are computed when the TEST runs, not when the module is
    # imported. A decorator argument is evaluated at collection, so a run that
    # crossed midnight UTC made "tomorrow" today and the future-date case passed.
    @pytest.mark.parametrize("make_body", [
        lambda: {"kind": "personnel_decision"},                                           # no date
        lambda: {"kind": "personnel_decision", "decision_date": date.today() + timedelta(days=1)},  # future
        lambda: {"kind": "legal_charge", "decision_date": date.today()},                  # date on the wrong kind
        lambda: {"kind": "legal_charge", "note": "x"},                                    # extra="forbid"
    ], ids=["no-date", "future", "date-on-wrong-kind", "extra-field"])
    def test_the_request_is_validated(self, make_body):
        with pytest.raises(ValidationError):
            RetentionHoldIn(**make_body())


class TestNothingElseCanDeleteAHeldScorecard:
    def test_manual_delete_is_refused(self, db, emp):
        mgr = make_employee(db, role="management", name="Mgr")
        sc = _card(db, emp, RECENT, retention_hold_indefinite=True)
        with pytest.raises(HTTPException) as exc:
            sc_router.delete_scorecard(scorecard_id=sc.id, caller=mgr, _={}, db=db)
        assert exc.value.status_code == 409 and _exists(db, sc)

    def test_employee_hard_delete_is_refused_before_cognito(self, db, emp):
        """Scorecard.employee_id is ON DELETE CASCADE. The guard must fire before
        the Cognito user is deleted, or a refused delete leaves a login-less
        employee behind."""
        from app.routers import employees
        admin = make_employee(db, role="admin", name="Admin")
        _card(db, emp, RECENT, retention_hold_until=date.today() + timedelta(days=5))
        with patch.object(employees, "_cognito_revoke_access") as revoke, \
             patch.object(employees, "_cognito_client") as client:
            with pytest.raises(HTTPException) as exc:
                employees.delete_employee(employee_id=emp.id, current_user={}, caller=admin, db=db)
        assert exc.value.status_code == 409
        revoke.assert_not_called()
        client.assert_not_called()


class TestTheRetentionScreen:
    """D5 — what management sees before deciding to hold."""

    def _rows(self, db, emp):
        mgr = make_employee(db, role="management", name="Mgr")
        return {r.week: r for r in sc_router.individual_retention_records(
            employee_id=emp.id, caller=mgr, _={}, db=db)}

    def test_removed_after_is_week_start_plus_the_window(self, db, emp):
        _card(db, emp, RECENT)
        row = self._rows(db, emp)[RECENT]
        monday = cleanup._iso_week_monday(RECENT)
        assert row.removed_after == monday + timedelta(days=396)

    def test_a_later_hold_moves_the_date_and_an_indefinite_one_clears_it(self, db, emp):
        far = date.today() + timedelta(days=900)
        _card(db, emp, RECENT, retention_hold_until=far)
        _card(db, emp, OLD, retention_hold_indefinite=True)
        rows = self._rows(db, emp)
        assert rows[RECENT].removed_after == far
        assert rows[OLD].removed_after is None

    def test_an_open_appeal_is_flagged(self, db, emp):
        sc = _card(db, emp, RECENT)
        _appeal(db, sc, "submitted")
        assert self._rows(db, emp)[RECENT].open_appeal is True

    def test_another_companys_scorecards_are_invisible(self, db, emp):
        """Dimension 1: the employee_id alone must not reach across tenants."""
        foreign = Scorecard(id=uuid.uuid4(), company_id=uuid.uuid4(), week=RECENT,
                            scope="individual", employee_id=emp.id)
        db.add(foreign)
        db.commit()
        assert self._rows(db, emp) == {}
