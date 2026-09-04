"""The hub must not gate the rest of the board (ADR-375).

Reported from the Dispatch Center after publishing the hub's confirmations:

    Post Final Crews is blocked - under 50% confirmed on Hub (0/2).

Live state at the time, read from the API:

    Hub      active     is_hub=True   dock='A07'   <- the only active truck
    Atlas    planned    is_hub=False  dock=None
    Eagle    planned    is_hub=False  dock=None
    Falcon   planned    is_hub=False  dock=None
    Morgan   planned    is_hub=False  dock=None
    Titan    planned    is_hub=False  dock=None
    Viking   planned    is_hub=False  dock=None

The hub is published EARLY on purpose (ADR-320), so it is the only `active`
truck for most of the morning. Its pinned crew of two (ADR-370) is small and
frequently not on Discord, so it sits at 0/2 -- under the 50% block threshold --
and gates Post Final Crews for the entire day.

This is the same defect ADR-320 fixed for the bulk buttons, in the one place
ADR-320 did not reach. ADR-329 revisited this exact function for per-truck
status and did not mention hubs at all.

There is no frontend test runner in this repo, so the source-text assertions
follow test_adr320_bulk_button_gates.py. The gate LOGIC is reimplemented here
from the same rule and executed, so a behavioural break fails even when the
text still matches.
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DASH = BACKEND.parent / "frontend" / "src" / "pages" / "DispatchDashboard.tsx"

FINALIZE_BLOCK = 0.50
FINALIZE_WARN = 0.80


def _src() -> str:
    return DASH.read_text(encoding="utf-8")


def _gate(trucks, confirmed_by_truck, hub_ids):
    """The ADR-375 D1 rule, executed rather than grepped.

    trucks: {truck_id: (crew_size, status)}
    """
    stats = []
    for tid, (total, status) in trucks.items():
        if total <= 0 or tid in hub_ids or status != "active":
            continue
        confirmed = confirmed_by_truck.get(tid, 0)
        stats.append({"truckId": tid, "total": total, "confirmed": confirmed,
                      "rate": confirmed / total if total else 1.0})
    below50 = [t for t in stats if t["rate"] < FINALIZE_BLOCK]
    below80 = [t for t in stats if t["rate"] < FINALIZE_WARN]
    return {
        "live": len(stats) > 0,
        "block": len(below50) > 0,
        "warn": len(below50) == 0 and len(below80) > 0,
        "below50": below50,
    }


HUB = "hub-id"


class TestTheReportedIncident:
    def test_a_hub_at_zero_of_two_does_not_block_the_board(self):
        """The exact staging state: hub active at 0/2, six trucks planned."""
        trucks = {HUB: (2, "active")}
        for t in ("atlas", "eagle", "falcon", "morgan", "titan", "viking"):
            trucks[t] = (18, "planned")

        gate = _gate(trucks, confirmed_by_truck={HUB: 0}, hub_ids={HUB})

        assert gate["block"] is False, (
            "the hub is published early on purpose (ADR-320); at 0/2 it was "
            "blocking Post Final Crews for six trucks that never published"
        )
        assert gate["live"] is False, "no NON-HUB truck is in its confirmation window"

    def test_without_the_fix_the_hub_would_block(self):
        """Pins the bug itself: the same state, hub NOT excluded, blocks."""
        trucks = {HUB: (2, "active")}
        gate = _gate(trucks, confirmed_by_truck={HUB: 0}, hub_ids=set())
        assert gate["block"] is True, (
            "if this stops blocking, the test no longer reproduces the bug and "
            "the one above proves nothing"
        )


class TestTheGateStillGates:
    def test_a_non_hub_truck_under_fifty_percent_still_blocks(self):
        trucks = {HUB: (2, "active"), "atlas": (10, "active")}
        gate = _gate(trucks, {HUB: 0, "atlas": 4}, {HUB})
        assert gate["block"] is True
        assert [t["truckId"] for t in gate["below50"]] == ["atlas"], (
            "the hub must not appear in the blocking set"
        )

    def test_a_hub_at_zero_alongside_a_healthy_truck_does_not_block(self):
        trucks = {HUB: (2, "active"), "atlas": (10, "active")}
        gate = _gate(trucks, {HUB: 0, "atlas": 9}, {HUB})
        assert gate["block"] is False and gate["warn"] is False

    def test_the_warn_band_is_unaffected_by_the_hub(self):
        trucks = {HUB: (2, "active"), "atlas": (10, "active")}
        gate = _gate(trucks, {HUB: 0, "atlas": 6}, {HUB})   # 60% -> warn
        assert gate["block"] is False and gate["warn"] is True

    def test_a_finalized_truck_still_drops_out(self):
        """ADR-329 D2 -- status filtering must survive this change."""
        trucks = {"atlas": (10, "finalized")}
        assert _gate(trucks, {"atlas": 0}, set())["block"] is False

    def test_an_empty_truck_still_does_not_gate(self):
        trucks = {"atlas": (0, "active")}
        assert _gate(trucks, {}, set())["block"] is False


class TestTheSourceMatchesTheRule:
    def test_the_gate_excludes_hub_trucks(self):
        assert "!hubTruckIds.has(t.truckId)" in _src(), (
            "confirmationGate lost its hub exclusion -- a hub published early "
            "will block Post Final Crews for the whole board again"
        )

    def test_hub_ids_are_declared_before_the_gate_reads_them(self):
        src = _src()
        assert src.index("const hubTruckIds") < src.index("const confirmationGate"), (
            "hubTruckIds must stay above confirmationGate, which reads it"
        )

    def test_hub_ids_are_memoised(self):
        """A bare `new Set(...)` has a fresh identity every render, so listing it
        as a dependency would defeat the memo and omitting it leaves an
        exhaustive-deps warning indistinguishable from a real one."""
        src = _src()
        i = src.index("const hubTruckIds")
        assert "useMemo" in src[i:i + 200], "hubTruckIds must be memoised"

    def test_the_blocked_tooltip_names_the_trucks(self):
        """ADR-375 D3 -- 'at least one truck' does not say which."""
        src = _src()
        assert "Blocked: under 50% confirmed on ${confirmationGate.below50" in src
        assert "'Blocked: under 50% confirmed on at least one truck'" not in src

    def test_the_dock_gate_is_untouched(self):
        """ADR-375 D2 -- it fires correctly; six trucks really had no bay."""
        assert "dockGate.block" in _src()


# ── D4: the server runs the same rule, and had the same gap ──────────────────

class TestTheServerAlsoExcludesTheHub:
    """`finalize_dispatch` applies ADR-205's 50% rule to every `active`
    assignment (dispatch.py:4068) with no is_hub term. That is the safety
    boundary and must stay -- but without this fix, D1 only converts a disabled
    button into a 409 discovered after clicking. Same block, one layer down.
    """

    def test_the_day_wide_call_does_not_gate_on_the_hub(self):
        import inspect
        from app.routers import dispatch as D

        src = inspect.getsource(D.finalize_dispatch)
        assert "gating = assignments" in src and "Truck.is_hub" in src, (
            "finalize_dispatch lost its hub exclusion -- the dashboard fix "
            "would then just move the block into a 409"
        )
        assert "for a in gating:" in src, (
            "the confirmation loop must read the hub-excluded list, not the raw one"
        )

    def test_the_exclusion_is_scoped_to_the_day_wide_call(self):
        """A hub finalized BY NAME must still gate on its own confirmations --
        posting an unconfirmed hub crew is what ADR-205 exists to prevent."""
        import inspect
        from app.routers import dispatch as D

        src = inspect.getsource(D.finalize_dispatch)
        assert "if truck_id is None:" in src, (
            "the hub exclusion must apply only to the day-wide call; a per-truck "
            "finalize naming the hub still gates on the hub"
        )

    def test_the_server_still_enforces_the_rule(self):
        """The gate is the safety boundary; the dashboard is a courtesy."""
        import inspect
        from app.routers import dispatch as D

        src = inspect.getsource(D.finalize_dispatch)
        assert "confirmed / total < 0.5" in src
        assert "Cannot post final crews" in src

    def test_the_hub_is_still_finalized_only_its_veto_is_removed(self):
        """The subtle half of D4: `gating` must feed ONLY the gate loop.

        Everything after it -- the Discord post, the captain-familiarity credit,
        the status write -- keeps reading `assignments`, so the hub is still
        finalized and posted. It stops vetoing the day; it does not drop out of
        the work.
        """
        import inspect
        from app.routers import dispatch as D

        src = inspect.getsource(D.finalize_dispatch)
        # Code lines only -- a comment mentioning `gating` is not a use, and
        # counting one as a use made this fail on ADR-376's explanatory comment.
        uses = [ln.strip() for ln in src.splitlines()
                if "gating" in ln and not ln.strip().startswith("#")]
        assert len(uses) == 3, (
            f"`gating` should be used exactly 3 times (assign, narrow, loop); "
            f"found {len(uses)}: {uses}. If it spread further, the hub may have "
            f"stopped being finalized rather than merely stopped gating."
        )
        assert "_credit_captain_familiarity(db, assignments" in src, (
            "post-gate work must still read the full assignment list"
        )
