"""The slim stats series behind My Stats (ADR-271).

WHAT MUST NOT REGRESS

1. TODAY IS EXCLUDED. The whole caching design rests on the payload being
   immutable once fetched. If today leaks in, the client caches a number that
   is still moving — and a worker sees their performance change while looking
   at it.

2. DAMAGED IS ROLE-DEPENDENT and the two kinds are never summed.
   walker/trainee/trainer -> packages THEY brought back damaged.
   driver                 -> damage reported on their TRUCK.
   captain                -> both, separately, because a captain both delivers
                             and marks pre-route damage.
   `DAMAGE_STAGES` are all pre-delivery, so truck damage is a different event
   from on-route damage; "3 on route, 2 at load" is actionable, "5 damaged" is
   not.

3. DATED BY route_date, never completed_at. completed_at is nullable and null
   across existing data — the bug that made the old 4-week trend report 0 while
   lifetime showed 379 (ADR-270). Any regression to completed_at silently
   zeroes this whole surface.

4. Company scoping on every query, including the joins.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import ARRAY as GA, MetaData, create_engine
from sqlalchemy.dialects.postgresql import ARRAY as PA, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

for _T in (GA, PA, JSONB):
    compiles(_T, "sqlite")(lambda t, c, **kw: "JSON")


def _bind(self, dialect):
    import json
    return lambda v: None if v is None else json.dumps(v)


def _result(self, dialect, coltype=None):
    import json

    def p(v):
        if v is None or not isinstance(v, (str, bytes)):
            return v
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return p


for _T in (GA, PA, JSONB):
    _T.bind_processor = _bind
    _T.result_processor = _result

from app.models.company import Company  # noqa: E402
from app.models.delivery_stop import DeliveryStop  # noqa: E402
from app.models.rts import DamagedPackage, MissingPackage, RTSPackage  # noqa: E402
from app.models.walker_route import (  # noqa: E402
    MisroutedPackageFlag, Route, RouteParticipant,
)
from app.services.stats_series import (  # noqa: E402
    MAX_LOOKBACK_MONTHS, get_lifetime_totals, get_stats_series,
)
from tests.conftest import (  # noqa: E402
    DISPATCH_TABLES, SEED_COMPANY_ID, make_assignment, make_employee,
    make_member, make_truck,
)

OTHER_COMPANY_ID = uuid.UUID("b0000000-0000-0000-0000-000000000002")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    meta = MetaData()
    for table in DISPATCH_TABLES + [
        Route.__table__, RouteParticipant.__table__, DeliveryStop.__table__,
        MisroutedPackageFlag.__table__, RTSPackage.__table__,
        MissingPackage.__table__, DamagedPackage.__table__,
    ]:
        table.to_metadata(meta)
    meta.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Company(id=SEED_COMPANY_ID, name="Test Co", slug="t",
                        is_active=True))
    session.add(Company(id=OTHER_COMPANY_ID, name="Other", slug="o",
                        is_active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


_n = [0]


def _route(db, assignment, when, *, effort="standard", company_id=SEED_COMPANY_ID):
    _n[0] += 1
    r = Route(
        id=uuid.uuid4(), company_id=company_id, route_date=when,
        truck_assignment_id=assignment.id, route_number=_n[0],
        status="completed", package_count=0, capacity_limit=50,
        effort_class=effort, block_keys=[], tote_ids=[], tba_numbers=[],
        normalised_addresses=[], stops=[],
    )
    db.add(r); db.commit()
    return r


def _stop(db, route, *, total, rts, walker_id, company_id=SEED_COMPANY_ID):
    s = DeliveryStop(
        id=uuid.uuid4(), company_id=company_id, route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        block_key="W_37_St_500", tba_numbers=[], status="completed",
        stop_sequence=1, packages_total=total, packages_delivered=total - rts,
        rts_count=rts, missing_count=0, effort_class=route.effort_class,
        walker_id=walker_id,
        # Deliberately NULL: real data has it null, and the series must not
        # depend on it (ADR-270).
        completed_at=None,
    )
    db.add(s); db.commit()
    return s


def _rts(db, route, *, walker_id, rts_type="no_access", company_id=SEED_COMPANY_ID):
    r = RTSPackage(
        id=uuid.uuid4(), company_id=company_id, route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        tba_number=f"TBA{uuid.uuid4().hex[:10].upper()}",
        rts_type=rts_type, rts_explanation="seeded", is_reattemptable=True,
        walker_id=walker_id,
    )
    db.add(r); db.commit()
    return r


def _damaged(db, assignment, when, *, stage="truck_load",
             company_id=SEED_COMPANY_ID):
    d = DamagedPackage(
        id=uuid.uuid4(), company_id=company_id, route_date=when,
        tba_number=f"TBA{uuid.uuid4().hex[:10].upper()}",
        truck_assignment_id=assignment.id, stage=stage,
        damage_notes="seeded", resolution_status="pending",
    )
    db.add(d); db.commit()
    return d


def _day(db, emp, when, *, total=100, rts=5, effort="standard", role="walker"):
    truck = make_truck(db, name=f"T{_n[0]}")
    a = make_assignment(db, truck, target_date=when)
    make_member(db, a, emp, role)
    r = _route(db, a, when, effort=effort)
    _stop(db, r, total=total, rts=rts, walker_id=emp.id)
    return a, r


class TestTodayIsExcluded:
    def test_today_never_appears(self, db):
        """THE CACHE INVARIANT. Today's numbers are in flight; caching them
        means the reader watches their own stats change."""
        emp = make_employee(db, role="walker", name="W")
        _day(db, emp, date.today())
        _day(db, emp, date.today() - timedelta(days=1))

        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker")

        assert s.end_date == date.today() - timedelta(days=1)
        assert all(d.d != date.today() for d in s.days), (
            "today leaked into the cached series"
        )
        assert len(s.days) == 1

    def test_yesterday_is_included(self, db):
        """The counterpart: excluding today must not excise the newest real
        day, or the series is always a day staler than it looks."""
        emp = make_employee(db, role="walker", name="W2")
        yesterday = date.today() - timedelta(days=1)
        _day(db, emp, yesterday)

        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker")
        assert [d.d for d in s.days] == [yesterday]


class TestDatedByRouteDate:
    def test_stops_with_null_completed_at_still_count(self, db):
        """completed_at is null across real data. A regression to filtering on
        it silently zeroes this entire surface — which is exactly what happened
        to the 4-week trend (ADR-270)."""
        emp = make_employee(db, role="walker", name="W3")
        when = date.today() - timedelta(days=3)
        _day(db, emp, when, total=100, rts=7)

        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker")
        assert len(s.days) == 1
        assert s.days[0].delivered == 93
        assert s.days[0].total == 100
        assert s.days[0].rts == 7


class TestRoleDependentDamaged:
    def _setup(self, db, role):
        emp = make_employee(db, role=role, name=f"{role}-emp")
        when = date.today() - timedelta(days=2)
        a, r = _day(db, emp, when, role=role)
        # one package brought back damaged, one damaged on the truck
        _rts(db, r, walker_id=emp.id, rts_type="package_damaged")
        _damaged(db, a, when, stage="truck_load")
        return emp, when

    def test_walker_sees_own_damaged_only(self, db):
        emp, _ = self._setup(db, "walker")
        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker")
        assert s.days[0].damaged == 1
        assert s.days[0].truck_damaged == 0, (
            "a walker was credited with damage reported on the truck"
        )

    def test_driver_sees_truck_damaged_only(self, db):
        emp, _ = self._setup(db, "driver")
        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "driver")
        assert s.days[0].truck_damaged == 1
        assert s.days[0].damaged == 0, (
            "a driver was credited with on-route damage they did not carry"
        )

    def test_captain_sees_both_separately(self, db):
        """A captain both delivers and marks pre-route damage, so they get both
        figures — never summed, because they are different events."""
        emp, _ = self._setup(db, "captain")
        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "captain")
        assert s.days[0].damaged == 1
        assert s.days[0].truck_damaged == 1

    def test_damaged_is_a_subset_of_rts_not_an_addition(self, db):
        """package_damaged is one of the six RTS_TYPES. Reporting it as a
        separate total that ADDS to rts would double-count."""
        emp = make_employee(db, role="walker", name="Sub")
        when = date.today() - timedelta(days=4)
        a, r = _day(db, emp, when, total=100, rts=3)
        for t in ("package_damaged", "no_access", "business_closed"):
            _rts(db, r, walker_id=emp.id, rts_type=t)

        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker")
        assert s.days[0].rts == 3          # from the stop's rts_count
        assert s.days[0].damaged == 1      # a subset, not a fourth return


class TestTenantScoping:
    def test_another_companys_stops_do_not_count(self, db):
        """Single-tenant tests cannot see a scoping bug. The dangerous row is
        one carrying OUR employee's id under THEIR company_id."""
        emp = make_employee(db, role="walker", name="Scoped")
        when = date.today() - timedelta(days=5)
        _day(db, emp, when, total=50, rts=1)

        # foreign-company route + stop naming OUR employee
        truck = make_truck(db, name="Foreign")
        a = make_assignment(db, truck, target_date=when)
        fr = _route(db, a, when, company_id=OTHER_COMPANY_ID)
        _stop(db, fr, total=999, rts=99, walker_id=emp.id,
              company_id=OTHER_COMPANY_ID)

        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker")
        assert len(s.days) == 1
        assert s.days[0].total == 50, "a foreign company's stop was counted"


class TestWindow:
    def test_capped_at_the_max_lookback(self, db):
        emp = make_employee(db, role="walker", name="Old")
        s = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker", months=999)
        span_days = (s.end_date - s.start_date).days
        assert span_days <= MAX_LOOKBACK_MONTHS * 31 + 1


class TestLifetimeTotals:
    def test_lifetime_is_not_windowed(self, db):
        """'Lifetime' that silently meant 'the last 24 months' would be a lie,
        so the header is computed separately from the series."""
        emp = make_employee(db, role="walker", name="Life")
        _day(db, emp, date.today() - timedelta(days=400), total=100, rts=10)

        t = get_lifetime_totals(db, SEED_COMPANY_ID, emp.id, "walker")
        assert t.delivered == 90, "a day outside the series window was dropped"

    def test_success_pct_is_null_with_no_attempts(self, db):
        """Not 0.0 — 'no data' and '0% success' are different facts."""
        emp = make_employee(db, role="walker", name="Empty")
        t = get_lifetime_totals(db, SEED_COMPANY_ID, emp.id, "walker")
        assert t.success_pct is None
        assert t.delivered == 0


class TestEndpointScoping:
    """The endpoint's authorisation IS its signature (ADR-271).

    /me/stats takes no employee parameter, so there is nothing a caller could
    pass to read someone else's numbers. That is the same shape as
    /assignment-history/me, and it is worth pinning: adding an optional
    `employee_id` here would make the authorisation depend on whether a query
    parameter was supplied — the exact defect that left
    /dispatch/confirmations/history ungated (ADR-268).
    """

    def test_takes_no_employee_parameter(self):
        import inspect
        from app.routers.assignment_history import get_my_stats
        params = inspect.signature(get_my_stats).parameters
        assert "employee_id" not in params
        src = inspect.getsource(get_my_stats)
        assert "caller.id" in src and "caller.company_id" in src

    def test_months_is_bounded(self):
        """An unbounded window lets one request walk the whole table."""
        import inspect
        src = inspect.getsource(
            __import__("app.routers.assignment_history", fromlist=["x"]).get_my_stats
        )
        assert "ge=1" in src and "le=MAX_LOOKBACK_MONTHS" in src

    def test_role_comes_from_the_caller_not_the_request(self):
        """Damage attribution is role-dependent (ADR-271 F), so a
        client-supplied role would let a walker request a driver's truck-damage
        figures."""
        import inspect
        src = inspect.getsource(
            __import__("app.routers.assignment_history", fromlist=["x"]).get_my_stats
        )
        assert "caller.role" in src
        assert "role: str = Query" not in src


class TestYearStats:
    """All-time yearly aggregates for the LIFETIME chart (ADR-271 D2).

    Computed server-side rather than folded out of the daily series, because
    that series is capped at 24 months — a five-year employee would otherwise
    see two bars and a silent hole where their first three years were.
    """

    def test_groups_by_calendar_year(self, db):
        from app.services.stats_series import get_year_stats
        emp = make_employee(db, role="walker", name="Multi")
        _day(db, emp, date(2025, 3, 10), total=100, rts=5)
        _day(db, emp, date(2025, 9, 2), total=50, rts=1)
        _day(db, emp, date(2026, 2, 4), total=80, rts=2)

        ys = get_year_stats(db, SEED_COMPANY_ID, emp.id, "walker")
        by = {y.year: y for y in ys}
        assert by[2025].delivered == 95 + 49    # (100-5) + (50-1)
        assert by[2026].delivered == 78
        assert [y.year for y in ys] == [2025, 2026], "years must be oldest first"

    def test_reaches_beyond_the_series_window(self, db):
        """THE REASON THIS EXISTS. A day older than the 24-month daily cap must
        still appear in the yearly chart."""
        from app.services.stats_series import get_stats_series, get_year_stats
        emp = make_employee(db, role="walker", name="Veteran")
        old = date.today() - timedelta(days=1000)   # ~2.7 years back
        _day(db, emp, old, total=200, rts=10)

        series = get_stats_series(db, SEED_COMPANY_ID, emp.id, "walker")
        years = get_year_stats(db, SEED_COMPANY_ID, emp.id, "walker")

        assert all(d.d != old for d in series.days), "outside the 24mo cap"
        assert any(y.year == old.year and y.delivered == 190 for y in years), (
            "the yearly chart lost a year the daily series cannot reach"
        )

    def test_excludes_today(self, db):
        from app.services.stats_series import get_year_stats
        emp = make_employee(db, role="walker", name="TodayYear")
        _day(db, emp, date.today(), total=999, rts=0)

        ys = get_year_stats(db, SEED_COMPANY_ID, emp.id, "walker")
        cur = next((y for y in ys if y.year == date.today().year), None)
        assert cur is None or cur.delivered == 0, "today leaked into the year"
