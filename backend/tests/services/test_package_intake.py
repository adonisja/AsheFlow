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
from sqlalchemy import ARRAY as GA, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import BinaryExpression, CollectionAggregate
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


@event.listens_for(Engine, "connect")
def _register_json_contains(dbapi_conn, _rec):
    """Membership helper for the `.any()` shim below.

    Arrays round-trip as JSON strings under the processors above, so testing
    membership is a parse plus an `in`.
    """
    import json

    def _contains(haystack, needle):
        if haystack is None:
            return False
        try:
            values = json.loads(haystack) if isinstance(haystack, (str, bytes)) else haystack
        except (ValueError, TypeError):
            return False
        return needle in (values or [])

    dbapi_conn.create_function("_json_contains", 2, _contains)


@compiles(BinaryExpression, "sqlite")
def _compile_any_for_sqlite(element, compiler, **kw):
    """Rewrite Postgres `x = ANY(col)` into a SQLite membership call.

    `Route.tba_numbers.any(needle)` is the right production construct — it is
    native Postgres and can use a GIN index, unlike the
    `array_to_string(...) ILIKE` trick package_lookup uses to get suffix
    matching. But it compiles to `? = ANY(tba_numbers)`, which SQLite cannot
    parse: the tests here raise OperationalError rather than returning a wrong
    answer, so the duplicate guard would otherwise be untestable.

    Note the arity trap: `ANY` takes the *column* as its only argument and the
    needle sits on the other side of the `=`, so registering a two-argument
    SQLite function named ANY fails with "wrong number of arguments". The
    rewrite has to happen at compile time, where both operands are visible.

    This changes only what the TEST database runs. Production still emits
    `= ANY(...)`, and that SQL is exercised for real only against Postgres.
    """
    if isinstance(element.right, CollectionAggregate):
        needle = compiler.process(element.left, **kw)
        column = compiler.process(element.right.element, **kw)
        return f"_json_contains({column}, {needle})"
    return compiler.visit_binary(element, **kw)

from app.models.base import Base  # noqa: E402
from app.models.company import Company, CompanyZone  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.models.truck import Truck  # noqa: E402
from app.models.truck_assignment import TruckAssignment  # noqa: E402
from app.models.walker_route import Route, RouteParticipant  # noqa: E402
from app.models.delivery_stop import DeliveryStop  # noqa: E402
from app.models.tote_ops import PackageRemoval  # noqa: E402
from app.services.package_intake import (  # noqa: E402
    _ACCEPTING_STATUSES, attach_to_route, check_duplicate, check_zone,
    create_foreign_removal, find_best_fit, load_company_boundary,
    resolve_address,
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



class TestAttachToRoute:
    """The write path. ARRAY and JSONB columns must be REASSIGNED — these models
    have no MutableList, so an in-place append is silently discarded at commit.
    """

    def _attach(self, db, route, tba="TBA999", block="BLK1", addr="1 MAIN ST"):
        w = _walker(db, "Executor")
        rec = _walker(db, "Recorder")
        return attach_to_route(
            db, route, tba=tba, block_key=block, normalised_address=addr,
            company_id=COMPANY, executor_id=w.id, executor_name=w.name,
            recorded_by=rec.id, recorded_by_name=rec.name,
        )

    def test_tba_lands_on_the_route_after_commit(self, db):
        """The regression that matters: an in-place append would pass in memory
        and vanish on reload."""
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        self._attach(db, r)
        db.commit()
        db.expire_all()

        reloaded = db.query(Route).filter(Route.id == r.id).first()
        assert "TBA999" in reloaded.tba_numbers

    def test_package_count_increments(self, db):
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        before = r.package_count
        self._attach(db, r)
        db.commit()
        assert r.package_count == before + 1

    def test_geography_is_attached(self, db):
        """Without this the stop exists but the route card never shows it."""
        r = _route(db, date(2026, 8, 1), blocks=[], addresses=[])
        self._attach(db, r, block="BLK7", addr="9 NEW ST")
        db.commit()
        db.expire_all()

        reloaded = db.query(Route).filter(Route.id == r.id).first()
        assert "BLK7" in reloaded.block_keys
        assert "9 NEW ST" in reloaded.normalised_addresses
        assert any(s["address"] == "9 NEW ST" for s in reloaded.stops)

    def test_second_package_at_same_address_merges_the_stop(self, db):
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        self._attach(db, r, tba="TBA1", addr="1 MAIN ST")
        self._attach(db, r, tba="TBA2", addr="1 MAIN ST")
        db.commit()
        db.expire_all()

        reloaded = db.query(Route).filter(Route.id == r.id).first()
        entries = [s for s in reloaded.stops if s["address"] == "1 MAIN ST"]
        assert len(entries) == 1, "same address should merge, not duplicate"
        assert set(entries[0]["tba_numbers"]) == {"TBA1", "TBA2"}

    def test_existing_stop_is_reused_not_duplicated(self, db):
        """delivery_stops is UNIQUE on (route_id, normalised_address) — one stop
        per building per route. Inserting blindly raises IntegrityError, which
        is how this guard was found."""
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        first = self._attach(db, r, tba="TBA1", addr="1 MAIN ST")
        db.commit()
        second = self._attach(db, r, tba="TBA2", addr="1 MAIN ST")
        db.commit()

        assert second.id == first.id, "should join the existing stop"
        assert set(second.tba_numbers) == {"TBA1", "TBA2"}
        assert second.packages_total == 2
        assert db.query(DeliveryStop).filter(
            DeliveryStop.route_id == r.id).count() == 1

    def test_constraint_exists_so_the_guard_is_required(self):
        """Pins WHY the reuse branch exists — if this constraint were dropped
        the guard would look like dead code."""
        names = {c.name for c in DeliveryStop.__table__.constraints if c.name}
        assert "uq_delivery_stops_route_address" in names

    def test_stop_is_flagged_unplanned(self, db):
        """is_unplanned keeps it out of Amazon reconciliation (ADR-197/246):
        the package was never manifested, so counting it in our_delivered would
        manufacture a discrepancy against ourselves."""
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        stop = self._attach(db, r)
        db.commit()
        assert stop.is_unplanned is True
        assert stop.status == "planned"

    def test_both_actors_are_recorded(self, db):
        """ADR-244: the executor owns the stop, the enterer is recorded."""
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        stop = self._attach(db, r)
        db.commit()
        assert stop.walker_name == "Executor"
        assert stop.recorded_by_name == "Recorder"
        assert stop.walker_id != stop.recorded_by

    def test_stop_sequence_continues_from_existing(self, db):
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        first = self._attach(db, r, tba="TBA1", addr="1 A ST")
        second = self._attach(db, r, tba="TBA2", addr="2 B ST")
        db.commit()
        assert second.stop_sequence == first.stop_sequence + 1

    def test_capacity_is_not_checked(self, db):
        """The package is already in the tote — its capacity was consumed at
        load. Rejecting it here would apply a planning rule to a fact on the
        ground (ADR-246)."""
        r = _route(db, date(2026, 8, 1), blocks=["BLK1"])
        r.package_count = 999
        r.capacity_limit = 10          # already far over
        db.commit()

        stop = self._attach(db, r)     # must not raise
        db.commit()
        assert stop is not None


class TestForeignRemoval:
    def test_creates_a_flagged_anchor_point_removal(self, db):
        """Reuses ADR-176 rather than inventing a mechanism: same row shape
        persist_zones writes for station finds, with pull_point marking that
        this one came from the field."""
        w = _walker(db, "Finder")
        rem = create_foreign_removal(
            db, company_id=COMPANY, tba="TBA_ALIEN",
            removal_date=date(2026, 8, 1),
            removed_by=w.id, removed_by_name=w.name,
        )
        db.commit()

        assert rem.reason == "out_of_zone"
        assert rem.pull_point == "anchor_point"
        assert rem.status == "flagged"
        assert rem.whole_tote is False
        assert rem.package_count == 1

    def test_custody_chain_starts_pending(self, db):
        """Dispatch approving the removal is not custody — the walker->driver->
        station legs transition this field."""
        w = _walker(db, "Finder")
        rem = create_foreign_removal(
            db, company_id=COMPANY, tba="TBA_ALIEN",
            removal_date=date(2026, 8, 1),
            removed_by=w.id, removed_by_name=w.name,
        )
        db.commit()
        assert rem.handoff_status == "pending"
        assert rem.handed_over_at is None
        assert rem.received_at is None

    def test_removal_is_company_scoped(self, db):
        w = _walker(db, "Finder")
        create_foreign_removal(db, company_id=COMPANY, tba="T1",
                               removal_date=date(2026, 8, 1),
                               removed_by=w.id, removed_by_name=w.name)
        db.commit()
        mine = db.query(PackageRemoval).filter(
            PackageRemoval.company_id == COMPANY).all()
        assert len(mine) == 1


class TestDuplicateGuard:
    """Never create a second delivery record for one TBA (ADR-246).

    Two records for one physical package corrupt both the walker's metrics and
    the Amazon reconciliation. The guard must also NAME the holder — a bare
    refusal sends the walker off to find out who has it, and two people holding
    the same TBA is itself a signal worth surfacing.
    """

    def test_unknown_tba_is_not_a_duplicate(self, db):
        _route(db, date(2026, 8, 2), blocks=["B1"])
        v = check_duplicate(db, COMPANY, "TBA999", date(2026, 8, 2))
        assert v.is_duplicate is False
        assert v.holder_name is None

    def test_tba_on_a_route_manifest_is_a_duplicate(self, db):
        w = _walker(db, name="M. Rivera")
        r = _route(db, date(2026, 8, 2), number=7, executor=w)
        r.tba_numbers = ["TBA447"]
        db.commit()

        v = check_duplicate(db, COMPANY, "TBA447", date(2026, 8, 2))
        assert v.is_duplicate is True
        assert v.basis == "route_manifest"
        assert v.holder_name == "M. Rivera"      # names them, does not just refuse
        assert v.route_number == 7

    def test_holder_is_reported_even_with_no_executor(self, db):
        """An unassigned route still blocks the duplicate; the name is simply
        unknown. Refusing to report the duplicate because nobody is on the
        route would let a second record through."""
        r = _route(db, date(2026, 8, 2), number=3)
        r.tba_numbers = ["TBA447"]
        db.commit()

        v = check_duplicate(db, COMPANY, "TBA447", date(2026, 8, 2))
        assert v.is_duplicate is True
        assert v.route_number == 3
        assert v.holder_name is None

    def test_match_is_case_insensitive_and_trimmed(self, db):
        r = _route(db, date(2026, 8, 2))
        r.tba_numbers = ["TBA447"]
        db.commit()
        assert check_duplicate(db, COMPANY, "  tba447 ", date(2026, 8, 2)).is_duplicate

    def test_empty_tba_is_not_a_duplicate(self, db):
        assert check_duplicate(db, COMPANY, "   ", date(2026, 8, 2)).is_duplicate is False

    # ── the two scoping properties ──────────────────────────────────────────

    def test_another_companys_package_is_not_a_duplicate(self, db):
        """Dimension 1. A cross-tenant match would leak that another company
        holds the TBA, and would block a legitimate delivery."""
        other = uuid.uuid4()
        r = _route(db, date(2026, 8, 2), company=other)
        r.tba_numbers = ["TBA447"]
        db.commit()

        assert check_duplicate(db, COMPANY, "TBA447", date(2026, 8, 2)).is_duplicate is False

    def test_same_tba_on_a_different_day_is_not_a_duplicate(self, db):
        """TBAs recur across days — Amazon reuses them, and a redelivery is a
        new package-day. An all-time check would refuse today's package because
        it was delivered a fortnight ago."""
        r = _route(db, date(2026, 7, 20))
        r.tba_numbers = ["TBA447"]
        db.commit()

        assert check_duplicate(db, COMPANY, "TBA447", date(2026, 8, 2)).is_duplicate is False
        assert check_duplicate(db, COMPANY, "TBA447", date(2026, 7, 20)).is_duplicate is True

    def test_a_delivered_stop_also_counts_as_a_duplicate(self, db):
        """The package may already be recorded as delivered rather than merely
        assigned. Adding it again would double-count it."""
        r = _route(db, date(2026, 8, 2), number=4)
        db.add(DeliveryStop(
            id=uuid.uuid4(), company_id=COMPANY, route_id=r.id,
            truck_assignment_id=r.truck_assignment_id,
            walker_id=uuid.uuid4(), walker_name="D. Chen",
            normalised_address="1 MAIN ST", block_key="B1",
            tba_numbers=["TBA447"], status="completed", stop_sequence=1,
        ))
        db.commit()

        v = check_duplicate(db, COMPANY, "TBA447", date(2026, 8, 2))
        assert v.is_duplicate is True
        assert v.basis == "delivery_stop"
        assert v.holder_name == "D. Chen"
        assert v.route_number == 4


class TestResolveAddress:
    """Deriving coords, canonical address and block key from label text (ADR-259).

    Clients only ever send what the OCR read off the label. Before this, lat/lng
    arrived null on every request, so `check_zone` answered `no_coords` every
    time and the whole ownership tree of ADR-246 never ran.

    The two derivations are deliberately independent: the block key is pure
    string work, so a GeoClient outage must still leave routes rankable.
    """

    @staticmethod
    def _geo(**kw):
        from app.tasks.enrich_manifest import GeoClientResult
        base = dict(
            normalised_address="505 WEST 37 STREET", lat=40.756679, lng=-73.998177,
            first_cross_street=None, second_cross_street=None, segment_id=None,
            from_lion_node_id=None, to_lion_node_id=None,
            x_low_address_end=None, y_low_address_end=None,
            x_high_address_end=None, y_high_address_end=None,
        )
        base.update(kw)
        return GeoClientResult(**base)

    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        """Fail loudly if a test forgets to stub GeoClient.

        A unit test that silently reaches the real API would pass locally, cost
        400ms, and break in CI where no key is set.
        """
        import app.tasks.enrich_manifest as em

        def _boom(*a, **kw):
            raise AssertionError("unstubbed GeoClient call")

        monkeypatch.setattr(em, "_geoclient_normalise", _boom)

    def _stub(self, monkeypatch, fn):
        import app.tasks.enrich_manifest as em
        monkeypatch.setattr(em, "_geoclient_normalise", fn)

    def test_block_key_is_derived_from_label_text(self, db, monkeypatch):
        """The bug in one line: nothing derived this, so the block-match tier
        could never fire."""
        self._stub(monkeypatch, lambda *a, **kw: None)
        r = resolve_address(db, COMPANY, "505 W 37TH ST APT 4007", "TBA1")
        assert r.block_key == "W_37_St_500"

    def test_geocode_supplies_coords_and_canonical_address(self, db, monkeypatch):
        self._stub(monkeypatch, lambda *a, **kw: self._geo())
        r = resolve_address(db, COMPANY, "505 W 37TH ST APT 4007", "TBA1")
        assert (r.lat, r.lng) == (40.756679, -73.998177)
        assert r.geocoded is True
        # GeoClient's canonical form is what Route.normalised_addresses holds,
        # so preferring it is what lets the exact-address tier match at all.
        assert r.normalised_address == "505 WEST 37 STREET"

    def test_block_key_survives_a_geocode_failure(self, db, monkeypatch):
        """The reason the two derivations are independent: an outage costs the
        ownership check, not the ability to rank routes."""
        self._stub(monkeypatch, lambda *a, **kw: None)
        r = resolve_address(db, COMPANY, "505 W 37TH ST APT 4007", "TBA1")
        assert r.geocoded is False
        assert r.lat is None
        assert r.block_key == "W_37_St_500"

    def test_a_geoclient_exception_never_propagates(self, db, monkeypatch):
        """Intake must reach dispatch even when geocoding is down — a network
        error here would otherwise 500 a walker mid-route."""
        def _raise(*a, **kw):
            raise RuntimeError("connection reset")
        self._stub(monkeypatch, _raise)

        r = resolve_address(db, COMPANY, "505 W 37TH ST APT 4007", "TBA1")
        assert r.geocoded is False
        assert r.block_key == "W_37_St_500"

    def test_caller_supplied_coords_are_not_overridden(self, db, monkeypatch):
        """Mobile may send a device fix, and a dispatcher may correct a bad
        parse. Neither should be silently replaced — and no call is made."""
        r = resolve_address(db, COMPANY, "505 W 37TH ST APT 4007", "TBA1",
                            lat=40.70, lng=-74.00)
        assert (r.lat, r.lng) == (40.70, -74.00)
        assert r.geocoded is True

    def test_caller_supplied_block_key_is_not_overridden(self, db, monkeypatch):
        self._stub(monkeypatch, lambda *a, **kw: None)
        r = resolve_address(db, COMPANY, "505 W 37TH ST APT 4007", "TBA1",
                            block_key="MANUAL_1")
        assert r.block_key == "MANUAL_1"

    def test_an_unparseable_address_yields_no_block_key(self, db, monkeypatch):
        """derive_block_key returns UnparseableAddress for OCR mush. That is a
        normal outcome carrying a reason, not a block key — and not a crash."""
        self._stub(monkeypatch, lambda *a, **kw: None)
        r = resolve_address(db, COMPANY, "no house number here", "TBA1")
        assert r.block_key is None
        assert r.geocoded is False

    def test_no_address_at_all_is_handled(self, db):
        """A radio report may carry only a TBA. No address means nothing to
        derive and nothing to call — the autouse guard proves no call is made."""
        r = resolve_address(db, COMPANY, None, "TBA1")
        assert r.block_key is None
        assert r.geocoded is False

    def test_a_geocode_without_coords_is_not_treated_as_located(self, db, monkeypatch):
        """GeoClient answers 200 with the street matched but the house number
        out of range: a normalised name and NO coords. That is not a location,
        and treating it as one would put the package in the wrong zone."""
        self._stub(monkeypatch, lambda *a, **kw: self._geo(lat=None, lng=None))
        r = resolve_address(db, COMPANY, "99999 W 37TH ST", "TBA1")
        assert r.geocoded is False
        assert r.lat is None

    def test_borough_comes_from_company_config(self, db, monkeypatch):
        """An operator outside Manhattan sets it on CompanyConfig; the default
        is only a default. Passing the wrong borough silently geocodes to the
        wrong city block."""
        from app.models.company import CompanyConfig
        db.add(CompanyConfig(id=uuid.uuid4(), company_id=COMPANY,
                             geoclient_borough="brooklyn"))
        db.commit()

        seen = {}

        def _capture(addr, borough="manhattan"):
            seen["borough"] = borough
            return None

        self._stub(monkeypatch, _capture)
        resolve_address(db, COMPANY, "100 MAIN ST", "TBA1")
        assert seen["borough"] == "brooklyn"

    def test_borough_defaults_to_manhattan(self, db, monkeypatch):
        seen = {}

        def _capture(addr, borough="manhattan"):
            seen["borough"] = borough
            return None

        self._stub(monkeypatch, _capture)
        resolve_address(db, COMPANY, "100 MAIN ST", "TBA1")
        assert seen["borough"] == "manhattan"

    def test_another_companys_config_does_not_apply(self, db, monkeypatch):
        """Dimension 1: the borough lookup is company-scoped like every other
        read. Without the filter, one tenant's borough would geocode another's
        packages."""
        from app.models.company import CompanyConfig
        db.add(CompanyConfig(id=uuid.uuid4(), company_id=OTHER,
                             geoclient_borough="queens"))
        db.commit()

        seen = {}

        def _capture(addr, borough="manhattan"):
            seen["borough"] = borough
            return None

        self._stub(monkeypatch, _capture)
        resolve_address(db, COMPANY, "100 MAIN ST", "TBA1")
        assert seen["borough"] == "manhattan"
