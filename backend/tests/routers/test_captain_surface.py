"""A captain can reach the work their role owns (ADR-274 D19 / ADR-256).

THE GAP
-------
ADR-256 made `captain` a first-class role: a truck's route lead, who runs the
anchor-point sort, owns RTS and reattempts, and answers for the crew. The
backend honours that — 88 captain tests pass, `ROUTE_LEAD_ROLES` contains
captain, and `rts._is_elevated_for_route` implements D11's truck-scoped split.

The UI did not. `captain` appeared in **none** of mobile's 16 role tuples, so a
captain logging in got **zero tabs** — no Field Ops, no Route Sort, no
Reattempts. Every authority ADR-256 granted them was unreachable from the device
they actually carry.

`field_ops.py` had four hardcoded role lists, none naming captain, so even the
screens would have 403'd on write.

WHAT THIS PINS
--------------
1. the tabs a captain must have (the role's operational surface)
2. the tabs they must NOT have (D5 moved route-lead authority, not training)
3. the field_ops gates that make those tabs work
4. that vehicle acts stay with the driver (D4: distinct slots, same truck)
"""
import re
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
ROLES = BACKEND.parent / "mobile" / "src" / "navigation" / "roles.ts"
NAV = BACKEND.parent / "mobile" / "src" / "navigation" / "index.tsx"
FIELD_OPS = BACKEND / "app" / "routers" / "field_ops.py"


def _tuples() -> dict[str, str]:
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"export const (\w+)\s*=\s*\[([^\]]*)\]",
                             ROLES.read_text(encoding="utf-8"))
    }


class TestCaptainHasATabSurface:
    @pytest.mark.parametrize("tuple_name,why", [
        ("FIELD_OPS_ROLES",     "the captain's core station-and-road workflow"),
        ("ROUTE_SORT_ROLES",    "ADR-256 D5: route assignment is the captain's"),
        ("REATTEMPT_ROLES",     "the captain owns reattempts"),
        ("ANCHOR_POINT_ROLES",  "the captain leads the anchor point"),
        ("INCIDENT_ROLES",      "a route lead reports incidents"),
        ("SCHEDULE_ROLES",      "every field role needs their own schedule"),
        ("GEAR_ROLES",          "every field role requests gear"),
        ("PREFERENCES_ROLES",   "every field role sets preferences"),
    ])
    def test_captain_is_in_tuple(self, tuple_name: str, why: str):
        t = _tuples()
        assert tuple_name in t, f"{tuple_name} no longer exists"
        assert "captain" in t[tuple_name], (
            f"captain cannot reach {tuple_name} — {why}. Before ADR-274 D19 a "
            "captain had ZERO tabs and could not work from mobile at all."
        )

    def test_captain_actually_resolves_to_tabs(self):
        # Guards the guard: the tuples above are only meaningful if the nav
        # registry references them. A tuple nothing uses grants nothing.
        t = _tuples()
        nav = NAV.read_text(encoding="utf-8")
        labels = [
            m.group(2)
            for m in re.finditer(r"key: '(\w+)',\s*label: '([^']*)'[^}]*?roles: (\w+)",
                                 nav, re.S)
            if m.group(3) in t and "captain" in t[m.group(3)]
        ]
        assert len(labels) >= 8, (
            f"captain resolves to only {len(labels)} tabs ({labels}) — the role "
            "tuples may no longer be wired into the nav registry"
        )


class TestTrainingSurfacesStayWithTrainers:
    """D5 moved route-lead authority. It did NOT move training supervision."""

    @pytest.mark.parametrize("tuple_name", [
        "TRAINER_ROLES", "TRAINEE_ROLES", "WALKER_ROLES",
    ])
    def test_captain_is_not_in_training_tuple(self, tuple_name: str):
        t = _tuples()
        assert "captain" not in t.get(tuple_name, ""), (
            f"captain added to {tuple_name} — D5 moved ROUTE-LEAD authority to "
            "captains and deliberately left training supervision with trainers. "
            "Widening this silently re-tangles the two authorities the ADR split."
        )


class TestFieldOpsGates:
    def _gate(self, name: str) -> str:
        src = FIELD_OPS.read_text(encoding="utf-8")
        m = re.search(rf'^{name}\s*=\s*RoleChecker\(\[([^\]]*)\]', src, re.M)
        assert m, f"{name} gate not found"
        return m.group(1)

    def test_captain_can_record_station_arrival(self):
        assert "captain" in self._gate("allow_field_staff"), (
            "a captain arriving at the station cannot record it, so their own "
            "attendance is invisible"
        )

    def test_captain_can_rate_peers(self):
        assert "captain" in self._gate("allow_crew"), (
            "a captain cannot submit peer ratings (ADR-201) despite crewing the "
            "truck like everyone else"
        )

    def test_vehicle_acts_stay_with_the_driver(self):
        # ADR-256 D4: driver and captain are DISTINCT slots on the same truck,
        # so the captain is not the person behind the wheel. Pre-trip inspection
        # and fuel logging are acts of whoever drives it.
        assert "captain" not in self._gate("allow_driver"), (
            "captain added to allow_driver — that gates vehicle inspection and "
            "fuel logs, which belong to the driver (ADR-256 D4)"
        )

    def test_oversight_gate_untouched(self):
        assert "captain" not in self._gate("allow_management"), (
            "captain is a truck-scoped field role, not station oversight"
        )


class TestBackendAlreadySupportsThem:
    """The authority the tabs now reach — pinned so a revert is visible."""

    def test_captain_is_a_route_lead(self):
        src = (BACKEND / "app" / "services" / "constants.py").read_text(encoding="utf-8")
        block = src[src.index("ROUTE_LEAD_ROLES"):src.index("TRUCK_SCOPED_ROLES")]
        assert '"captain"' in block

    def test_captain_elevation_is_truck_scoped_not_blanket(self):
        # ADR-256 D11: adding captain to a blanket is_elevated would let a
        # captain on truck 1 write stops on truck 6.
        src = (BACKEND / "app" / "routers" / "rts.py").read_text(encoding="utf-8")
        assert "def _is_elevated_for_route(" in src, (
            "the truck-scoped elevation helper is gone — captain elevation may "
            "have reverted to a blanket role list (ADR-256 D11)"
        )
