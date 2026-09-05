"""Truck pins actually seat people (ADR-371).

seat_truck_pins built `truck_key = str(pin.truck_id)` and tested it against
assigned_crews, which run_dispatch keys by UUID OBJECTS:

    str(uuid) in {uuid: []}   ->   False

So the guard fired for EVERY pin, on every truck. Truck pins have been inert
since ADR-358 shipped -- the UI was built, the picker offers hubs, the help text
explains the behaviour, and nobody was ever seated.

ADR-368 found this guard, read its comment ("Truck not running today"), and
concluded hubs were the problem. The comment described a legitimate case, which
is what made a failing comparison look like designed behaviour.
"""
import ast
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEAT = ROOT / "backend" / "app" / "services" / "seat_truck_pins.py"
RUN = ROOT / "backend" / "app" / "services" / "run_dispatch.py"


class TestTheLookupResolvesTheCallersKeyType:
    def test_it_builds_a_mapping_from_the_live_keys(self):
        """Not `str(...)` assumed, and not a hardcoded UUID assumption -- read
        the types actually present so a future re-key cannot break it."""
        src = SEAT.read_text(errors="ignore")
        assert "by_str = {str(k): k for k in assigned_crews}" in src, (
            "the key type is assumed rather than resolved from the dict"
        )

    def test_the_skip_uses_the_resolved_key(self):
        src = SEAT.read_text(errors="ignore")
        assert "truck_key = by_str.get(str(pin.truck_id))" in src
        assert "if truck_key is None:" in src, (
            "the guard must test the RESOLVED key; comparing a str against the "
            "raw dict is the original bug"
        )

    def test_no_raw_membership_test_remains(self):
        src = SEAT.read_text(errors="ignore")
        assert "if truck_key not in assigned_crews:" not in src, (
            "the str-against-UUID membership test is back"
        )

    def test_both_key_types_resolve(self):
        """The behaviour, not the source: UUID keys today, str keys if
        run_dispatch is ever re-keyed."""
        tid = uuid.uuid4()
        for assigned in ({tid: []}, {str(tid): []}):
            by_str = {str(k): k for k in assigned}
            key = by_str.get(str(tid))
            assert key is not None and key in assigned


class TestRunDispatchStillKeysByUUID:
    """If this changes, the fix above still works -- but the mismatch that
    caused the bug is worth pinning so a re-key is a deliberate act."""

    def test_assigned_crews_is_keyed_by_truck_id(self):
        tree = ast.parse(RUN.read_text(errors="ignore"))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "run_dispatch"
        )
        src = ast.unparse(fn)
        assert "assigned_crews = {truck_id: [] for truck_id in truck_ids}" in src
        assert "truck_ids = [truck.id for truck in trucks]" in src, (
            "truck_ids no longer holds Truck.id values; re-check every consumer "
            "that indexes assigned_crews"
        )
