"""
Tests for the _persist_routes helper in walker_routes.py.

These tests cover the three bugs found in the 2026-06-03 audit:
  1. package_count must be set on every Route row (was missing — nullable=False violation)
  2. Unassigned misroutes must be anchored to the route whose block_keys contains the
     destination, not always to created[0]
  3. Fallback to created[0] when no route matches the destination block key

We use MagicMock for the DB session to avoid the PostgreSQL ARRAY/UUID column
types that SQLite cannot compile. The helper under test is pure logic — it builds
ORM objects from a SortResult, calls db.add/flush/commit/refresh. We intercept
those calls and inspect what was constructed.
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from app.routers.walker_routes import _persist_routes
from app.schemas.walker_routes import (
    MisroutedPackageOut,
    RouteOut,
    SortResult,
    EFFORT_CAPACITY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMPANY_ID   = uuid.uuid4()
_TA_ID        = uuid.uuid4()
_ROUTE_DATE   = date.today()


def _make_caller():
    caller = MagicMock()
    caller.company_id = _COMPANY_ID
    return caller


def _make_route_out(
    route_number: int,
    block_keys: list[str],
    package_count: int = 3,
    misrouted: list[MisroutedPackageOut] | None = None,
) -> RouteOut:
    return RouteOut(
        route_number       = route_number,
        block_keys         = block_keys,
        tote_ids           = [f"Bag{route_number}"],
        tba_numbers        = [f"TBA{route_number:03}{i}" for i in range(package_count)],

        slot_cost          = 4,
        capacity_limit     = EFFORT_CAPACITY["standard"],
        effort_class       = "standard",
        workload_source    = "default",
        package_count      = package_count,
        misrouted_packages = misrouted or [],
    )


def _make_sort_result(
    routes: list[RouteOut],
    unassigned_misroutes: list[MisroutedPackageOut] | None = None,
) -> SortResult:
    return SortResult(
        truck_assignment_id  = _TA_ID,
        route_date           = _ROUTE_DATE,
        routes               = routes,
        unassigned_misroutes = unassigned_misroutes or [],
    )


def _make_mock_db():
    """Return a mock Session that captures add() calls and gives routes a UUID on flush()."""
    db = MagicMock()
    added_objects: list = []

    def _add(obj):
        added_objects.append(obj)
        # Give Route objects a UUID id so flush() doesn't leave it None
        if hasattr(obj, "route_number"):
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()

    db.add.side_effect = _add
    db._added = added_objects
    return db


# ---------------------------------------------------------------------------
# Tests: package_count written to every Route row
# ---------------------------------------------------------------------------

class TestPersistRoutesPackageCount:
    def test_package_count_set_on_single_route(self):
        route_out = _make_route_out(1, ["W_36_St_300"], package_count=5)
        result = _make_sort_result([route_out])
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert len(created) == 1
        assert created[0].package_count == 5

    def test_package_count_set_on_each_route_independently(self):
        routes = [
            _make_route_out(1, ["W_36_St_300"], package_count=3),
            _make_route_out(2, ["W_57_St_400"],  package_count=7),
        ]
        result = _make_sort_result(routes)
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert created[0].package_count == 3
        assert created[1].package_count == 7

    def test_package_count_zero_is_allowed(self):
        # A route with no packages (e.g. OV-only) must still set the field
        route_out = _make_route_out(1, ["W_36_St_300"], package_count=0)
        result = _make_sort_result([route_out])
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert created[0].package_count == 0

    def test_company_id_set_on_route(self):
        route_out = _make_route_out(1, ["W_36_St_300"])
        result = _make_sort_result([route_out])
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert created[0].company_id == _COMPANY_ID

    def test_status_is_unassigned(self):
        route_out = _make_route_out(1, ["W_36_St_300"])
        result = _make_sort_result([route_out])
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert created[0].status == "unassigned"


# ---------------------------------------------------------------------------
# Tests: unassigned misroute anchoring
# ---------------------------------------------------------------------------

class TestPersistRoutesUnassignedMisrouteAnchor:
    def _run(self, routes: list[RouteOut], unassigned: list[MisroutedPackageOut]):
        result = _make_sort_result(routes, unassigned_misroutes=unassigned)
        db = _make_mock_db()
        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        # Collect all MisroutedPackageFlag objects added to the session
        flags = [obj for obj in db._added if hasattr(obj, "tba_number")]
        return created, flags

    def test_misroute_anchored_to_matching_destination_route(self):
        # Route 1 owns W_36_St_300; Route 2 owns W_57_St_400.
        # A misroute destined for W_57_St_400 must anchor to Route 2.
        r1 = _make_route_out(1, ["W_36_St_300"])
        r2 = _make_route_out(2, ["W_57_St_400"])
        misroute = MisroutedPackageOut(
            tba_number             = "TBA999",
            current_bag_id         = "BagX",
            destination_block_key  = "W_57_St_400",
            suggested_route_number = None,
        )

        created, flags = self._run([r1, r2], [misroute])

        unassigned_flags = [f for f in flags if f.tba_number == "TBA999"]
        assert len(unassigned_flags) == 1
        assert unassigned_flags[0].route_id == created[1].id  # Route 2, not Route 1

    def test_misroute_falls_back_to_first_route_when_no_match(self):
        # Destination block key not present in any route — fall back to created[0].
        r1 = _make_route_out(1, ["W_36_St_300"])
        r2 = _make_route_out(2, ["W_57_St_400"])
        misroute = MisroutedPackageOut(
            tba_number             = "TBA888",
            current_bag_id         = "BagY",
            destination_block_key  = "W_99_St_100",   # no route owns this
            suggested_route_number = None,
        )

        created, flags = self._run([r1, r2], [misroute])

        unassigned_flags = [f for f in flags if f.tba_number == "TBA888"]
        assert unassigned_flags[0].route_id == created[0].id  # falls back to Route 1

    def test_misroute_with_none_destination_falls_back_to_first_route(self):
        r1 = _make_route_out(1, ["W_36_St_300"])
        misroute = MisroutedPackageOut(
            tba_number             = "TBA777",
            current_bag_id         = "BagZ",
            destination_block_key  = None,
            suggested_route_number = None,
        )

        created, flags = self._run([r1], [misroute])

        unassigned_flags = [f for f in flags if f.tba_number == "TBA777"]
        assert unassigned_flags[0].route_id == created[0].id

    def test_multiple_misroutes_each_anchored_independently(self):
        # Three routes; three unassigned misroutes each destined for a different route.
        r1 = _make_route_out(1, ["W_36_St_300"])
        r2 = _make_route_out(2, ["W_57_St_400"])
        r3 = _make_route_out(3, ["5_Ave_200"])
        misroutes = [
            MisroutedPackageOut(
                destination_block_key="W_57_St_400", suggested_route_number=None,
            ),
            MisroutedPackageOut(
                destination_block_key="5_Ave_200", suggested_route_number=None,
            ),
            MisroutedPackageOut(
                destination_block_key="W_36_St_300", suggested_route_number=None,
            ),
        ]

        created, flags = self._run([r1, r2, r3], misroutes)

        flag_map = {f.tba_number: f.route_id for f in flags if f.tba_number.startswith("M")}
        assert flag_map["M1"] == created[1].id   # W_57_St → Route 2
        assert flag_map["M2"] == created[2].id   # 5_Ave   → Route 3
        assert flag_map["M3"] == created[0].id   # W_36_St → Route 1

    def test_no_misroutes_means_no_flag_rows_added_for_unassigned(self):
        r1 = _make_route_out(1, ["W_36_St_300"])
        result = _make_sort_result([r1], unassigned_misroutes=[])
        db = _make_mock_db()

        _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        flags = [obj for obj in db._added if hasattr(obj, "tba_number")]
        assert flags == []

    def test_destination_block_key_preserved_on_flag(self):
        r1 = _make_route_out(1, ["W_36_St_300"])
        misroute = MisroutedPackageOut(
            tba_number="TBA123", current_bag_id="BagA",
            destination_block_key="W_36_St_300", suggested_route_number=None,
        )
        _, flags = self._run([r1], [misroute])

        flag = next(f for f in flags if f.tba_number == "TBA123")
        assert flag.destination_block_key == "W_36_St_300"
        assert flag.current_bag_id == "BagA"
        assert flag.resolved is False


# ---------------------------------------------------------------------------
# ADR-194 — stops persistence + misroute geography move
# ---------------------------------------------------------------------------

from types import SimpleNamespace

from app.routers.walker_routes import (
    _merge_stops,
    _split_stops_by_tbas,
    _move_flag_geography,
)
from app.schemas.walker_routes import StopOut


def _stop(bk: str, addr: str, tbas: list[str], segment_id: str | None = None) -> dict:
    # ADR-230: StopOut now carries a bag-grouped view; default [] when built
    # without bags (these fixtures pass only tba_numbers).
    # ADR-279: ...and a per-stop segment_id, None when the fixture's packages
    # carried no LION topology (which is every fixture here — they pass
    # addresses, not enriched packages).
    return {
        "block_key": bk,
        "address": addr,
        "segment_id": segment_id,
        "tba_numbers": tbas,
        "bags": [],
    }


class TestPersistRoutesStops:
    def test_stops_persisted_as_plain_dicts(self):
        route_out = _make_route_out(1, ["W_36_St_300"])
        route_out.stops = [
            StopOut(block_key="W_36_St_300", address="302 WEST 36 STREET", tba_numbers=["T1"]),
            StopOut(block_key="W_36_St_300", address="310 WEST 36 STREET", tba_numbers=["T2", "T3"]),
        ]
        db = _make_mock_db()
        created = _persist_routes(_make_sort_result([route_out]), _make_caller(), _TA_ID, _ROUTE_DATE, db)
        assert created[0].stops == [
            _stop("W_36_St_300", "302 WEST 36 STREET", ["T1"]),
            _stop("W_36_St_300", "310 WEST 36 STREET", ["T2", "T3"]),
        ]

    def test_flag_normalised_address_persisted(self):
        m = MisroutedPackageOut(
            tba_number="FAR", current_bag_id="BagY",
            destination_block_key="W_57_St_300",
            normalised_address="350 WEST 57 STREET",
            suggested_route_number=None,
        )
        route_out = _make_route_out(1, ["W_57_St_300"])
        db = _make_mock_db()
        _persist_routes(_make_sort_result([route_out], unassigned_misroutes=[m]),
                        _make_caller(), _TA_ID, _ROUTE_DATE, db)
        flags = [a.args[0] for a in db.add.call_args_list
                 if type(a.args[0]).__name__ == "MisroutedPackageFlag"]
        assert len(flags) == 1
        assert flags[0].normalised_address == "350 WEST 57 STREET"


class TestMergeAndSplitStops:
    def test_merge_combines_same_address(self):
        merged = _merge_stops(
            [_stop("W_36_St_300", "310 WEST 36 STREET", ["T1"])],
            [_stop("W_36_St_300", "310 WEST 36 STREET", ["T2"]),
             _stop("W_36_St_400", "410 WEST 36 STREET", ["T3"])],
        )
        assert merged == [
            _stop("W_36_St_300", "310 WEST 36 STREET", ["T1", "T2"]),
            _stop("W_36_St_400", "410 WEST 36 STREET", ["T3"]),
        ]

    def test_merge_does_not_mutate_inputs(self):
        base = [_stop("W_36_St_300", "310 WEST 36 STREET", ["T1"])]
        _merge_stops(base, [_stop("W_36_St_300", "310 WEST 36 STREET", ["T2"])])
        assert base == [_stop("W_36_St_300", "310 WEST 36 STREET", ["T1"])]

    def test_merge_deduplicates_tbas(self):
        merged = _merge_stops(
            [_stop("W_36_St_300", "310 WEST 36 STREET", ["T1"])],
            [_stop("W_36_St_300", "310 WEST 36 STREET", ["T1"])],
        )
        assert merged[0]["tba_numbers"] == ["T1"]

    def test_split_by_tbas_both_sides(self):
        taken, remaining = _split_stops_by_tbas(
            [_stop("W_36_St_300", "310 WEST 36 STREET", ["T1", "T2"]),
             _stop("W_36_St_400", "410 WEST 36 STREET", ["T3"])],
            {"T1", "T3"},
        )
        assert taken == [
            _stop("W_36_St_300", "310 WEST 36 STREET", ["T1"]),
            _stop("W_36_St_400", "410 WEST 36 STREET", ["T3"]),
        ]
        assert remaining == [_stop("W_36_St_300", "310 WEST 36 STREET", ["T2"])]

    def test_split_none_is_empty(self):
        assert _split_stops_by_tbas(None, {"T1"}) == ([], [])


class TestMoveFlagGeography:
    def _routes(self):
        src = SimpleNamespace(
            id=uuid.uuid4(),
            block_keys=["W_44_St_300", "W_57_St_400"],
            normalised_addresses=["300 WEST 44 STREET", "446 WEST 57 STREET"],
            stops=[_stop("W_44_St_300", "300 WEST 44 STREET", ["D1"])],
            tba_numbers=["D1", "FAR"],
        )
        dest = SimpleNamespace(
            id=uuid.uuid4(),
            block_keys=["W_57_St_300"],
            normalised_addresses=["350 WEST 57 STREET"],
            stops=[_stop("W_57_St_300", "350 WEST 57 STREET", ["X1"])],
            tba_numbers=["X1"],
        )
        flag = SimpleNamespace(
            tba_number="FAR",
            destination_block_key="W_57_St_400",
            normalised_address="446 WEST 57 STREET",
        )
        return src, dest, flag

    def test_dest_gains_stop_block_and_address(self):
        src, dest, flag = self._routes()
        _move_flag_geography(flag, src, dest, other_flags=[])
        # ADR-230: the moved package rides in a bag group (color unknown here).
        moved = {"block_key": "W_57_St_400", "address": "446 WEST 57 STREET",
                 "tba_numbers": ["FAR"],
                 "bags": [{"bag_id": "(loose)", "bag_color": None, "tba_numbers": ["FAR"]}]}
        assert moved in dest.stops
        assert "W_57_St_400" in dest.block_keys
        assert "446 WEST 57 STREET" in dest.normalised_addresses

    def test_src_drops_outlier_block_and_address(self):
        src, dest, flag = self._routes()
        _move_flag_geography(flag, src, dest, other_flags=[])
        assert "W_57_St_400" not in src.block_keys
        assert "446 WEST 57 STREET" not in src.normalised_addresses
        # the delivered stop is untouched
        assert src.block_keys == ["W_44_St_300"]
        assert src.stops == [_stop("W_44_St_300", "300 WEST 44 STREET", ["D1"])]

    def test_src_keeps_block_referenced_by_another_unresolved_flag(self):
        src, dest, flag = self._routes()
        other = SimpleNamespace(
            tba_number="FAR2",
            destination_block_key="W_57_St_400",
            normalised_address="450 WEST 57 STREET",
        )
        _move_flag_geography(flag, src, dest, other_flags=[other])
        assert "W_57_St_400" in src.block_keys           # still referenced
        assert "446 WEST 57 STREET" not in src.normalised_addresses  # address is not

    def test_src_keeps_block_when_a_delivered_stop_shares_it(self):
        src, dest, flag = self._routes()
        src.stops = src.stops + [_stop("W_57_St_400", "440 WEST 57 STREET", ["D2"])]
        _move_flag_geography(flag, src, dest, other_flags=[])
        assert "W_57_St_400" in src.block_keys


# ---------------------------------------------------------------------------
# ADR-195 F4 — _get_block_time_urgency helper (BuildingProfile hours → 0-1)
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta

from app.routers.walker_routes import _get_block_time_urgency


def _mock_db_with_profiles(rows):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = rows
    return db


class TestBlockTimeUrgency:
    """Clock is pinned to a fixed local noon so relative offsets can't wrap past
    midnight (which would turn a 'far future' close into an already-passed one)."""

    _REF = datetime(2026, 7, 11, 12, 0, 0)   # noon, deterministic

    def _urgency(self, rows):
        # patch datetime.now in the helper's module so 'now' is _REF
        import app.routers.walker_routes as wr

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 11, 12, 0, 0, tzinfo=tz)

        with patch.object(wr, "datetime", _FrozenDatetime):
            return _get_block_time_urgency(_mock_db_with_profiles(rows), uuid.uuid4(),
                                           date(2026, 7, 11), "America/New_York")

    def test_imminent_close_is_max_urgency(self):
        rows = [SimpleNamespace(block_key="W_23_St_100", closes_at=self._REF.time(), break_start=None)]
        assert self._urgency(rows).get("W_23_St_100", 0) >= 0.9

    def test_far_close_is_low_urgency(self):
        late = (self._REF + timedelta(hours=7)).time()   # 19:00 — same day, no wrap
        rows = [SimpleNamespace(block_key="W_50_St_300", closes_at=late, break_start=None)]
        u = self._urgency(rows)
        assert 0.0 < u.get("W_50_St_300", 0) < 0.3

    def test_no_hours_block_absent(self):
        rows = [SimpleNamespace(block_key="W_40_St_200", closes_at=None, break_start=None)]
        assert "W_40_St_200" not in self._urgency(rows)   # absent → preserves cold-start

    def test_earliest_cutoff_across_buildings_wins(self):
        soon = self._REF.time()
        late = (self._REF + timedelta(hours=7)).time()
        rows = [
            SimpleNamespace(block_key="W_30_St_100", closes_at=late, break_start=None),
            SimpleNamespace(block_key="W_30_St_100", closes_at=soon, break_start=None),
        ]
        assert self._urgency(rows).get("W_30_St_100", 0) >= 0.9   # earliest (soon) drives it


# ---------------------------------------------------------------------------
# ADR-197 Phase 0a — planned delivery-stop pre-seeding
# ---------------------------------------------------------------------------

class TestPlannedStopPreseed:
    def test_persist_routes_preseeds_planned_stops(self):
        route_out = _make_route_out(1, ["W_36_St_300"])
        route_out.stops = [
            StopOut(block_key="W_36_St_300", address="302 WEST 36 STREET", tba_numbers=["T1"]),
            StopOut(block_key="W_36_St_300", address="310 WEST 36 STREET", tba_numbers=["T2", "T3"]),
        ]
        db = _make_mock_db()
        _persist_routes(_make_sort_result([route_out]), _make_caller(), _TA_ID, _ROUTE_DATE, db)
        stops = [o for o in db._added if type(o).__name__ == "DeliveryStop"]
        assert len(stops) == 2
        assert all(s.status == "planned" for s in stops)
        assert all(s.is_unplanned is False for s in stops)
        assert all(s.completed_at is None and s.walker_id is None for s in stops)
        # stop_sequence follows the ADR-194 sort order
        assert [s.stop_sequence for s in stops] == [1, 2]
        assert {s.normalised_address for s in stops} == {"302 WEST 36 STREET", "310 WEST 36 STREET"}

    def test_no_stops_preseeds_nothing(self):
        route_out = _make_route_out(1, ["W_36_St_300"])
        route_out.stops = []
        db = _make_mock_db()
        _persist_routes(_make_sort_result([route_out]), _make_caller(), _TA_ID, _ROUTE_DATE, db)
        stops = [o for o in db._added if type(o).__name__ == "DeliveryStop"]
        assert stops == []
