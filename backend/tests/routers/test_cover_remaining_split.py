"""ADR-229 — cover remaining stops: emergency route split.

A walker stalls mid-route and the undelivered stops have to reach someone else.
The failure this guards against is not an error — it is a stop that lands on
BOTH routes or NEITHER, which surfaces days later as a package nobody
delivered and nobody was assigned.

walker_routes.py is proprietary; CI copies it in from AsheFlow-private before
pytest, so there is deliberately NO skip guard.
"""
import inspect

from app.main import app
from app.models.walker_route import Route
from app.routers import walker_routes as wr


def _code_only(obj) -> str:
    """Source with comments and docstring stripped.

    Well-documented code names the thing it avoids; a bare absence assertion
    would read the explanation as the offence.
    """
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


class TestRouteExists:
    def test_endpoint_registered(self):
        assert "/api/v1/walker-routes/routes/{route_id}/cover-remaining" in app.openapi()["paths"]

    def test_mobile_no_longer_calls_a_missing_route(self):
        """RouteSortScreen has called this since July with nothing on the other
        end — a captain tapping "Cover" in a real emergency got a generic
        error. It should now be off the known-unbuilt list."""
        from pathlib import Path

        # Import the set itself rather than slicing source. My first version
        # cut at the first "}" — which landed inside the path string
        # "/routes/{}/cover-remaining" — so the assertion passed while the entry
        # was still there.
        from tests.routers.test_ui_api_paths_exist import _KNOWN_UNBUILT

        assert not any("cover-remaining" in p for p in _KNOWN_UNBUILT), (
            "the endpoint exists now — remove it from _KNOWN_UNBUILT"
        )


class TestGates:
    def test_only_route_leads_may_split(self):
        src = _code_only(wr.cover_remaining)
        assert "_allow_route_lead" in src

    def test_caller_must_crew_the_truck(self):
        """A route lead on another truck must not reshuffle this one."""
        src = _code_only(wr.cover_remaining)
        assert "_assert_truck_scope(caller, route.truck_assignment_id, db)" in src

    def test_only_an_in_progress_route_can_be_covered(self):
        """`assigned` has reassign; `completed` has nothing to move."""
        src = _code_only(wr.cover_remaining)
        assert 'route.status != "in_progress"' in src
        assert "HTTP_409_CONFLICT" in src

    def test_it_requires_a_real_distress_signal(self):
        """THE gate (ADR-229). Without it a captain could silently peel work off
        any active route; with it the structural move follows a help request."""
        src = _code_only(wr.cover_remaining)
        assert "route.help_requested_at is None" in src

    def test_request_help_stamps_the_signal(self):
        """The gate is only meaningful if something sets it. The column shipped
        months ago and nothing wrote it — the endpoint would have 409'd for
        every caller, forever."""
        src = _code_only(wr.request_help)
        assert "route.help_requested_at = datetime.now(timezone.utc)" in src

    def test_empty_remaining_is_refused(self):
        src = _code_only(wr.cover_remaining)
        assert "if not remaining:" in src


class TestPartitionIsExhaustive:
    def test_every_stop_lands_on_exactly_one_side(self):
        """ADR-115 dim 5. The partition is a single predicate over one list, so
        a stop cannot be duplicated or dropped — that is the property, not the
        test's cleverness."""
        src = _code_only(wr.cover_remaining)
        assert 'delivered = [s for s in stops if s.status == "completed"]' in src
        assert 'remaining = [s for s in stops if s.status != "completed"]' in src

    def test_stops_are_repointed_not_recreated(self):
        """Re-creating DeliveryStop rows would lose started_at and any partial
        progress; the new executor must pick up mid-stop where the stalled one
        left off."""
        src = _code_only(wr.cover_remaining)
        assert "s.route_id = covering.id" in src
        assert "DeliveryStop(" not in src, "stops must MOVE, not be recreated"

    def test_the_split_is_driven_by_lifecycle_rows_not_the_json_blob(self):
        """Route.stops is ADR-194 presentation data. DeliveryStop is the
        lifecycle truth — deriving the split from the blob would mis-split any
        route where the two drifted."""
        src = _code_only(wr.cover_remaining)
        i_query = src.index("db.query(DeliveryStop)")
        i_blob = src.index("_split_stops(route.stops)")
        assert i_query < i_blob


class TestOriginalIsClosedAtDelivered:
    def test_it_completes_with_a_reason(self):
        src = _code_only(wr.cover_remaining)
        assert 'route.status               = "completed"' in src
        assert 'route.closed_reason        = "covered"' in src

    def test_counts_are_recomputed_from_the_kept_set(self):
        """Leaving package_count at its pre-split value would credit the walker
        with work that moved away."""
        src = _code_only(wr.cover_remaining)
        # Derived from the KEPT stop payload, not by subtracting from the old
        # array — the ADR-194 stops are the package-identity source, and the
        # pre-existing integration test pins that contract.
        assert "route.tba_numbers          = sorted(kept_tba_set)" in src
        assert "route.package_count        = len(kept_tba_set)" in src
        assert "route.slot_cost            = len(delivered)" in src

    def test_returned_at_is_not_overwritten(self):
        """A walker who already tapped back-at-truck has a real timestamp;
        covering their route must not move it."""
        src = _code_only(wr.cover_remaining)
        assert "route.returned_at          = route.returned_at or" in src


class TestCoveringRoute:
    def test_it_lands_unassigned(self):
        """ADR-226/213: the captain assigns from the existing wave UI. No forced
        immediate pick, and no live-rebuilt seed."""
        src = _code_only(wr.cover_remaining)
        assert 'status                = "unassigned"' in src

    def test_it_carries_only_what_moved(self):
        """A covering route claiming the original's full block list would
        mis-rank every proximity decision downstream."""
        src = _code_only(wr.cover_remaining)
        assert "block_keys            = sorted(remaining_blocks)" in src
        assert "tba_numbers           = sorted(remaining_tba_set)" in src

    def test_it_is_the_next_wave(self):
        src = _code_only(wr.cover_remaining)
        assert "wave_number           = (route.wave_number or 1) + 1" in src

    def test_route_number_is_scoped_to_the_truck_and_date(self):
        """max()+1 across the whole company would collide with another truck's
        numbering."""
        src = _code_only(wr.cover_remaining)
        i = src.index("func.max(Route.route_number)")
        window = src[i : i + 400]
        assert "Route.truck_assignment_id == route.truck_assignment_id" in window
        assert "Route.route_date == route.route_date" in window


class TestTenancyAndAudit:
    def test_every_query_is_company_scoped(self):
        """ADR-115 dim 1. Four queries here: route, stops, max route_number,
        plus the truck scope check inside the helper."""
        src = _code_only(wr.cover_remaining)
        assert src.count("db.query(") == 3
        assert src.count("company_id == caller.company_id") == 3

    def test_flush_audit_commit_in_order(self):
        src = _code_only(wr.cover_remaining)
        assert src.index("db.flush()") < src.index("write_audit(") < src.index("db.commit()")

    def test_the_split_is_audited_with_both_route_numbers(self):
        """A stop that later looks misplaced has to be traceable to the split
        that moved it."""
        src = _code_only(wr.cover_remaining)
        assert "route.cover_remaining" in src
        assert "covering_route_number" in src
        assert "stops_moved" in src

    def test_no_address_is_logged(self):
        src = _code_only(wr.cover_remaining)
        assert "logger" not in src


class TestSchema:
    def test_route_carries_the_help_signal(self):
        col = Route.__table__.columns.get("help_requested_at")
        assert col is not None
        assert col.nullable is True


class TestClosedReasonStaysOutOfSortTelemetry:
    """ADR-115 dimension 8. `closed_reason` is ADR-272's sort diagnosis, and
    ADR-229 added an eighth value to a column that documented seven.

    "covered" is safe today only because telemetry is computed at SORT time,
    over routes the sort just produced — a route cannot be covered until it is
    in_progress with a help request. That is a timing property, not a
    structural one, so it is worth pinning."""

    def test_covered_is_only_reachable_after_the_sort(self):
        src = _code_only(wr.cover_remaining)
        assert 'route.status != "in_progress"' in src
        assert "route.help_requested_at is None" in src

    def test_the_column_documents_the_value(self):
        """The model listed seven values; a reader diagnosing an unexpected
        histogram bucket would have found no explanation for the eighth."""
        import inspect

        from app.models import walker_route

        src = inspect.getsource(walker_route)
        i = src.index("closed_reason         = Column")
        assert "covered" in src[max(0, i - 700):i]

    def test_sort_telemetry_is_computed_at_sort_time(self):
        """If this ever runs over persisted historical routes instead, a
        "covered" bucket enters ADR-272's diagnosis and the finding is real."""
        import inspect

        from app.services import sort_telemetry

        src = inspect.getsource(sort_telemetry.compute_sort_metrics)
        assert "closed_reason" in src
        assert "db.query(Route)" not in src, (
            "telemetry now reads routes itself — re-check whether a covered "
            "route can reach closed_reason_hist (ADR-229 / ADR-272)"
        )
