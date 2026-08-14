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
from app.models.shift_roll_call import ShiftRollCall  # noqa: E402
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
        ShiftRollCall.__table__,
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


class TestPeriodExtras:
    """Top blocks + attendance, SCOPED TO THE SELECTED PERIOD (ADR-271 I).

    The operator's requirement was explicit: "top 5 for week 1 may not be top 5
    for the month". A globally-computed ranking would be identical at every
    level and would tell a reader nothing about the period they are viewing.
    """

    def _stop_on(self, db, emp, when, block, *, total, rts):
        truck = make_truck(db, name=f"TB{_n[0]}")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        r = _route(db, a, when)
        s = DeliveryStop(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=r.id,
            truck_assignment_id=a.id, block_key=block, tba_numbers=[],
            status="completed", stop_sequence=1, packages_total=total,
            packages_delivered=total - rts, rts_count=rts, missing_count=0,
            effort_class="standard", walker_id=emp.id, completed_at=None,
        )
        db.add(s); db.commit()

    def test_blocks_are_scoped_to_the_period(self, db):
        """THE REQUIREMENT. A block worked only in week 1 must not appear in a
        week-2 query."""
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="Blocks")
        w1 = date.today() - timedelta(days=14)
        w2 = date.today() - timedelta(days=4)
        for _ in range(4):
            self._stop_on(db, emp, w1, "W_11_St_100", total=10, rts=1)
        for _ in range(4):
            self._stop_on(db, emp, w2, "W_99_St_900", total=10, rts=1)

        b1, _, _reasons = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                  w1 - timedelta(days=1), w1 + timedelta(days=1))
        b2, _, _reasons = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                  w2 - timedelta(days=1), w2 + timedelta(days=1))

        assert [b.block_key for b in b1] == ["W_11_St_100"]
        assert [b.block_key for b in b2] == ["W_99_St_900"], (
            "the block ranking is not scoped to the requested period"
        )

    def test_ranked_by_rts_rate_not_volume(self, db):
        """'Where do I struggle' is actionable; 'where do I go most' is not."""
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="Ranked")
        when = date.today() - timedelta(days=3)
        # High volume, clean record.
        for _ in range(5):
            self._stop_on(db, emp, when, "EASY_St_100", total=20, rts=0)
        # Lower volume, bad record.
        for _ in range(3):
            self._stop_on(db, emp, when, "HARD_St_200", total=10, rts=6)

        blocks, _, _reasons = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                      when - timedelta(days=1), when + timedelta(days=1))
        assert blocks[0].block_key == "HARD_St_200", (
            "ranked by volume instead of difficulty"
        )

    def test_thin_blocks_do_not_top_the_ranking(self, db):
        """One returned package on a single stop is not a pattern. Ranking it
        first would be actively misleading."""
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="Thin")
        when = date.today() - timedelta(days=5)
        self._stop_on(db, emp, when, "ONEOFF_St_100", total=1, rts=1)   # 100%
        for _ in range(4):
            self._stop_on(db, emp, when, "REAL_St_200", total=10, rts=3)  # 30%

        blocks, _, _reasons = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                      when - timedelta(days=1), when + timedelta(days=1))
        assert blocks[0].block_key == "REAL_St_200", (
            "a 1-stop block with a 100% rate was ranked above a real pattern"
        )

    def test_attendance_counts_and_rate(self, db):
        from app.models.shift_roll_call import ShiftRollCall
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="Attend")
        base = date.today() - timedelta(days=10)
        for i, st in enumerate(["present", "present", "present", "ncns", "late"]):
            db.add(ShiftRollCall(
                id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=emp.id,
                date=base + timedelta(days=i), status=st, confirmed=True,
            ))
        db.commit()

        _, att, _reasons = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                   base, base + timedelta(days=6))
        assert att.total == 5
        assert att.present == 3 and att.ncns == 1 and att.late == 1
        assert att.rate == 60.0

    def test_attendance_rate_is_none_with_no_roll_calls(self, db):
        """'No roll calls recorded' is not '0% attendance'."""
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="NoRoll")
        _, att, _reasons = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                   date.today() - timedelta(days=5), date.today())
        assert att.total == 0
        assert att.rate is None


class TestBlocksApplyByRole:
    """Blocks are meaningless for truck-scoped roles (ADR-271 I).

    They derive from DeliveryStop.walker_id — the EXECUTOR (ADR-244) — and a
    driver does not carry, so their list is permanently empty BY DESIGN. The
    response says so explicitly rather than leaving the client to infer
    "empty" from "not applicable": an empty panel reads as broken.

    Verified against staging: driver.test and captain.test return zero blocks
    at every period while showing 170 and 115 truck-damage rows respectively.
    """

    def test_truck_scoped_roles_are_flagged(self):
        import inspect
        from app.routers.assignment_history import get_my_period_extras
        src = inspect.getsource(get_my_period_extras)
        assert "blocks_apply=caller.role not in TRUCK_SCOPED_ROLES" in src

    def test_the_constant_is_the_shared_one(self):
        """Not a re-declared local list that could drift from ADR-256."""
        from app.services.constants import TRUCK_SCOPED_ROLES
        assert set(TRUCK_SCOPED_ROLES) == {"driver", "captain"}

    def test_a_walker_still_gets_blocks(self, db):
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="Carrier")
        when = date.today() - timedelta(days=3)
        truck = make_truck(db, name="TBK")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        r = _route(db, a, when)
        for i in range(4):
            db.add(DeliveryStop(
                id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=r.id,
                truck_assignment_id=a.id, block_key="W_1_St_100",
                tba_numbers=[], status="completed", stop_sequence=i + 1,
                packages_total=10, packages_delivered=8, rts_count=2,
                missing_count=0, effort_class="standard", walker_id=emp.id,
                completed_at=None,
            ))
        db.commit()

        blocks, _, _reasons = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                      when - timedelta(days=1), when + timedelta(days=1))
        assert [b.block_key for b in blocks] == ["W_1_St_100"]
        assert blocks[0].rts_rate == 0.2


class TestTruckScopedCounts:
    """A driver's counts come from THEIR TRUCK, not from walker_id (ADR-268).

    THE BUG THIS PINS. stats_series originally scoped every count by walker_id
    regardless of role. A driver never owns a stop — walker_id is the EXECUTOR
    (ADR-244) — so driver.test showed 0 delivered while the trucks they drove
    had delivered 256,733 packages. Every one of the 25 tests that existed at
    the time passed, because none of them opened the page as a driver.

    assignment_history had solved this from the start with TRUCK_SCOPED_ROLES;
    the new service simply did not carry the rule across.
    """

    def _truck_day(self, db, driver, carrier, when):
        truck = make_truck(db, name=f"TS{_n[0]}")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, driver, "driver")
        make_member(db, a, carrier, "walker")
        r = _route(db, a, when)
        # The CARRIER owns the stop; the driver owns nothing.
        _stop(db, r, total=100, rts=6, walker_id=carrier.id)
        return a

    def test_driver_sees_the_trucks_load(self, db):
        drv = make_employee(db, role="driver", name="Dee")
        wlk = make_employee(db, role="walker", name="Wanda")
        when = date.today() - timedelta(days=3)
        self._truck_day(db, drv, wlk, when)

        s = get_stats_series(db, SEED_COMPANY_ID, drv.id, "driver")
        assert len(s.days) == 1, "the driver's day vanished entirely"
        assert s.days[0].delivered == 94, (
            "driver scoped by walker_id — they own no stops, so this is 0"
        )
        assert s.days[0].rts == 6

    def test_walker_still_sees_only_their_own(self, db):
        """The counterpart: fixing the driver must not give walkers the whole
        truck, which would be the ADR-268 bug in reverse."""
        drv = make_employee(db, role="driver", name="Dee2")
        wlk = make_employee(db, role="walker", name="Wanda2")
        other = make_employee(db, role="walker", name="Otto")
        when = date.today() - timedelta(days=4)
        a = self._truck_day(db, drv, wlk, when)
        # A second carrier on the SAME truck, whose work is not Wanda's.
        make_member(db, a, other, "walker")
        r2 = _route(db, a, when)
        _stop(db, r2, total=500, rts=50, walker_id=other.id)

        s = get_stats_series(db, SEED_COMPANY_ID, wlk.id, "walker")
        assert s.days[0].delivered == 94, "a walker was given the truck's load"

    def test_lifetime_agrees_with_the_series(self, db):
        """A driver's lifetime total must not contradict the days that make it
        up — they are computed by separate queries and can drift apart."""
        drv = make_employee(db, role="driver", name="Dee3")
        wlk = make_employee(db, role="walker", name="Wanda3")
        for i in (3, 4, 5):
            self._truck_day(db, drv, wlk, date.today() - timedelta(days=i))

        s = get_stats_series(db, SEED_COMPANY_ID, drv.id, "driver")
        lt = get_lifetime_totals(db, SEED_COMPANY_ID, drv.id, "driver")
        assert lt.delivered == sum(d.delivered for d in s.days)


class TestPeriodReasons:
    """Why packages came back, scoped to the period AND the role (ADR-271 I).

    The mock's donut was fed by hardcoded data, so the endpoint shipped without
    reason support at all and the real UI had no donut for anyone. Caught by
    the operator asking where the driver's donut had gone.
    """

    def _rts_on(self, db, emp, when, rts_type, carrier=None):
        truck = make_truck(db, name=f"TR{_n[0]}")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, emp.role)
        owner = carrier or emp
        if carrier:
            make_member(db, a, carrier, "walker")
        r = _route(db, a, when)
        _stop(db, r, total=10, rts=1, walker_id=owner.id)
        _rts(db, r, walker_id=owner.id, rts_type=rts_type)
        return a

    def test_reasons_are_scoped_to_the_period(self, db):
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="Reasons")
        old = date.today() - timedelta(days=20)
        new = date.today() - timedelta(days=3)
        self._rts_on(db, emp, old, "no_access")
        self._rts_on(db, emp, new, "business_closed")

        _, _, r = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                    new - timedelta(days=1), new + timedelta(days=1),
                                    role="walker")
        assert [x.rts_type for x in r] == ["business_closed"], (
            "the reason mix is not scoped to the requested period"
        )

    def test_driver_sees_the_whole_trucks_reasons(self, db):
        """A driver's counts are truck-wide everywhere else; their donut must
        match, or it would sit empty beside an RTS figure in the thousands."""
        from app.services.stats_series import get_period_extras
        drv = make_employee(db, role="driver", name="DrvReason")
        wlk = make_employee(db, role="walker", name="WlkReason")
        when = date.today() - timedelta(days=4)
        self._rts_on(db, drv, when, "package_damaged", carrier=wlk)

        _, _, r = get_period_extras(db, SEED_COMPANY_ID, drv.id,
                                    when - timedelta(days=1), when + timedelta(days=1),
                                    role="driver")
        assert [x.rts_type for x in r] == ["package_damaged"], (
            "a driver's reason mix was scoped by walker_id and came back empty"
        )

    def test_sorted_commonest_first(self, db):
        from app.services.stats_series import get_period_extras
        emp = make_employee(db, role="walker", name="SortReason")
        when = date.today() - timedelta(days=5)
        for _ in range(3):
            self._rts_on(db, emp, when, "no_access")
        self._rts_on(db, emp, when, "inclement_weather")

        _, _, r = get_period_extras(db, SEED_COMPANY_ID, emp.id,
                                    when - timedelta(days=1), when + timedelta(days=1),
                                    role="walker")
        assert r[0].rts_type == "no_access" and r[0].count == 3
