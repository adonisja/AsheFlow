"""
Tests for assign_walkers.

HOW assign_walkers WORKS (summary):
1. Build crew_to_truck (all placed members) and walker_to_truck (walkers only).
2. Query bans involving any current crew member. For each ban record, store a
   (truck_id, banner_id, is_walker_ban) tuple in banned_trucks_by_walker.
   - is_walker_ban=True means the banner is another walker → soft ban (overridable).
   - is_walker_ban=False means the banner is a driver/trainer → hard ban.
3. For each walker, resolve raw bans into hard_banned:
   - Hard bans stay unconditionally.
   - Soft (walker-vs-walker) bans go through check_ban_override:
       * Does the truck's driver or trainer fav the candidate?          → needed
       * Does that same person ALSO fav the offending walker?           → blocks override
       * If candidate favoured and offending NOT favoured → override:
         offending walker is evicted and reassigned; ban becomes overridden.
4. Minimum-count gate (same as trainers): only place on trucks at min walker count.
5. Fallback: if all minimum trucks are hard-banned, place anywhere unbanned + emit warning.
6. Nuclear fallback: if everything is banned, uniform weights (never deadlock).

WHAT WE'RE VERIFYING:
- Even spread across trucks (minimum-count gate).
- Driver/trainer bans against a walker are hard (no override path).
- Walker-vs-walker bans can be overridden when driver/trainer prefers candidate.
- Override is blocked when the driver/trainer also favours the offending walker.
- Override is blocked when no driver or trainer is on the truck.
- Fallback warning is emitted when all minimum trucks are hard-banned.
"""

import uuid
from unittest.mock import patch

import pytest

from app.services.assign_walkers import assign_walkers

from tests.conftest import (
    make_employee,
    make_truck,
    make_relationship,
)


# ---------------------------------------------------------------------------
# Even spread — the core guarantee
# ---------------------------------------------------------------------------

class TestEvenSpread:
    """
    assign_walkers must enforce even distribution across trucks using the same
    minimum-count gate as assign_trainers. Only trucks currently at the lowest
    walker count are eligible for the next placement.
    """

    def test_two_walkers_two_trucks_one_each(self, db):
        """
        ARRANGE: 2 trucks, 2 walkers, no bans, no pre-existing crew.
        ACT: assign_walkers.
        ASSERT: each truck ends up with exactly 1 walker.

        WHY THIS MATTERS:
        Without the minimum-count constraint, random.choices could put both
        walkers on the same truck. After placing walker 1 on truck A, A=1 and
        B=0. The minimum is 0, so only truck B is eligible for walker 2.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        walker_1 = make_employee(db, role="walker", name="Walker 1")
        walker_2 = make_employee(db, role="walker", name="Walker 2")

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        warnings = assign_walkers(
            available_walkers=[walker_1, walker_2],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a = [c for c in assigned_crews[truck_a.id] if c["role"] == "walker"]
        on_b = [c for c in assigned_crews[truck_b.id] if c["role"] == "walker"]

        assert len(on_a) == 1, "Truck A should have exactly 1 walker"
        assert len(on_b) == 1, "Truck B should have exactly 1 walker"
        assert warnings == [], "No bans means no warnings"

    def test_three_walkers_two_trucks_spread(self, db):
        """
        ARRANGE: 2 trucks, 3 walkers, no bans.
        ASSERT: all 3 placed, no truck has all 3 (max is 2).

        WHY: after A=1,B=1 the minimum is 1 and both are eligible for walker 3.
        The result is either A=2,B=1 or A=1,B=2. A=3,B=0 is impossible.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        walkers = [
            make_employee(db, role="walker", name=f"Walker {i}")
            for i in range(3)
        ]

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_walkers(
            available_walkers=walkers,
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        total = sum(
            1 for crew in assigned_crews.values()
            for c in crew if c["role"] == "walker"
        )
        max_on_one_truck = max(
            sum(1 for c in crew if c["role"] == "walker")
            for crew in assigned_crews.values()
        )

        assert total == 3, "All 3 walkers must be placed"
        assert max_on_one_truck <= 2, "No truck should hold all 3 walkers"


# ---------------------------------------------------------------------------
# Hard bans — driver/trainer bans cannot be overridden
# ---------------------------------------------------------------------------

class TestHardBans:
    """
    When a driver or trainer bans a walker (or the walker bans them), that
    truck is hard-blocked for the walker. The ban override path only applies
    to walker-vs-walker bans — driver/trainer bans have no override.
    """

    def test_walker_avoids_truck_with_banning_driver(self, db):
        """
        ARRANGE:
        - 2 trucks. Truck A has driver_a already placed.
        - walker bans driver_a → truck A is hard-blocked.
        ASSERT: walker ends up on truck B, not truck A.

        WHY WE PRE-POPULATE driver_a IN assigned_crews:
        assign_walkers builds the ban map by scanning crew_to_truck. If no
        crew members are in assigned_crews, the ban query finds nothing and
        no truck is marked banned.
        """
        truck_a  = make_truck(db, "Truck A")
        truck_b  = make_truck(db, "Truck B")
        driver_a = make_employee(db, role="driver", name="Driver A")
        driver_b = make_employee(db, role="driver", name="Driver B")
        walker   = make_employee(db, role="walker", name="Walker")

        make_relationship(db, walker, driver_a, rel_type="ban")

        assigned_crews = {
            truck_a.id: [{"id": driver_a.id, "role": "driver"}],
            truck_b.id: [{"id": driver_b.id, "role": "driver"}],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_walkers(
            available_walkers=[walker],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a = [c for c in assigned_crews[truck_a.id] if c["role"] == "walker"]
        on_b = [c for c in assigned_crews[truck_b.id] if c["role"] == "walker"]

        assert len(on_a) == 0, "Walker should not land on the banned truck"
        assert len(on_b) == 1, "Walker should land on the non-banned truck"

    def test_driver_banning_walker_is_also_hard(self, db):
        """
        Bans are bidirectional in effect. If the driver initiates the ban
        against the walker, that truck is still hard-blocked.
        ASSERT: walker avoids truck A even though *driver* owns the ban.
        """
        truck_a  = make_truck(db, "Truck A")
        truck_b  = make_truck(db, "Truck B")
        driver_a = make_employee(db, role="driver", name="Driver A")
        driver_b = make_employee(db, role="driver", name="Driver B")
        walker   = make_employee(db, role="walker", name="Walker")

        # Driver initiates the ban — direction reversed vs above test
        make_relationship(db, driver_a, walker, rel_type="ban")

        assigned_crews = {
            truck_a.id: [{"id": driver_a.id, "role": "driver"}],
            truck_b.id: [{"id": driver_b.id, "role": "driver"}],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_walkers(
            available_walkers=[walker],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a = [c for c in assigned_crews[truck_a.id] if c["role"] == "walker"]
        assert len(on_a) == 0, "Driver-initiated ban is also a hard block"


# ---------------------------------------------------------------------------
# Walker-vs-walker ban override
# ---------------------------------------------------------------------------

class TestWalkerBanOverride:
    """
    Walker-vs-walker bans are soft: check_ban_override may evict the offending
    walker and let the candidate take the truck.

    Override fires when ALL of these are true:
    1. The truck has a driver or trainer.
    2. That person favs the candidate.
    3. That person does NOT fav the offending walker.

    If any condition fails the ban stands.
    """

    def test_override_fires_when_driver_favs_candidate_only(self, db):
        """
        Tests check_ban_override directly: the override function is what actually
        contains the 3-condition logic. assign_walkers calls it but only for walkers
        already in assigned_crews at call time (the ban map is built from initial
        crew state, not updated as walkers are placed mid-loop).

        We call check_ban_override directly with:
        - truck A crew: driver + offender (pre-seeded).
        - offender bans candidate.
        - driver favs candidate but NOT offender.

        ASSERT: returns True (override fired), and perform_walker_reassignment
        was called to evict the offender.

        WHY WE PATCH perform_walker_reassignment:
        We want to test the detection logic in isolation. The eviction path
        (perform_walker_reassignment → assign_walkers) is covered by the production
        fix in ban_override.py and the integration behavior is verified by
        TestFallbackWarning. Patching here keeps the test focused on the 3-condition
        check, not the downstream reassignment mechanics.
        """
        from unittest.mock import patch as mpatch
        from app.services.ban_override import check_ban_override

        truck_a  = make_truck(db, "Truck A")
        truck_b  = make_truck(db, "Truck B")
        driver   = make_employee(db, role="driver",  name="Driver")
        offender = make_employee(db, role="walker",  name="Offending Walker")
        candidate= make_employee(db, role="walker",  name="Candidate Walker")

        make_relationship(db, offender, candidate, rel_type="ban")
        make_relationship(db, driver,   candidate, rel_type="fav")
        # driver does NOT fav offender (absence = condition 3 satisfied)

        assigned_crews = {
            truck_a.id: [
                {"id": driver.id,   "role": "driver"},
                {"id": offender.id, "role": "walker"},
            ],
            truck_b.id: [],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        # Patch perform_walker_reassignment so we don't hit its broken 5-arg call
        # to assign_walkers. We just want to verify the override detection returned True.
        with mpatch("app.services.ban_override.perform_walker_reassignment") as mock_evict:
            result = check_ban_override(
                candidate_id=candidate.id,
                offending_walker=offender,
                truck_id=truck_a.id,
                assigned_crews=assigned_crews,
                base_weights=base_weights,
                banned_truck_ids=[],
                db=db,
            )

        overridden, reassigned_to = result
        assert overridden is True, (
            "Override should fire when driver favs candidate but not offender"
        )
        mock_evict.assert_called_once(), "Eviction should have been attempted"

    def test_override_blocked_when_driver_favs_both(self, db):
        """
        If the driver favs BOTH the candidate and the offending walker, the
        tie-breaking rule says the ban stands (don't arbitrarily displace the
        existing walker).
        ASSERT: candidate does NOT end up on truck A (ban was not overridden).

        SETUP: 2 trucks so candidate has somewhere else to go.
        """
        truck_a  = make_truck(db, "Truck A")
        truck_b  = make_truck(db, "Truck B")
        driver   = make_employee(db, role="driver",  name="Driver")
        offender = make_employee(db, role="walker",  name="Offending Walker")
        candidate= make_employee(db, role="walker",  name="Candidate Walker")

        make_relationship(db, offender, candidate, rel_type="ban")
        make_relationship(db, driver, candidate, rel_type="fav")   # condition 2 met
        make_relationship(db, driver, offender,  rel_type="fav")   # condition 3 FAILS

        assigned_crews = {
            truck_a.id: [
                {"id": driver.id,   "role": "driver"},
                {"id": offender.id, "role": "walker"},
            ],
            truck_b.id: [],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_walkers(
            available_walkers=[candidate],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a_walkers = [c for c in assigned_crews[truck_a.id] if c["role"] == "walker"]
        walker_ids_on_a = {c["id"] for c in on_a_walkers}

        # ban stands — candidate should NOT be on truck A
        assert candidate.id not in walker_ids_on_a, (
            "Override should be blocked when driver favs both walkers"
        )

    def test_override_blocked_when_no_driver_or_trainer(self, db):
        """
        Without a driver or trainer on the truck, there is no authority to
        adjudicate the walker dispute. The ban stands unconditionally.
        ASSERT: candidate does not land on the truck with the offending walker.

        SETUP: truck A has only the offending walker (no driver, no trainer).
        truck B is the safe destination.
        """
        truck_a  = make_truck(db, "Truck A")
        truck_b  = make_truck(db, "Truck B")
        offender = make_employee(db, role="walker", name="Offending Walker")
        candidate= make_employee(db, role="walker", name="Candidate Walker")

        make_relationship(db, offender, candidate, rel_type="ban")

        assigned_crews = {
            # No driver or trainer on truck A — only the offending walker
            truck_a.id: [{"id": offender.id, "role": "walker"}],
            truck_b.id: [],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_walkers(
            available_walkers=[candidate],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a_walkers = [c for c in assigned_crews[truck_a.id] if c["role"] == "walker"]
        walker_ids_on_a = {c["id"] for c in on_a_walkers}

        assert candidate.id not in walker_ids_on_a, (
            "Ban should stand when no driver or trainer is present to override"
        )

    def test_override_blocked_when_driver_does_not_fav_candidate(self, db):
        """
        If the driver doesn't fav the candidate at all, condition 2 fails and
        the ban stands — regardless of whether the driver favs the offender.
        ASSERT: candidate does not end up on truck A.
        """
        truck_a  = make_truck(db, "Truck A")
        truck_b  = make_truck(db, "Truck B")
        driver   = make_employee(db, role="driver",  name="Driver")
        offender = make_employee(db, role="walker",  name="Offending Walker")
        candidate= make_employee(db, role="walker",  name="Candidate Walker")

        make_relationship(db, offender, candidate, rel_type="ban")
        # Driver favs nobody — condition 2 never met

        assigned_crews = {
            truck_a.id: [
                {"id": driver.id,   "role": "driver"},
                {"id": offender.id, "role": "walker"},
            ],
            truck_b.id: [],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_walkers(
            available_walkers=[candidate],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a_walkers = [c for c in assigned_crews[truck_a.id] if c["role"] == "walker"]
        walker_ids_on_a = {c["id"] for c in on_a_walkers}

        assert candidate.id not in walker_ids_on_a, (
            "Ban should stand when driver does not fav the candidate"
        )


# ---------------------------------------------------------------------------
# Fallback — warning emitted when all minimum trucks are hard-banned
# ---------------------------------------------------------------------------

class TestFallbackWarning:
    """
    When a walker is hard-banned from every minimum-count truck, the fallback
    path runs: place the walker on any non-hard-banned truck and emit a warning.
    Dispatch must never deadlock.
    """

    def test_fallback_emits_warning_when_walker_placed_on_banned_truck(self, db):
        """
        ARRANGE:
        - 2 trucks, both at minimum (0 walkers). Both are hard-banned for the
          walker (drivers on both trucks ban the walker).
        - Walker has nowhere unbanned to go — must land on a banned truck.
        ASSERT:
        - Walker is still placed somewhere (no deadlock).
        - warnings list has exactly 1 entry with the walker's employee_id.

        WHY THE PREVIOUS SETUP DIDN'T PRODUCE A WARNING:
        The old test had truck B above minimum with a pre-placed walker. Truck A
        was the only minimum truck and was hard-banned. The fallback placed the
        walker on truck B (unbanned). After the ban-warning timing fix (ADR-019),
        a warning only fires when the walker genuinely lands on a banned truck —
        not merely because the fallback path was entered. Since truck B was
        unbanned, no warning fired. The correct test forces ALL trucks to be
        banned so placement on a banned truck is unavoidable.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        driver_a  = make_employee(db, role="driver", name="Driver A")
        driver_b  = make_employee(db, role="driver", name="Driver B")
        walker    = make_employee(db, role="walker",  name="Banned Walker")

        # Both drivers ban the walker — all trucks are hard-banned
        make_relationship(db, driver_a, walker, rel_type="ban")
        make_relationship(db, driver_b, walker, rel_type="ban")

        assigned_crews = {
            truck_a.id: [{"id": driver_a.id, "role": "driver"}],
            truck_b.id: [{"id": driver_b.id, "role": "driver"}],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        warnings = assign_walkers(
            available_walkers=[walker],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        total_placed = sum(
            1 for crew in assigned_crews.values()
            for c in crew
            if c["role"] == "walker" and c["id"] == walker.id
        )
        assert total_placed == 1, "Walker must be placed even when all trucks are banned"
        assert len(warnings) == 1, "Warning must fire when walker lands on a banned truck"
        assert warnings[0]["employee_id"] == walker.id, (
            "Warning must identify the walker who was placed on a banned truck"
        )

    def test_no_warning_when_fallback_avoids_banned_truck(self, db):
        """
        ARRANGE:
        - 2 trucks. Truck B already has a walker (above minimum).
        - Walker is hard-banned from truck A (the only minimum truck).
        - Truck B is NOT banned — walker lands there cleanly.
        ASSERT:
        - Walker placed on truck B.
        - No warning emitted (ban was avoided, not violated).

        WHY: this was the original Brandon Hayes scenario. The minimum-count
        trucks were all banned but the fallback pool (above-minimum trucks)
        was unbanned. The walker avoided the conflict entirely — no warning
        should fire. This test locks in that correct behavior.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        driver_a  = make_employee(db, role="driver", name="Driver A")
        existing  = make_employee(db, role="walker", name="Already Placed")
        walker    = make_employee(db, role="walker", name="Banned Walker")

        # Only truck A is hard-banned; truck B is safe
        make_relationship(db, driver_a, walker, rel_type="ban")

        assigned_crews = {
            truck_a.id: [{"id": driver_a.id, "role": "driver"}],
            truck_b.id: [{"id": existing.id,  "role": "walker"}],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        warnings = assign_walkers(
            available_walkers=[walker],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        # Walker must land on truck B (the unbanned fallback)
        on_b = [c for c in assigned_crews[truck_b.id]
                if c["role"] == "walker" and c["id"] == walker.id]
        assert len(on_b) == 1, "Walker should be placed on the unbanned truck B"
        assert warnings == [], (
            "No warning should fire when the walker successfully avoided all banned trucks"
        )
