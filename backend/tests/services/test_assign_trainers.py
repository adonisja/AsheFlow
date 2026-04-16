"""
Tests for assign_trainers.

HOW assign_trainers WORKS (summary):
1. Build a map of which trucks are banned for each trainer, based on ban
   relationships with drivers already placed on those trucks.
2. For each trainer, find trucks at the current MINIMUM trainer count
   (recomputed after every placement to enforce even spread).
3. Happy path: place on a minimum-count, non-banned truck.
4. Fallback: if all minimum-count trucks are banned, place on any non-banned
   truck and emit a warning.
5. Nuclear fallback: if all trucks are banned, assign uniform weight and place
   anyway — dispatch must never deadlock.

WHAT WE'RE VERIFYING:
- Trainers are spread evenly across trucks (the round-robin guarantee).
- A ban with a placed driver blocks that truck for the trainer.
- Being forced off minimum-count trucks produces a warning.
- Having no trainers produces no assignments and no warnings.
- Having one trainer produces exactly one placement.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.services.assign_trainers import assign_trainers

from tests.conftest import (
    make_employee,
    make_truck,
    make_assignment,
    make_member,
    make_relationship,
)


# ---------------------------------------------------------------------------
# Even spread — the core guarantee
# ---------------------------------------------------------------------------

class TestEvenSpread:
    """
    assign_trainers must enforce even distribution by only placing each
    trainer on trucks currently at the minimum trainer count.
    """

    def test_two_trainers_two_trucks_one_each(self, db):
        """
        ARRANGE: 2 trucks, 2 trainers, no bans, no history.
        ACT: assign_trainers.
        ASSERT: each truck ends up with exactly 1 trainer.

        WHY THIS MATTERS:
        Without the minimum-count constraint, random.choices might place both
        trainers on the same truck. The minimum-count gate prevents that.
        Both trucks start at 0. After placing trainer 1 on truck A,
        trainer_counts becomes {A: 1, B: 0}. The minimum is now 0, so only
        truck B is eligible for trainer 2.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="Trainer 1")
        trainer_2 = make_employee(db, role="trainer", name="Trainer 2")

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        warnings = assign_trainers(
            available_trainers=[trainer_1, trainer_2],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        trainers_on_a = [c for c in assigned_crews[truck_a.id] if c["role"] == "trainer"]
        trainers_on_b = [c for c in assigned_crews[truck_b.id] if c["role"] == "trainer"]

        assert len(trainers_on_a) == 1, "Truck A should have exactly 1 trainer"
        assert len(trainers_on_b) == 1, "Truck B should have exactly 1 trainer"
        assert warnings == [], "No bans means no warnings"

    def test_three_trainers_two_trucks_spread(self, db):
        """
        ARRANGE: 2 trucks, 3 trainers.
        ASSERT: total trainer count across trucks is 3, and no truck has more
        than 2 (3+0 is impossible with the minimum-count gate).

        WHY: after placement 1 (A=1,B=0) and placement 2 (A=1,B=1), the
        minimum is 1. Both trucks are now eligible for trainer 3. The result
        will be either A=2,B=1 or A=1,B=2 — never A=3,B=0.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        trainers = [
            make_employee(db, role="trainer", name=f"Trainer {i}")
            for i in range(3)
        ]

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_trainers(
            available_trainers=trainers,
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        total = sum(
            1 for crew in assigned_crews.values()
            for c in crew if c["role"] == "trainer"
        )
        max_on_one_truck = max(
            sum(1 for c in crew if c["role"] == "trainer")
            for crew in assigned_crews.values()
        )

        assert total == 3, "All 3 trainers must be placed"
        assert max_on_one_truck <= 2, (
            "No truck should have 3 trainers when only 3 exist across 2 trucks"
        )

    def test_no_trainers_no_assignments(self, db):
        """
        Edge case: empty trainer list.
        ASSERT: assigned_crews unchanged, warnings is empty list.

        WHY: the for loop never executes. This should be a clean no-op.
        """
        truck_a = make_truck(db, "Truck A")

        assigned_crews = {truck_a.id: []}
        base_weights   = {truck_a.id: 1.0}

        warnings = assign_trainers(
            available_trainers=[],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        total = sum(
            1 for crew in assigned_crews.values()
            for c in crew if c["role"] == "trainer"
        )
        assert total == 0
        assert warnings == []

    def test_one_trainer_one_truck_placed(self, db):
        """
        Simplest case: 1 trainer, 1 truck.
        ASSERT: that trainer is placed on the truck.
        """
        truck_a = make_truck(db, "Truck A")
        trainer = make_employee(db, role="trainer", name="Solo Trainer")

        assigned_crews = {truck_a.id: []}
        base_weights   = {truck_a.id: 1.0}

        assign_trainers(
            available_trainers=[trainer],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        placements = [c for c in assigned_crews[truck_a.id] if c["role"] == "trainer"]
        assert len(placements) == 1
        assert placements[0]["id"] == trainer.id


# ---------------------------------------------------------------------------
# Ban constraints
# ---------------------------------------------------------------------------

class TestBanConstraints:
    """
    A ban between a trainer and a driver already on a truck blocks that truck
    for the trainer. The minimum-count logic still applies — only if ALL
    minimum-count trucks are banned does the fallback path trigger.
    """

    def test_trainer_avoids_banned_truck(self, db):
        """
        ARRANGE:
        - 2 trucks (A and B), each with one driver already placed.
        - trainer bans driver_a (so truck A is off-limits).
        - Only truck B is eligible.
        ASSERT: trainer is placed on truck B, not truck A.

        WHY WE SET UP drivers in assigned_crews:
        assign_trainers builds its ban map by scanning assigned_crews for
        drivers. If no drivers are in assigned_crews, the ban query finds
        nothing and no trucks are marked banned.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver_a = make_employee(db, role="driver", name="Driver A")
        driver_b = make_employee(db, role="driver", name="Driver B")
        trainer  = make_employee(db, role="trainer", name="Trainer")

        # Trainer bans driver_a — truck A is blocked
        make_relationship(db, trainer, driver_a, rel_type="ban")

        assigned_crews = {
            truck_a.id: [{"id": driver_a.id, "role": "driver"}],
            truck_b.id: [{"id": driver_b.id, "role": "driver"}],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_trainers(
            available_trainers=[trainer],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a = [c for c in assigned_crews[truck_a.id] if c["role"] == "trainer"]
        on_b = [c for c in assigned_crews[truck_b.id] if c["role"] == "trainer"]

        assert len(on_a) == 0, "Trainer should not be placed on banned truck A"
        assert len(on_b) == 1, "Trainer should be placed on non-banned truck B"

    def test_driver_ban_on_trainer_also_blocks_truck(self, db):
        """
        Bans are bidirectional in effect — if driver bans trainer OR trainer
        bans driver, that truck is blocked for the trainer.
        ARRANGE: driver_a bans the trainer (not the other way around).
        ASSERT: trainer still avoids truck A.

        WHY: the ban_records query uses OR — it fetches bans where either
        party is the driver. Both directions produce the same blocked truck.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver_a = make_employee(db, role="driver", name="Driver A")
        driver_b = make_employee(db, role="driver", name="Driver B")
        trainer  = make_employee(db, role="trainer", name="Trainer")

        # Driver bans the trainer — truck A should still be blocked
        make_relationship(db, driver_a, trainer, rel_type="ban")

        assigned_crews = {
            truck_a.id: [{"id": driver_a.id, "role": "driver"}],
            truck_b.id: [{"id": driver_b.id, "role": "driver"}],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_trainers(
            available_trainers=[trainer],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a = [c for c in assigned_crews[truck_a.id] if c["role"] == "trainer"]
        assert len(on_a) == 0, "Driver-initiated ban should also block truck A for the trainer"

    def test_no_drivers_means_no_bans(self, db):
        """
        If assigned_crews has no drivers yet, the ban query finds nothing,
        so all trucks are eligible regardless of any ban relationships.
        ASSERT: trainer is placed (on the only truck), no warning.

        WHY THIS MATTERS: dispatch places drivers first, then trainers. But
        if dispatch is run manually or tested in isolation with no drivers,
        the trainer placement must not crash.
        """
        truck_a = make_truck(db, "Truck A")
        trainer = make_employee(db, role="trainer", name="Trainer")

        assigned_crews = {truck_a.id: []}   # no drivers
        base_weights   = {truck_a.id: 1.0}

        warnings = assign_trainers(
            available_trainers=[trainer],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        placements = [c for c in assigned_crews[truck_a.id] if c["role"] == "trainer"]
        assert len(placements) == 1
        assert warnings == []


# ---------------------------------------------------------------------------
# Fallback path — warning emitted
# ---------------------------------------------------------------------------

class TestFallbackWarning:
    """
    When a trainer is banned from ALL minimum-count trucks, the fallback
    path runs: the trainer is placed on an above-minimum truck (if one exists)
    and a warning dict is appended to the warnings list.

    This is the most complex scenario to set up because we need:
    - Only one truck at the minimum (or all minimum trucks banned)
    - A ban that covers all of those minimum trucks
    """

    def test_fallback_emits_warning_when_all_minimum_trucks_banned(self, db):
        """
        ARRANGE:
        - 2 trucks (A=minimum=0 trainers, B=above minimum because we pre-populate it).
          We pre-populate truck B with a trainer so truck A is the ONLY minimum truck.
        - Trainer is banned from truck A (the only minimum truck).
        ASSERT:
        - Trainer is still placed somewhere (dispatch must complete).
        - warnings list has exactly 1 entry containing the trainer's ID.

        HOW WE FORCE TRUCK B ABOVE MINIMUM:
        We manually insert a trainer entry into assigned_crews[truck_b.id]
        before calling assign_trainers. This makes B's count=1 and A's count=0,
        so A is the only minimum-count truck. Since A is banned, fallback triggers.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver_a  = make_employee(db, role="driver",  name="Driver A")
        existing  = make_employee(db, role="trainer", name="Already Placed")
        trainer   = make_employee(db, role="trainer", name="Banned Trainer")

        # Trainer is banned from truck A via driver_a
        make_relationship(db, trainer, driver_a, rel_type="ban")

        assigned_crews = {
            # truck A: driver only, 0 trainers (the minimum)
            truck_a.id: [{"id": driver_a.id, "role": "driver"}],
            # truck B: already has a trainer (above minimum = 1)
            truck_b.id: [{"id": existing.id, "role": "trainer"}],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        warnings = assign_trainers(
            available_trainers=[trainer],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        # Trainer must be placed somewhere
        total_placed = sum(
            1 for crew in assigned_crews.values()
            for c in crew
            if c["role"] == "trainer" and c["id"] == trainer.id
        )
        assert total_placed == 1, "Trainer must be placed even via fallback"

        # Warning must be emitted
        assert len(warnings) == 1, "Exactly one warning should be emitted"
        assert warnings[0]["employee_id"] == trainer.id, (
            "Warning should identify the trainer who triggered fallback"
        )

    def test_no_warning_when_ban_does_not_block_minimum_trucks(self, db):
        """
        A ban that blocks an ABOVE-minimum truck does not trigger a warning.
        The trainer can still reach minimum-count trucks freely.

        ARRANGE:
        - 2 trucks. Truck B is already above minimum (pre-placed trainer).
        - Trainer is banned from truck B (the above-minimum one).
        - Truck A is the only minimum truck and is NOT banned.
        ASSERT: trainer placed on truck A, no warnings.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver_b  = make_employee(db, role="driver",  name="Driver B")
        existing  = make_employee(db, role="trainer", name="Already Placed")
        trainer   = make_employee(db, role="trainer", name="Trainer")

        # Ban blocks truck B (which is above minimum) — should not matter
        make_relationship(db, trainer, driver_b, rel_type="ban")

        assigned_crews = {
            truck_a.id: [],   # minimum — 0 trainers, no driver to create bans
            truck_b.id: [
                {"id": driver_b.id, "role": "driver"},
                {"id": existing.id, "role": "trainer"},
            ],
        }
        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}

        warnings = assign_trainers(
            available_trainers=[trainer],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        on_a = [c for c in assigned_crews[truck_a.id] if c["role"] == "trainer"]
        assert len(on_a) == 1, "Trainer should be placed on truck A (only minimum truck)"
        assert warnings == [], "No warning when minimum trucks are freely accessible"
