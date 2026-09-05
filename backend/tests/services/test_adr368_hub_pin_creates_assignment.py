"""A pin to a hub creates the hub's assignment and seats the crew (ADR-368).

The truck-pin picker deliberately offers hubs (ADR-358), the backend accepts the
pin, and the help drawer promises the pin "holds the crew member to the truck".
Dispatch then ignored it, because:

    trucks = ...filter(Truck.is_hub == False)      # run_dispatch
    assigned_crews = {truck_id: [] for truck_id in truck_ids}

    if truck_key not in assigned_crews:            # seat_truck_pins
        continue                                   # "truck not running today"

A hub is NEVER in assigned_crews, so that skip was permanent rather than a
statement about today's selection. Creating the hub assignment by hand did not
help either, because the exclusion happens at truck-SELECTION time.

The boundary these tests protect most carefully is ADR-286 D1: a hub -- however
it was created -- must never make the day look dispatched.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "backend" / "app" / "services" / "run_dispatch.py"
ROUTER = ROOT / "backend" / "app" / "routers" / "dispatch.py"


def _run_dispatch_source() -> str:
    tree = ast.parse(RUN.read_text(errors="ignore"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "run_dispatch"
    )
    return ast.unparse(fn)


class TestOnlyPinnedHubsJoinTheRun:
    def test_the_query_requires_a_hub_with_a_pin(self):
        src = _run_dispatch_source()
        i = src.index("_pinned_hubs")
        window = src[i: i + 900]
        assert "TruckPin" in window, "hubs are not selected via a pin"
        assert "Truck.is_hub == True" in window, (
            "the query must be restricted to hubs; ordinary trucks are already "
            "selected by the normal path"
        )

    def test_it_is_scoped_to_this_weekday(self):
        """A Tuesday pin must not create the hub on Wednesday."""
        src = _run_dispatch_source()
        i = src.index("_pinned_hubs")
        window = src[i: i + 900]
        assert "TruckPin.day_of_week ==" in window, (
            "without a weekday filter, a pin creates the hub every day"
        )

    def test_it_is_company_scoped_on_both_tables(self):
        """Dimension 1. A pin in company A must not create an assignment in B."""
        src = _run_dispatch_source()
        i = src.index("_pinned_hubs")
        window = src[i: i + 900]
        assert "TruckPin.company_id == company_id" in window
        assert "Truck.company_id == company_id" in window, (
            "joining Truck without scoping it lets another tenant's hub in"
        )

    def test_a_hub_with_no_pin_is_not_added(self):
        """The trigger is the pin, not the existence of a hub -- otherwise every
        hub gets an assignment every day."""
        src = _run_dispatch_source()
        # Matched loosely: ast.unparse normalises `for (hub_id,)` to
        # `for hub_id,`, so an exact-string assertion pins formatting rather
        # than behaviour.
        assert re.search(r"for hub_id,?\s*\)? in _pinned_hubs", src), (
            "hubs must be added from the pinned-hub query, not from all hubs"
        )


class TestTheAssignmentIsMarkedAndIdempotent:
    def test_only_hubs_the_run_created_are_marked(self):
        src = _run_dispatch_source()
        # ast.unparse rewrites quotes and collapses the call onto one line, so
        # this asserts the CONDITION rather than the literal source text.
        assert re.search(
            r"auto_created_reason=.truck_pin.\s+if\s+truck_id in hub_truck_ids\s+else None", src
        ), (
            "an ordinary truck is the dispatcher asking for a run and must not "
            "be marked auto-created"
        )

    def test_an_existing_hub_assignment_is_reused(self):
        """ADR-368 D4 -- the operator's original workaround was to create the hub
        by hand. That must now work, without a duplicate row."""
        src = _run_dispatch_source()
        i = src.index("if truck_id in hub_truck_ids:")
        window = src[i: i + 700]
        assert "TruckAssignment" in window and ".first()" in window, (
            "an existing hub assignment is not looked up, so a second row is "
            "created alongside the dispatcher's"
        )

    def test_a_hand_created_row_is_not_relabelled(self):
        """auto_created_reason is set only on the row the run creates itself."""
        src = _run_dispatch_source()
        i = src.index("if truck_assignment is None:")
        after = src[i:]
        assert "auto_created_reason" in after[:600], (
            "the marker must be inside the creation branch"
        )
        before = src[:i]
        assert "auto_created_reason" not in before[before.index("hub_truck_ids"):], (
            "auto_created_reason is set outside the creation branch, so a "
            "dispatcher's own row would be relabelled as auto-created"
        )


class TestTheADR286BoundaryStillHolds:
    """The load-bearing guarantee. A hub -- created by hand or by the run --
    contributes no workflow phase and does not trip the double-dispatch guard.
    Both derive hub-ness from Truck.is_hub, so neither cares how the assignment
    came to exist; these pin that so a future change cannot key off the new
    column instead."""

    def test_workflow_status_still_filters_on_is_hub(self):
        src = ROUTER.read_text(errors="ignore")
        i = src.index("operational_statuses = {")
        window = src[i: i + 300]
        assert 'not s["is_hub"]' in window, (
            "workflow_status must exclude hubs by is_hub, not by whether the "
            "assignment was auto-created"
        )

    def test_the_409_guard_still_filters_on_is_hub(self):
        src = ROUTER.read_text(errors="ignore")
        i = src.index("def trigger_dispatch")
        window = src[i: i + 1400]
        assert "Truck.is_hub == False" in window, (
            "the double-dispatch guard must keep ignoring hubs, or an "
            "auto-created hub blocks the next day's run"
        )

    def test_nothing_keys_the_workflow_off_auto_created_reason(self):
        """A tempting future 'simplification'. The column answers WHY a row
        exists, never whether dispatch ran."""
        src = ROUTER.read_text(errors="ignore")
        for m in re.finditer(r"auto_created_reason", src):
            seg = src[max(0, m.start() - 200): m.start() + 200]
            assert "workflow_status" not in seg, (
                "workflow_status is being derived from auto_created_reason; "
                "ADR-286 D1 requires it to derive from is_hub"
            )


class TestPublishDoesNotDoublePostAHub:
    """D8 finding from the audit. publish_dispatch selected EVERY assignment for
    the date with no hub filter, and the bot iterates that payload to post crew
    embeds to the drivers channel.

    A hub publishes through its own endpoint (publish_hub) with its own channel
    and notifications, so publishing it here double-posts it and sends a crew
    embed for a truck that runs no route.

    Reachable before ADR-368 -- a dispatcher could always create a hub by hand --
    but auto-created hubs make it the common case rather than a rarity.
    """

    def _publish_source(self) -> str:
        tree = ast.parse(ROUTER.read_text(errors="ignore"))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "publish_dispatch"
        )
        return ast.unparse(fn)

    def test_it_excludes_hubs(self):
        src = self._publish_source()
        assert "Truck.is_hub == False" in src, (
            "publish_dispatch publishes hubs through the ordinary flow, "
            "double-posting them and sending a drivers-channel embed for a "
            "truck that runs no route"
        )

    def test_the_join_is_company_scoped(self):
        """Dimension 1: joining Truck without scoping it widens the query."""
        src = self._publish_source()
        i = src.index("Truck.is_hub == False")
        window = src[max(0, i - 500): i]
        assert "Truck.company_id == caller.company_id" in window, (
            "the Truck join must be company-scoped"
        )
