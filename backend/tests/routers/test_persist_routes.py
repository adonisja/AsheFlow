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
        tag_numbers        = [],
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
        route_out = _make_route_out(1, ["W_36_St_350s_even"], package_count=5)
        result = _make_sort_result([route_out])
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert len(created) == 1
        assert created[0].package_count == 5

    def test_package_count_set_on_each_route_independently(self):
        routes = [
            _make_route_out(1, ["W_36_St_350s_even"], package_count=3),
            _make_route_out(2, ["W_57_St_400s_odd"],  package_count=7),
        ]
        result = _make_sort_result(routes)
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert created[0].package_count == 3
        assert created[1].package_count == 7

    def test_package_count_zero_is_allowed(self):
        # A route with no packages (e.g. OV-only) must still set the field
        route_out = _make_route_out(1, ["W_36_St_350s_even"], package_count=0)
        result = _make_sort_result([route_out])
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert created[0].package_count == 0

    def test_company_id_set_on_route(self):
        route_out = _make_route_out(1, ["W_36_St_350s_even"])
        result = _make_sort_result([route_out])
        db = _make_mock_db()

        created = _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        assert created[0].company_id == _COMPANY_ID

    def test_status_is_unassigned(self):
        route_out = _make_route_out(1, ["W_36_St_350s_even"])
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
        # Route 1 owns W_36_St_350s_even; Route 2 owns W_57_St_400s_odd.
        # A misroute destined for W_57_St_400s_odd must anchor to Route 2.
        r1 = _make_route_out(1, ["W_36_St_350s_even"])
        r2 = _make_route_out(2, ["W_57_St_400s_odd"])
        misroute = MisroutedPackageOut(
            tba_number             = "TBA999",
            tag_number             = None,
            current_bag_id         = "BagX",
            destination_block_key  = "W_57_St_400s_odd",
            suggested_route_number = None,
        )

        created, flags = self._run([r1, r2], [misroute])

        unassigned_flags = [f for f in flags if f.tba_number == "TBA999"]
        assert len(unassigned_flags) == 1
        assert unassigned_flags[0].route_id == created[1].id  # Route 2, not Route 1

    def test_misroute_falls_back_to_first_route_when_no_match(self):
        # Destination block key not present in any route — fall back to created[0].
        r1 = _make_route_out(1, ["W_36_St_350s_even"])
        r2 = _make_route_out(2, ["W_57_St_400s_odd"])
        misroute = MisroutedPackageOut(
            tba_number             = "TBA888",
            tag_number             = None,
            current_bag_id         = "BagY",
            destination_block_key  = "W_99_St_100s_even",   # no route owns this
            suggested_route_number = None,
        )

        created, flags = self._run([r1, r2], [misroute])

        unassigned_flags = [f for f in flags if f.tba_number == "TBA888"]
        assert unassigned_flags[0].route_id == created[0].id  # falls back to Route 1

    def test_misroute_with_none_destination_falls_back_to_first_route(self):
        r1 = _make_route_out(1, ["W_36_St_350s_even"])
        misroute = MisroutedPackageOut(
            tba_number             = "TBA777",
            tag_number             = None,
            current_bag_id         = "BagZ",
            destination_block_key  = None,
            suggested_route_number = None,
        )

        created, flags = self._run([r1], [misroute])

        unassigned_flags = [f for f in flags if f.tba_number == "TBA777"]
        assert unassigned_flags[0].route_id == created[0].id

    def test_multiple_misroutes_each_anchored_independently(self):
        # Three routes; three unassigned misroutes each destined for a different route.
        r1 = _make_route_out(1, ["W_36_St_350s_even"])
        r2 = _make_route_out(2, ["W_57_St_400s_odd"])
        r3 = _make_route_out(3, ["5_Ave_200s_even"])
        misroutes = [
            MisroutedPackageOut(
                tba_number="M1", tag_number=None, current_bag_id="B1",
                destination_block_key="W_57_St_400s_odd", suggested_route_number=None,
            ),
            MisroutedPackageOut(
                tba_number="M2", tag_number=None, current_bag_id="B2",
                destination_block_key="5_Ave_200s_even", suggested_route_number=None,
            ),
            MisroutedPackageOut(
                tba_number="M3", tag_number=None, current_bag_id="B3",
                destination_block_key="W_36_St_350s_even", suggested_route_number=None,
            ),
        ]

        created, flags = self._run([r1, r2, r3], misroutes)

        flag_map = {f.tba_number: f.route_id for f in flags if f.tba_number.startswith("M")}
        assert flag_map["M1"] == created[1].id   # W_57_St → Route 2
        assert flag_map["M2"] == created[2].id   # 5_Ave   → Route 3
        assert flag_map["M3"] == created[0].id   # W_36_St → Route 1

    def test_no_misroutes_means_no_flag_rows_added_for_unassigned(self):
        r1 = _make_route_out(1, ["W_36_St_350s_even"])
        result = _make_sort_result([r1], unassigned_misroutes=[])
        db = _make_mock_db()

        _persist_routes(result, _make_caller(), _TA_ID, _ROUTE_DATE, db)

        flags = [obj for obj in db._added if hasattr(obj, "tba_number")]
        assert flags == []

    def test_destination_block_key_preserved_on_flag(self):
        r1 = _make_route_out(1, ["W_36_St_350s_even"])
        misroute = MisroutedPackageOut(
            tba_number="TBA123", tag_number="T1", current_bag_id="BagA",
            destination_block_key="W_36_St_350s_even", suggested_route_number=None,
        )
        _, flags = self._run([r1], [misroute])

        flag = next(f for f in flags if f.tba_number == "TBA123")
        assert flag.destination_block_key == "W_36_St_350s_even"
        assert flag.current_bag_id == "BagA"
        assert flag.resolved is False
