"""Unregistered package intake decisions (ADR-246).

The rules under test, all from the operator:

  * Ownership is decided BEFORE routing — a package outside the company zone is
    not ours to deliver regardless of which route is nearest.
  * "Cannot decide" is a THIRD answer, distinct from "not ours". Without coords
    or a boundary we cannot prove a package is foreign, and declaring it so
    would strand a deliverable package.
  * A route that has departed cannot receive a package; it is absorbed into the
    closest route that can still accept it.
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
from app.models.company import Company, CompanyZone  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.models.truck import Truck  # noqa: E402
from app.models.truck_assignment import TruckAssignment  # noqa: E402
from app.models.walker_route import Route, RouteParticipant  # noqa: E402
from app.services.package_intake import (  # noqa: E402
    _ACCEPTING_STATUSES, check_zone, find_best_fit, load_company_boundary,
)

COMPANY = uuid.UUID("a0000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("a0000000-0000-0000-0000-0000000000ff")

# A square around midtown Manhattan, in GeoJSON (lng, lat) order.
_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [-74.00, 40.74], [-73.96, 40.74], [-73.96, 40.78], [-74.00, 40.78], [-74.00, 40.74],
    ]],
}


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(Company(id=COMPANY, name="Test Co", slug="t", is_active=True))
    s.add(Company(id=OTHER, name="Other", slug="o", is_active=True))
    s.commit()
    yield s
    s.close()
    eng.dispose()


def _zone(db, company=COMPANY, bounds=_SQUARE, active=True):
    z = CompanyZone(id=uuid.uuid4(), company_id=company, name="Zone",
                    bounds=bounds, is_active=active)
    db.add(z)
    db.commit()
    return z


def _walker(db, name="Walker", company=COMPANY):
    e = Employee(id=uuid.uuid4(), company_id=company, name=name, role="walker",
                 is_active=True, hr_system_id_adp=uuid.uuid4())
    db.add(e)
    db.commit()
    return e


def _route(db, when, *, number=1, status="assigned", blocks=None, addresses=None,
           executor=None, company=COMPANY):
    t = Truck(id=uuid.uuid4(), company_id=company, name=f"T{number}", is_active=True)
    db.add(t)
    db.commit()
    ta = TruckAssignment(id=uuid.uuid4(), company_id=company, truck_id=t.id,
                         date=when, status="planned")
    db.add(ta)
    db.commit()
    r = Route(id=uuid.uuid4(), company_id=company, route_date=when,
              truck_assignment_id=ta.id, route_number=number, status=status,
              package_count=10, capacity_limit=50,
              block_keys=blocks or [], tote_ids=[], tba_numbers=[],
              normalised_addresses=addresses or [], stops=[])
    db.add(r)
    db.commit()
    if executor:
        db.add(RouteParticipant(id=uuid.uuid4(), company_id=company, route_id=r.id,
                                employee_id=executor.id, role="executor"))
        db.commit()
        db.refresh(r)
    return r


class TestZoneOwnership:
    def test_inside_the_zone_is_ours(self, db):
        _zone(db)
        v = check_zone(db, COMPANY, lat=40.76, lng=-73.98)
        assert v.in_zone and v.decidable

    def test_outside_the_zone_is_not_ours(self, db):
        _zone(db)
        v = check_zone(db, COMPANY, lat=40.90, lng=-73.90)   # north of the square
        assert not v.in_zone and v.decidable
        assert v.reason == "outside"

    def test_missing_coords_is_undecidable_not_foreign(self, db):
        """THE distinction. Without coords we cannot prove a package is foreign,
        and saying so would strand a deliverable package — ADR-246 escalates
        these to dispatch instead."""
        _zone(db)
        v = check_zone(db, COMPANY, lat=None, lng=None)
        assert not v.decidable
        assert v.reason == "no_coords"
        assert not v.in_zone   # but decidable=False is what callers must branch on

    def test_no_boundary_configured_is_undecidable(self, db):
        v = check_zone(db, COMPANY, lat=40.76, lng=-73.98)
        assert not v.decidable
        assert v.reason == "no_boundary"

    def test_another_company_zone_does_not_apply(self, db):
        """Boundary lookup is company-scoped: another tenant's zone must not
        make our package in-zone."""
        _zone(db, company=OTHER)
        v = check_zone(db, COMPANY, lat=40.76, lng=-73.98)
        assert not v.decidable and v.reason == "no_boundary"

    def test_inactive_zone_is_ignored(self, db):
        _zone(db, active=False)
        v = check_zone(db, COMPANY, lat=40.76, lng=-73.98)
        assert not v.decidable

    def test_boundary_is_edge_buffered(self, db):
        """membership_boundary buffers the polygon (ADR-214): a package sitting
        exactly on the line belongs to us, rather than failing on a rounding
        error."""
        _zone(db)
        v = check_zone(db, COMPANY, lat=40.74, lng=-74.00)   # exact corner
        assert v.in_zone


class TestBestFit:
    def test_address_match_beats_block_match(self, db):
        """Same building is a stronger signal than same block."""
        today = date(2026, 8, 1)
        _route(db, today, number=1, blocks=["BLK1"])
        _route(db, today, number=2, addresses=["123 W 45 ST"], blocks=["BLK9"])

        a = find_best_fit(db, COMPANY, today, block_key="BLK1",
                          normalised_address="123 W 45 ST")
        assert a.best_fit.route_number == 2
        assert a.best_fit.match == "address"

    def test_block_match_when_no_address_match(self, db):
        today = date(2026, 8, 1)
        _route(db, today, number=1, blocks=["BLK1"])
        a = find_best_fit(db, COMPANY, today, block_key="BLK1", normalised_address="X")
        assert a.best_fit.route_number == 1
        assert a.best_fit.match == "block_key"

    def test_no_match_yields_no_best_fit(self, db):
        today = date(2026, 8, 1)
        _route(db, today, number=1, blocks=["BLK1"])
        a = find_best_fit(db, COMPANY, today, block_key="NOPE", normalised_address="NOPE")
        assert a.best_fit is None
        assert a.candidates == []

    def test_routes_from_other_days_are_excluded(self, db):
        _route(db, date(2026, 7, 31), number=1, blocks=["BLK1"])
        a = find_best_fit(db, COMPANY, date(2026, 8, 1), block_key="BLK1",
                          normalised_address=None)
        assert a.best_fit is None

    def test_other_company_routes_are_excluded(self, db):
        today = date(2026, 8, 1)
        _route(db, today, number=1, blocks=["BLK1"], company=OTHER)
        a = find_best_fit(db, COMPANY, today, block_key="BLK1", normalised_address=None)
        assert a.best_fit is None


class TestInProgressAbsorption:
    def test_departed_route_cannot_receive(self, db):
        """The operator's rule: if the best fit is already running, the package
        is absorbed into the closest route that can still accept it."""
        today = date(2026, 8, 1)
        _route(db, today, number=1, blocks=["BLK1"], status="in_progress")
        _route(db, today, number=2, blocks=["BLK1"], status="assigned")

        a = find_best_fit(db, COMPANY, today, block_key="BLK1", normalised_address=None)
        assert a.best_fit.route_number == 2
        assert a.absorbed_reason == "best_fit_in_progress:1"

    def test_no_accepting_route_is_reported(self, db):
        today = date(2026, 8, 1)
        _route(db, today, number=1, blocks=["BLK1"], status="completed")
        a = find_best_fit(db, COMPANY, today, block_key="BLK1", normalised_address=None)
        assert a.best_fit is None
        assert a.absorbed_reason == "no_accepting_route"

    def test_accepting_set_matches_the_model_lifecycle(self):
        """in_progress and completed must never accept a package."""
        assert "in_progress" not in _ACCEPTING_STATUSES
        assert "completed" not in _ACCEPTING_STATUSES
        assert "assigned" in _ACCEPTING_STATUSES

    def test_unknown_status_fails_closed(self, db):
        """The set lists what CAN accept, so an unrecognised status is not
        handed a package."""
        today = date(2026, 8, 1)
        _route(db, today, number=1, blocks=["BLK1"], status="some_new_state")
        a = find_best_fit(db, COMPANY, today, block_key="BLK1", normalised_address=None)
        assert a.best_fit is None


class TestAdderContext:
    def test_adders_own_route_is_identified(self, db):
        today = date(2026, 8, 1)
        w = _walker(db, "Rivera")
        _route(db, today, number=1, blocks=["BLK1"], executor=w)

        a = find_best_fit(db, COMPANY, today, block_key="BLK1",
                          normalised_address=None, adder_employee_id=w.id)
        assert a.adders_route is not None
        assert a.adders_route.is_adders_route
        assert a.adders_route.walker_name == "Rivera"

    def test_best_fit_may_not_be_the_adders_route(self, db):
        """This is the case that triggers the override warning."""
        today = date(2026, 8, 1)
        mine = _walker(db, "Mine")
        theirs = _walker(db, "Theirs")
        _route(db, today, number=1, blocks=["BLK9"], executor=mine)
        _route(db, today, number=2, addresses=["123 W 45 ST"], executor=theirs)

        a = find_best_fit(db, COMPANY, today, block_key="BLK9",
                          normalised_address="123 W 45 ST", adder_employee_id=mine.id)
        assert a.best_fit.walker_name == "Theirs"
        assert a.adders_route.walker_name == "Mine"
        assert not a.best_fit.is_adders_route
