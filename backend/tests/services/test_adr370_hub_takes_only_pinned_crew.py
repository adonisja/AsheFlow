"""A hub receives its pinned crew and nothing else (ADR-370).

ADR-368 added hubs to assigned_crews so seat_truck_pins could reach them, and
claimed "nobody is DRAWN onto a hub -- the later passes never see these keys as
candidates, they only find them already occupied."

That was wrong. Seven passes run after seating and every one iterates
assigned_crews; only assign_captains mentions is_hub at all. The first real run
put FIFTEEN people on the hub -- five trainers, walkers, the lot.

The claim came from reasoning about what the passes do to a FULL truck. A hub
with one pinned walker looks to assign_walkers exactly like an under-staffed one.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "backend" / "app" / "services" / "run_dispatch.py"

# Every pass that runs after seating and iterates assigned_crews.
LATER_PASSES = (
    "assign_drivers", "seat_crew_pins", "assign_captains", "assign_trainers",
    "assign_driver_trainees", "assign_trainees", "assign_walkers",
    "rebalance_crews",
)


def _source() -> str:
    tree = ast.parse(RUN.read_text(errors="ignore"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "run_dispatch"
    )
    return ast.unparse(fn)


class TestHubsAreAbsentWhileTheOtherPassesRun:
    def test_hub_keys_are_removed_after_seating(self):
        src = _source()
        assert re.search(r"hub_crews\s*=\s*\{.*assigned_crews\.pop", src), (
            "hub keys are not lifted out of assigned_crews, so every later pass "
            "treats the hub as an under-staffed truck"
        )

    def test_every_later_pass_runs_after_the_removal(self):
        """The load-bearing assertion. A pass placed above the pop() would see
        the hub -- which is precisely the ADR-368 bug."""
        src = _source()
        pop_at = src.index("hub_crews = {")
        for name in LATER_PASSES:
            call = f"{name}("
            if call not in src:
                continue
            assert src.index(call) > pop_at, (
                f"{name} runs BEFORE hubs are removed from assigned_crews, so it "
                "can place crew on a hub"
            )

    def test_rebalance_cannot_move_anyone_onto_a_hub(self):
        """D2 -- rebalance_crews evens out crew sizes and would treat a hub with
        one pinned walker as the obvious place to move people."""
        src = _source()
        assert src.index("hub_crews = {") < src.index("rebalance_crews("), (
            "rebalance_crews sees the hub and will move crew onto it"
        )

    def test_the_hubs_are_merged_back_for_persistence(self):
        """Removed for the passes, restored for the write -- or the hub gets an
        assignment with no crew, or no assignment at all."""
        src = _source()
        assert "assigned_crews.update(hub_crews)" in src, (
            "hub crews are never merged back, so the pinned members are lost"
        )
        merge_at = src.index("assigned_crews.update(hub_crews)")
        persist_at = src.index("for truck_id, crew in assigned_crews.items():")
        assert merge_at < persist_at, "the merge happens after persistence"


class TestHubsSortFirst:
    def test_the_query_orders_hubs_first_then_by_name(self):
        src = _source()
        assert "Truck.is_hub.desc()" in src, (
            "hubs are not sorted first; the board renders insertion order, so an "
            "unordered query puts them in arbitrary positions"
        )
        i = src.index("Truck.is_hub.desc()")
        assert "Truck.name" in src[i: i + 120], (
            "non-hub trucks must still be ordered by name"
        )

    def test_the_ordering_query_is_company_scoped(self):
        """Dimension 1 -- joining Truck without scoping it widens the query."""
        src = _source()
        i = src.index("Truck.is_hub.desc()")
        window = src[max(0, i - 700): i]
        assert "Truck.company_id == company_id" in window, (
            "the Truck join for ordering is not company-scoped"
        )
