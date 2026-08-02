"""ARRAY/JSONB columns must be REASSIGNED, never mutated in place.

These models carry no MutableList/MutableDict, so `col.append(x)`, `col.pop()`
and friends change the in-memory list and are SILENTLY DISCARDED at commit.

This is not hypothetical. walker_routes.split_pair used `route.tote_ids.pop()`
to move an overflow tote to the trainer's route: the destination gained the bag
by reassignment, the source's removal was dropped, so the bag ended up on BOTH
routes while the source's slot_cost and package_count were decremented for a
tote it never lost. The split is called from the mobile trainer screen and,
because the route is built at 1.5x paired capacity and the split clears
capacity_limit_paired, the overflow branch is the NORMAL path — not an edge case.

The existing test_pair_split suite passed throughout, because it builds routes
as SimpleNamespace mocks where `.pop()` genuinely mutates. A mock cannot catch
this class of bug: it needs a real session, a flush, and a reload.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import ARRAY as GA, create_engine
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

from app.models.base import Base  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.truck import Truck  # noqa: E402
from app.models.truck_assignment import TruckAssignment  # noqa: E402
from app.models.walker_route import Route  # noqa: E402

COMPANY = uuid.UUID("a0000000-0000-0000-0000-000000000001")
DAY = date(2026, 8, 1)


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(Company(id=COMPANY, name="Test Co", slug="t", is_active=True))
    s.commit()
    yield s
    s.close()
    eng.dispose()


def _route(db, totes, number=1):
    # trucks are unique on (company_id, name) and routes on
    # (truck_assignment_id, route_number) — both must vary per call.
    t = Truck(id=uuid.uuid4(), company_id=COMPANY,
              name=f"T{number}-{uuid.uuid4().hex[:4]}", is_active=True)
    db.add(t)
    db.commit()
    ta = TruckAssignment(id=uuid.uuid4(), company_id=COMPANY, truck_id=t.id,
                         date=DAY, status="planned")
    db.add(ta)
    db.commit()
    r = Route(id=uuid.uuid4(), company_id=COMPANY, route_date=DAY,
              truck_assignment_id=ta.id, route_number=number, status="assigned",
              package_count=len(totes), capacity_limit=50,
              block_keys=[], tote_ids=list(totes), tba_numbers=[],
              normalised_addresses=[], stops=[])
    db.add(r)
    db.commit()
    return r


class TestInPlaceMutationIsDiscarded:
    """Pins the trap itself, so the reassignment idiom is not 'cleaned up'
    into a simpler-looking in-place call by a future reader."""

    def test_pop_does_not_persist(self, db):
        r = _route(db, ["B1", "B2", "B3"])
        r.tote_ids.pop()
        db.commit()
        db.expire_all()

        reloaded = db.query(Route).filter(Route.id == r.id).first()
        assert reloaded.tote_ids == ["B1", "B2", "B3"], (
            "in-place pop unexpectedly persisted — if this now passes, a "
            "MutableList was added and the reassignment idiom can be relaxed"
        )

    def test_append_does_not_persist(self, db):
        r = _route(db, ["B1"])
        r.tote_ids.append("B2")
        db.commit()
        db.expire_all()
        assert db.query(Route).filter(Route.id == r.id).first().tote_ids == ["B1"]


class TestReassignmentPersists:
    def test_slice_reassignment_removes(self, db):
        """The idiom split_pair now uses."""
        r = _route(db, ["B1", "B2", "B3"])
        moved = r.tote_ids[-1]
        r.tote_ids = list(r.tote_ids[:-1])
        db.commit()
        db.expire_all()

        reloaded = db.query(Route).filter(Route.id == r.id).first()
        assert moved == "B3"
        assert reloaded.tote_ids == ["B1", "B2"]

    def test_concat_reassignment_adds(self, db):
        r = _route(db, ["B1"])
        r.tote_ids = list(r.tote_ids or []) + ["B2"]
        db.commit()
        db.expire_all()
        assert db.query(Route).filter(Route.id == r.id).first().tote_ids == ["B1", "B2"]

    def test_a_move_between_routes_is_not_duplicated(self, db):
        """The exact split_pair scenario: the bag must leave the source AND
        arrive at the destination. The bug left it on both."""
        src = _route(db, ["B1", "B2", "B3"])
        dst = _route(db, ["X1"], number=2)

        moved = src.tote_ids[-1]
        src.tote_ids = list(src.tote_ids[:-1])
        dst.tote_ids = list(dst.tote_ids or []) + [moved]
        db.commit()
        db.expire_all()

        src2 = db.query(Route).filter(Route.id == src.id).first()
        dst2 = db.query(Route).filter(Route.id == dst.id).first()
        assert moved not in src2.tote_ids, "bag still on the source route"
        assert moved in dst2.tote_ids
        assert src2.tote_ids.count(moved) + dst2.tote_ids.count(moved) == 1


class TestJsonbSameRule:
    def test_stops_in_place_append_is_discarded(self, db):
        r = _route(db, ["B1"])
        r.stops.append({"address": "1 MAIN ST", "tba_numbers": []})
        db.commit()
        db.expire_all()
        assert db.query(Route).filter(Route.id == r.id).first().stops == []

    def test_stops_reassignment_persists(self, db):
        r = _route(db, ["B1"])
        r.stops = list(r.stops or []) + [{"address": "1 MAIN ST", "tba_numbers": []}]
        db.commit()
        db.expire_all()
        assert len(db.query(Route).filter(Route.id == r.id).first().stops) == 1
