"""Dashboard summary aggregation tests.

These pin the two properties that the Phase 1/2 implementation got wrong and
that no import check can catch:

  1. UNITS. Success and rework rates are PACKAGE-denominated. The original
     divided delivered packages by STOP count, which silently inflates the rate
     whenever a stop carries more than one package.

  2. HONESTY. A metric with no source data returns None, never 0.0. The
     original shipped hardcoded values (inspection items, db_health, escalation
     reasons, trends) that presented as real measurements. "0% on-time" reads
     as a crisis; "unknown" must stay unknown.

The shared `db` fixture in conftest only builds DISPATCH_TABLES and cannot
create JSONB/ARRAY columns, so this module defines its own session that
registers SQLite compilers for those types and builds the FULL model metadata.
That keeps the tests running against the real ORM models rather than a
hand-maintained subset that could drift from production.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import ARRAY as GenericARRAY, create_engine
from sqlalchemy.dialects.postgresql import ARRAY as PgARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# SQLite has neither ARRAY nor JSONB. Two things are needed, and the DDL half
# alone is not enough: `compiles` lets CREATE TABLE render, but binding a Python
# list still raises "type 'list' is not supported" at INSERT. Registering a
# bind processor on the dialect impl serializes list/dict to JSON text so the
# real Postgres models can be exercised unmodified.
for _T in (GenericARRAY, PgARRAY, JSONB):
    compiles(_T, "sqlite")(lambda t, c, **kw: "JSON")


def _json_bind(self, dialect):
    import json

    def process(value):
        return None if value is None else json.dumps(value)

    return process


def _json_result(self, dialect, coltype=None):
    import json

    def process(value):
        if value is None or not isinstance(value, (str, bytes)):
            return value
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value

    return process


for _T in (GenericARRAY, PgARRAY, JSONB):
    _T.bind_processor = _json_bind
    _T.result_processor = _json_result

from app.models.base import Base  # noqa: E402
from app.models.company import Company, CompanyConfig  # noqa: E402
from app.models.delivery_stop import DeliveryStop  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.models.field_ops import Departure, VehicleInspection, WalkerRating  # noqa: E402
from app.models.incident import Incident  # noqa: E402
from app.models.shift_roll_call import ShiftRollCall  # noqa: E402
from app.models.truck import Truck  # noqa: E402
from app.models.truck_assignment import TruckAssignment  # noqa: E402
from app.models.walker_route import Route  # noqa: E402
from app.services.dashboard_summaries import (  # noqa: E402
    _pct,
    _trend,
    get_admin_dashboard_summary,
    get_dispatch_dashboard_summary,
    get_management_dashboard_summary,
    get_trainer_dashboard_summary,
)

COMPANY = uuid.UUID("a0000000-0000-0000-0000-000000000001")
OTHER_COMPANY = uuid.UUID("a0000000-0000-0000-0000-0000000000ff")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Company(id=COMPANY, name="Test Co", slug="test-co", is_active=True))
    session.add(Company(id=OTHER_COMPANY, name="Other Co", slug="other-co", is_active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _config(db, shift_end: time | None = time(18, 0)):
    db.add(CompanyConfig(id=uuid.uuid4(), company_id=COMPANY,
                         is_configured=True, shift_end=shift_end))
    db.commit()


def _employee(db, name="Walker One", role="walker", company=COMPANY, active=True):
    e = Employee(id=uuid.uuid4(), company_id=company, name=name, role=role,
                 is_active=active, hr_system_id_adp=uuid.uuid4())
    db.add(e)
    db.commit()
    return e


def _assignment(db, when: date, company=COMPANY, status="active", name="T1"):
    """Route.truck_assignment_id is NOT NULL, so a route needs a real parent."""
    t = Truck(id=uuid.uuid4(), company_id=company, name=name, is_active=True)
    db.add(t)
    db.commit()
    ta = TruckAssignment(id=uuid.uuid4(), company_id=company, truck_id=t.id,
                         date=when, status=status)
    db.add(ta)
    db.commit()
    return ta


def _route(db, when: date, *, status="completed", departed=None, returned=None,
           packages=100, company=COMPANY, number=1, assignment=None):
    ta = assignment or _assignment(db, when, company=company,
                                   name=f"T{number}-{uuid.uuid4().hex[:4]}")
    r = Route(id=uuid.uuid4(), company_id=company, route_date=when,
              truck_assignment_id=ta.id,
              route_number=number, status=status, package_count=packages,
              capacity_limit=packages,   # nullable=False, no default
              departed_at=departed, returned_at=returned,
              block_keys=[], tote_ids=[], tba_numbers=[],
              normalised_addresses=[], stops=[])
    db.add(r)
    db.commit()
    return r


def _stop(db, route, *, delivered, total, rts=0, missing=0, when=None,
          started=None, walker=None, company=COMPANY, seq=1, status="completed"):
    s = DeliveryStop(
        id=uuid.uuid4(), company_id=company, route_id=route.id,
        truck_assignment_id=uuid.uuid4(),
        walker_id=walker.id if walker else None,
        block_key=f"BLK{seq}", tba_numbers=[], status=status,
        stop_sequence=seq, packages_total=total, packages_delivered=delivered,
        rts_count=rts, missing_count=missing,
        started_at=started, completed_at=when or datetime(2026, 7, 20, 12, 0),
    )
    db.add(s)
    db.commit()
    return s


# ── unit helpers ──────────────────────────────────────────────────────────────

class TestHelpers:
    def test_pct_returns_none_for_zero_denominator(self):
        """Not 0.0 — dividing by nothing yields an unknown, not a zero."""
        assert _pct(5, 0) is None
        assert _pct(0, 0) is None
        assert _pct(5, None) is None

    def test_pct_computes_normally(self):
        assert _pct(1, 4) == 25.0
        assert _pct(0, 4) == 0.0        # a real measured zero

    def test_trend_none_when_no_prior_data(self):
        """The original hardcoded 'flat', asserting stability it never measured."""
        assert _trend(5.0, None) is None
        assert _trend(None, 5.0) is None
        assert _trend(5.0, 0) is None

    @pytest.mark.parametrize("cur,prior,expected", [
        (11.0, 10.0, "up"),
        (9.0, 10.0, "down"),
        (10.1, 10.0, "flat"),   # inside the 2% tolerance band
    ])
    def test_trend_directions(self, cur, prior, expected):
        assert _trend(cur, prior) == expected


# ── the unit bug ──────────────────────────────────────────────────────────────

class TestPackageDenominatedRates:
    def test_success_rate_uses_packages_not_stops(self, db):
        """2 stops, 100 packages assigned, 75 delivered -> 75%.

        Stop-denominated (the original bug) would give 75/2 = 3750%.
        """
        _config(db)
        r = _route(db, date(2026, 7, 20))
        _stop(db, r, delivered=50, total=60, seq=1)
        _stop(db, r, delivered=25, total=40, seq=2)

        s = get_management_dashboard_summary(db, COMPANY, period="month")
        assert s.operational.total_packages_delivered == 75
        assert s.operational.total_packages_assigned == 100
        assert s.operational.delivery_success_rate_pct == 75.0

    def test_rework_rate_uses_packages(self, db):
        _config(db)
        r = _route(db, date(2026, 7, 20))
        _stop(db, r, delivered=90, total=100, rts=7, missing=3)

        s = get_management_dashboard_summary(db, COMPANY, period="month")
        assert s.operational.total_rework_count == 10
        assert s.operational.rework_rate_pct == 10.0


# ── honesty ───────────────────────────────────────────────────────────────────

class TestNoFabricatedValues:
    def test_empty_company_yields_none_not_zero(self, db):
        _config(db)
        op = get_management_dashboard_summary(db, COMPANY, period="week").operational

        assert op.packages_per_hour is None
        assert op.delivery_success_rate_pct is None
        assert op.rework_rate_pct is None
        assert op.completion_rate_pct is None
        assert op.avg_minutes_per_stop is None
        assert op.trend_packages_per_hour is None
        assert op.paid_hours_source == "none"
        # Counts are genuinely zero — those are measured, not unknown.
        assert op.total_packages_delivered == 0
        assert op.routes_dispatched == 0

    def test_failed_inspection_items_are_empty_not_hardcoded(self, db):
        """The original returned [{'Tires',3},{'Lights',2}] regardless of data."""
        _config(db)
        items = get_admin_dashboard_summary(db, COMPANY).compliance.failed_items_trending
        assert items == []

    def test_failed_items_read_real_jsonb(self, db):
        _config(db)
        # One inspection per driver/date/type is enforced by a unique constraint,
        # so three failures means three different drivers.
        for i in range(3):
            d = _employee(db, f"Driver {i}", "driver")
            db.add(VehicleInspection(
                id=uuid.uuid4(), company_id=COMPANY, driver_id=d.id,
                date=date.today(), inspection_type="pre_trip",
                items={"Tires": False, "Lights": True, "Brakes": False},
                has_failures=True, submitted_at=datetime.now(timezone.utc),
            ))
        db.commit()

        items = get_admin_dashboard_summary(db, COMPANY).compliance.failed_items_trending
        counts = {i.item_name: i.failure_count for i in items}
        assert counts.get("Tires") == 3
        assert counts.get("Brakes") == 3
        assert "Lights" not in counts        # it passed, so never counted

    def test_trainer_escalations_not_hardcoded_reason(self, db):
        """The original stamped 'incomplete_training' on every escalation row."""
        _config(db)
        t = _employee(db, "Trainer", "trainer")
        perf = get_trainer_dashboard_summary(db, COMPANY, t.id).performance
        assert perf.problem_areas == []
        assert perf.ready_for_solo == []
        assert perf.trainee_feedback_about_me.avg_rating is None


# ── on-time, per the locked definition ────────────────────────────────────────

class TestOnTimeDefinition:
    def test_none_when_shift_end_unconfigured(self, db):
        """No reference time means on-time is unknowable — not 0%."""
        _config(db, shift_end=None)
        _route(db, date(2026, 7, 20),
               departed=datetime(2026, 7, 20, 9, 0),
               returned=datetime(2026, 7, 20, 17, 0))

        s = get_management_dashboard_summary(db, COMPANY, period="month")
        assert s.operational.on_time_rate_pct is None
        assert s.operational.on_time_reference is None

    def test_returned_before_shift_end_is_on_time(self, db):
        _config(db, shift_end=time(18, 0))
        _route(db, date(2026, 7, 20), number=1,
               departed=datetime(2026, 7, 20, 9, 0),
               returned=datetime(2026, 7, 20, 17, 30))
        _route(db, date(2026, 7, 20), number=2,
               departed=datetime(2026, 7, 20, 9, 0),
               returned=datetime(2026, 7, 20, 19, 15))   # late

        s = get_management_dashboard_summary(db, COMPANY, period="month")
        assert s.operational.on_time_rate_pct == 50.0
        assert s.operational.on_time_reference == "18:00"

    def test_completion_and_on_time_are_distinct(self, db):
        """Both routes complete, one returns late: completion 100%, on-time 50%."""
        _config(db, shift_end=time(18, 0))
        _route(db, date(2026, 7, 20), number=1, status="completed",
               departed=datetime(2026, 7, 20, 9, 0),
               returned=datetime(2026, 7, 20, 17, 0))
        _route(db, date(2026, 7, 20), number=2, status="completed",
               departed=datetime(2026, 7, 20, 9, 0),
               returned=datetime(2026, 7, 20, 20, 0))

        op = get_management_dashboard_summary(db, COMPANY, period="month").operational
        assert op.completion_rate_pct == 100.0
        assert op.on_time_rate_pct == 50.0


# ── route timing reads Route, not TruckAssignment ─────────────────────────────

class TestRouteTiming:
    def test_duration_from_route_timestamps(self, db):
        """TruckAssignment has neither created_at nor updated_at; the original
        subtracted those two non-existent columns."""
        _config(db)
        _route(db, date(2026, 7, 20),
               departed=datetime(2026, 7, 20, 8, 0),
               returned=datetime(2026, 7, 20, 14, 30))

        fleet = get_management_dashboard_summary(db, COMPANY, period="month").fleet
        assert fleet.route_avg_duration_hours == 6.5
        assert fleet.routes_with_timing == 1

    def test_untimed_routes_excluded(self, db):
        _config(db)
        _route(db, date(2026, 7, 20), departed=None, returned=None)
        fleet = get_management_dashboard_summary(db, COMPANY, period="month").fleet
        assert fleet.route_avg_duration_hours is None
        assert fleet.routes_with_timing == 0


# ── attendance comes from roll call ───────────────────────────────────────────

class TestRollCallAttendance:
    def test_ncns_is_the_no_show_signal(self, db):
        """There is no NoShow model — a no-show is ShiftRollCall.status=='ncns'
        (ADR-200/201)."""
        _config(db)
        w = _employee(db, "Absent Walker", "walker")
        for d, status in [(date(2026, 7, 20), "ncns"),
                          (date(2026, 7, 21), "ncns"),
                          (date(2026, 7, 22), "late"),
                          (date(2026, 7, 23), "present")]:
            db.add(ShiftRollCall(id=uuid.uuid4(), company_id=COMPANY,
                                 employee_id=w.id, submitted_by_id=w.id,
                                 date=d, status=status, confirmed=True))
        db.commit()

        crew = get_management_dashboard_summary(db, COMPANY, period="month").crew
        assert [(n.employee_name, n.count) for n in crew.no_shows_this_period] == \
               [("Absent Walker", 2)]
        trouble = {t.employee_name: t for t in crew.trouble_walkers}
        assert trouble["Absent Walker"].ncns_count == 2
        assert trouble["Absent Walker"].late_count == 1

    def test_confirmed_pct(self, db):
        _config(db)
        w = _employee(db)
        for d, conf in [(date(2026, 7, 20), True), (date(2026, 7, 21), True),
                        (date(2026, 7, 22), False), (date(2026, 7, 23), False)]:
            db.add(ShiftRollCall(id=uuid.uuid4(), company_id=COMPANY,
                                 employee_id=w.id, submitted_by_id=w.id,
                                 date=d, status="present", confirmed=conf))
        db.commit()

        crew = get_management_dashboard_summary(db, COMPANY, period="month").crew
        assert crew.roll_call_total == 4
        assert crew.roll_call_confirmed_pct == 50.0


# ── graduation, per the locked definition ─────────────────────────────────────

class TestGraduationDefinition:
    def test_none_when_no_training_history(self, db):
        _config(db)
        assert get_admin_dashboard_summary(db, COMPANY).compliance.graduation_completion_pct is None

    def test_active_trainee_counted_by_role(self, db):
        _config(db)
        _employee(db, "T1", "trainee")
        _employee(db, "T2", "trainee")
        _employee(db, "Inactive", "trainee", active=False)
        _employee(db, "W1", "walker")

        assert get_admin_dashboard_summary(db, COMPANY).compliance.active_trainee_count == 2


# ── multi-tenancy (CLAUDE.md Dimension 1) ─────────────────────────────────────

class TestCompanyScoping:
    def test_other_company_data_never_leaks(self, db):
        _config(db)
        mine = _route(db, date(2026, 7, 20), packages=10, company=COMPANY)
        _stop(db, mine, delivered=10, total=10, company=COMPANY, seq=1)

        theirs = _route(db, date(2026, 7, 20), packages=999,
                        company=OTHER_COMPANY, number=99)
        _stop(db, theirs, delivered=999, total=999, company=OTHER_COMPANY, seq=2)

        op = get_management_dashboard_summary(db, COMPANY, period="month").operational
        assert op.total_packages_delivered == 10
        assert op.total_packages_assigned == 10
        assert op.routes_dispatched == 1

    def test_incidents_scoped(self, db):
        _config(db)
        for company, sev in [(COMPANY, "critical"), (OTHER_COMPANY, "critical"),
                             (OTHER_COMPANY, "warning")]:
            r = _employee(db, f"R-{company}-{sev}", "driver", company=company)
            db.add(Incident(id=uuid.uuid4(), company_id=company, reporter_id=r.id,
                            date=date(2026, 7, 20), category="vehicle",
                            severity=sev, description="x", resolved=False,
                            created_at=datetime(2026, 7, 20, 10, 0)))
        db.commit()

        inc = get_management_dashboard_summary(db, COMPANY, period="month").incidents
        assert inc.total_period == 1
        assert inc.by_severity == {"critical": 1}


# ── dispatch snapshot ─────────────────────────────────────────────────────────

class TestDispatchSnapshot:
    def test_avg_packages_is_per_truck_not_per_stop(self, db):
        """The original averaged packages_delivered per STOP and labelled the
        result per-truck."""
        _config(db)
        # Exactly one active truck, so per-truck vs per-stop is unambiguous.
        ta = _assignment(db, date(2026, 7, 20), status="active")
        r = _route(db, date(2026, 7, 20), assignment=ta)
        for i in range(4):
            _stop(db, r, delivered=25, total=25, seq=i + 1,
                  when=datetime(2026, 7, 20, 12, 0))

        snap = get_dispatch_dashboard_summary(db, COMPANY, "2026-07-20").fleet_snapshot
        assert snap.trucks_active == 1
        assert snap.packages_delivered == 100
        assert snap.avg_packages_per_active_truck == 100.0   # per-stop would be 25

    def test_no_trucks_yields_none_not_zero(self, db):
        _config(db)
        snap = get_dispatch_dashboard_summary(db, COMPANY, "2026-07-20").fleet_snapshot
        assert snap.trucks_active == 0
        assert snap.avg_packages_per_active_truck is None

    def test_baseline_none_without_history(self, db):
        _config(db)
        perf = get_dispatch_dashboard_summary(db, COMPANY, "2026-07-20").performance
        assert perf.baseline_minutes_per_package is None
        assert perf.baseline_sample_size == 0

    def test_baseline_normalizes_per_package(self, db):
        """Baseline is minutes-per-package, so route size does not distort it.
        block_keys is an ARRAY, which is why per-block attribution was rejected.
        """
        _config(db)
        target = date(2026, 7, 20)
        # 2h for 100 packages and 4h for 200 both = 1.2 min/package
        _route(db, target - timedelta(days=2), packages=100, number=1,
               departed=datetime(2026, 7, 18, 9, 0),
               returned=datetime(2026, 7, 18, 11, 0))
        _route(db, target - timedelta(days=1), packages=200, number=2,
               departed=datetime(2026, 7, 19, 9, 0),
               returned=datetime(2026, 7, 19, 13, 0))

        perf = get_dispatch_dashboard_summary(db, COMPANY, target.isoformat()).performance
        assert perf.baseline_sample_size == 2
        assert perf.baseline_minutes_per_package == pytest.approx(1.2, abs=0.01)


# ── paid hours source ─────────────────────────────────────────────────────────

class TestPaidHours:
    def test_falls_back_to_departures_and_reports_source(self, db):
        """Source is reported so the client can disclose provenance rather than
        implying payroll-grade hours."""
        _config(db)
        e = _employee(db, "Driver", "driver")
        db.add(Departure(id=uuid.uuid4(), company_id=COMPANY, employee_id=e.id,
                         date=date(2026, 7, 20),
                         departed_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
                         returned_at=datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc)))
        db.commit()

        op = get_management_dashboard_summary(db, COMPANY, period="month").operational
        assert op.total_paid_hours == 8.0
        assert op.paid_hours_source == "departures"

    def test_packages_per_hour_derived_from_hours(self, db):
        _config(db)
        e = _employee(db, "Driver", "driver")
        db.add(Departure(id=uuid.uuid4(), company_id=COMPANY, employee_id=e.id,
                         date=date(2026, 7, 20),
                         departed_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
                         returned_at=datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)))
        db.commit()
        r = _route(db, date(2026, 7, 20))
        _stop(db, r, delivered=150, total=150)

        op = get_management_dashboard_summary(db, COMPANY, period="month").operational
        assert op.total_paid_hours == 10.0
        assert op.packages_per_hour == 15.0
