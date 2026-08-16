"""ADR-274 — a hub is a kind of truck, and is never auto-assigned.

The rule is one filter term in four places, which is exactly the shape that rots:
someone adds a truck query and forgets the hub clause, and the failure is silent
— a hub quietly collects crew it was never supposed to have.

These read the SOURCE rather than running dispatch, for the same reason
`test_role_authority_sets.py` does: the thing being guarded is a literal in a
query, and a behavioural test would need a full dispatch fixture to exercise
what a two-line assertion pins exactly.
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]


def _src(relpath: str) -> str:
    return (BACKEND / relpath).read_text(encoding="utf-8")


class TestHubExcludedFromAutoAssignment:
    def test_run_dispatch_excludes_hubs(self):
        src = _src("app/services/run_dispatch.py")
        assert "Truck.is_hub == False" in src, (
            "run_dispatch must exclude hub trucks — a hub exists for manual "
            "intra-day assembly, so the algorithm placing crew on it defeats "
            "the reason it exists (ADR-274 D2)"
        )

    def test_run_dispatch_filters_before_explicit_selection(self):
        # The hub clause must sit in the base query, NOT after the truck_ids
        # branch — otherwise an explicit selection passes a hub in by hand.
        src = _src("app/services/run_dispatch.py")
        hub_at = src.index("Truck.is_hub == False")
        branch_at = src.index("if truck_ids:")
        assert hub_at < branch_at, (
            "the hub filter must be in the base truck query, before the "
            "explicit truck_ids branch, or a caller can bypass it"
        )

    def test_run_sort_excludes_hubs(self):
        # A hub HAS a TruckAssignment, so run_sort's join would pull it into
        # package sorting without this.
        src = _src("app/services/run_sort.py")
        assert src.count("Truck.is_hub.is_(False)") >= 2, (
            "both the assigned-truck join and the pre-dispatch fallback must "
            "exclude hubs — a hub carries no delivery territory"
        )

    def test_captain_familiarisation_excludes_hubs(self):
        # Counting a hub would hold a captain in familiarisation against a truck
        # they can never complete a route on.
        src = _src("app/services/assign_captains.py")
        assert "Truck.is_hub == False" in src


class TestHubIsAColumnNotAStatus:
    def test_truck_model_has_is_hub(self):
        src = _src("app/models/truck.py")
        assert "is_hub" in src and "server_default=\"false\"" in src, (
            "is_hub must exist with a server default so the migration is "
            "additive and existing trucks keep their behaviour"
        )

    def test_truck_schemas_expose_is_hub(self):
        src = _src("app/schemas/truck.py")
        # create, update, and response — all three, or the admin page cannot
        # set it and the dispatch page cannot read it.
        assert src.count("is_hub") >= 3

    def test_dispatch_payload_sends_is_hub(self):
        # The frontend used to DERIVE hub-ness from status == 'planned', which
        # matched every truck before publish. It must be sent, not inferred.
        src = _src("app/routers/dispatch.py")
        assert '"is_hub"' in src, (
            "GET /dispatch/{date} must send is_hub per truck assignment "
            "(ADR-274) — deriving it client-side is the bug this replaced"
        )


class TestCreateHubRejectsNonHubTrucks:
    """The UI offers hub trucks only, but the ENDPOINT is the boundary.

    Without this guard a direct caller could create a hub assignment on a
    delivery truck — reintroducing "hub is a state some truck is in", which is
    the thing ADR-274 removed.
    """

    def test_create_hub_checks_is_hub(self):
        src = _src("app/routers/dispatch.py")
        assert "if not truck.is_hub:" in src, (
            "POST /dispatch/hubs must reject a truck that is not a hub"
        )

    def test_rejection_names_the_fix(self):
        # An error that says only "invalid" leaves the dispatcher stuck; this
        # one points at the Trucks page.
        src = _src("app/routers/dispatch.py")
        assert "is not a hub truck" in src and "Trucks" in src
