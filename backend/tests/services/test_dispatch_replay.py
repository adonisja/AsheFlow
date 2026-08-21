"""Dispatch's read-only reconstruction of a past day (ADR-268).

THE THING THIS PROTECTS
A driver's line is the whole truck's load; a walker's is their own stops. Both
appear in the same crew list, so the day total MUST be summed from the truck
rows — adding the crew lines together counts every package twice, once on the
walker who carried it and again on the driver who answers for it.

Measured on staging: crew lines summed to 5,730 against a real day total of
2,865. Exactly double, because one driver duplicates the load.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import ARRAY as GA, MetaData, create_engine
from sqlalchemy.dialects.postgresql import ARRAY as PA, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# Route/DeliveryStop use Postgres ARRAY/JSONB. Shimmed locally rather than in
# conftest — a global compiler override changes every other suite.
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
from app.models.rts import RTSPackage  # noqa: E402
from app.models.walker_route import (  # noqa: E402
    MisroutedPackageFlag, Route, RouteParticipant,
)
from app.services.dispatch_replay import get_day_replay  # noqa: E402
from tests.conftest import (  # noqa: E402
    DISPATCH_TABLES, SEED_COMPANY_ID, make_assignment, make_employee,
    make_member, make_truck,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    meta = MetaData()
    for table in DISPATCH_TABLES + [
        Route.__table__, DeliveryStop.__table__, RTSPackage.__table__,
        RouteParticipant.__table__, MisroutedPackageFlag.__table__,
    ]:
        table.to_metadata(meta)
    meta.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Company(id=SEED_COMPANY_ID, name="Test Co", slug="t", is_active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _route(db, assignment, when, *, number=1, effort="standard"):
    r = Route(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_date=when,
        truck_assignment_id=assignment.id, route_number=number,
        status="completed", package_count=0, capacity_limit=50,
        effort_class=effort, block_keys=[], tote_ids=[], tba_numbers=[],
        normalised_addresses=[], stops=[],
    )
    db.add(r); db.commit()
    return r


def _stop(db, route, *, total, rts, seq, walker_id):
    s = DeliveryStop(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        block_key="W_37_St_500", tba_numbers=[], status="completed",
        stop_sequence=seq, packages_total=total, packages_delivered=total - rts,
        rts_count=rts, missing_count=0, effort_class="standard",
        walker_id=walker_id,
    )
    db.add(s); db.commit()
    return s


def _one_truck_day(db, when):
    """One truck: a driver and two walkers, 100 packages between the walkers."""
    drv = make_employee(db, role="driver", name="The Driver")
    w1 = make_employee(db, role="walker", name="Walker One")
    w2 = make_employee(db, role="walker", name="Walker Two")
    truck = make_truck(db, name="Eagle")
    a = make_assignment(db, truck, target_date=when)
    make_member(db, a, drv, "driver")
    make_member(db, a, w1, "walker")
    make_member(db, a, w2, "walker")
    r = _route(db, a, when)
    _stop(db, r, total=40, rts=2, seq=1, walker_id=w1.id)
    _stop(db, r, total=60, rts=5, seq=2, walker_id=w2.id)
    return drv, w1, w2, a, r


class TestDoubleCounting:
    def test_the_day_total_is_the_truck_total_not_the_crew_sum(self, db):
        """THE invariant. A driver's line already contains the whole load, so
        summing crew lines double-counts every package."""
        when = date.today() - timedelta(days=3)
        _one_truck_day(db, when)
        rep = get_day_replay(db, SEED_COMPANY_ID, when)

        assert rep.packages_total == 100
        crew_sum = sum(m.packages_total for t in rep.trucks for m in t.crew)
        assert crew_sum == 200, "driver duplicates the load — that is expected"
        assert rep.packages_total != crew_sum, (
            "the day total was summed from crew lines and double-counts"
        )

    def test_the_truck_total_is_the_load(self, db):
        when = date.today() - timedelta(days=3)
        _one_truck_day(db, when)
        t = get_day_replay(db, SEED_COMPANY_ID, when).trucks[0]
        assert t.packages_total == 100
        assert t.packages_delivered == 93        # 100 - 7 rts
        assert t.rts_count == 7


class TestPerMemberScope:
    def test_a_driver_line_is_the_whole_truck(self, db):
        when = date.today() - timedelta(days=3)
        _one_truck_day(db, when)
        t = get_day_replay(db, SEED_COMPANY_ID, when).trucks[0]
        drv = next(m for m in t.crew if m.slot_role == "driver")
        assert drv.packages_total == 100
        assert drv.is_truck_lead is True

    def test_a_walker_line_is_their_own_stops(self, db):
        when = date.today() - timedelta(days=3)
        _one_truck_day(db, when)
        t = get_day_replay(db, SEED_COMPANY_ID, when).trucks[0]
        w1 = next(m for m in t.crew if m.name == "Walker One")
        w2 = next(m for m in t.crew if m.name == "Walker Two")
        assert (w1.packages_total, w1.rts_count) == (40, 2)
        assert (w2.packages_total, w2.rts_count) == (60, 5)
        assert w1.is_truck_lead is False

    def test_leads_sort_first(self, db):
        """A dispatcher scanning for 'who had a rough day' reads top-down."""
        when = date.today() - timedelta(days=3)
        _one_truck_day(db, when)
        t = get_day_replay(db, SEED_COMPANY_ID, when).trucks[0]
        assert t.crew[0].is_truck_lead is True


class TestReasons:
    def test_rts_reasons_are_counted_by_type(self, db):
        when = date.today() - timedelta(days=3)
        _drv, w1, _w2, _a, r = _one_truck_day(db, when)
        for t in ("no_access", "no_access", "business_closed"):
            db.add(RTSPackage(
                id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=r.id,
                truck_assignment_id=r.truck_assignment_id,
                tba_number=f"TBA{uuid.uuid4().hex[:8]}", rts_type=t,
                rts_explanation="x", is_reattemptable=True, walker_id=w1.id,
            ))
        db.commit()
        truck = get_day_replay(db, SEED_COMPANY_ID, when).trucks[0]
        assert truck.rts_reasons == {"no_access": 2, "business_closed": 1}


class TestEmptyAndTenancy:
    def test_a_day_that_never_ran_is_empty_not_an_error(self, db):
        rep = get_day_replay(db, SEED_COMPANY_ID, date.today() - timedelta(days=99))
        assert rep.trucks == []
        assert rep.packages_total == 0

    def test_a_planned_but_unworked_day_reports_zeros(self, db):
        """Trucks assigned, nothing delivered. Zeros are the honest answer —
        the crew was rostered even though the day produced nothing."""
        when = date.today() - timedelta(days=3)
        e = make_employee(db, role="driver", name="Rostered")
        truck = make_truck(db, name="Idle")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, e, "driver")
        rep = get_day_replay(db, SEED_COMPANY_ID, when)
        assert len(rep.trucks) == 1
        assert rep.trucks[0].packages_total == 0
        assert len(rep.trucks[0].crew) == 1

    def test_another_companys_day_is_never_returned(self, db):
        when = date.today() - timedelta(days=3)
        _one_truck_day(db, when)
        rep = get_day_replay(db, uuid.uuid4(), when)
        assert rep.trucks == []
