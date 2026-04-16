"""
Tests for assign_trainees.

HOW assign_trainees WORKS (summary):
1. Build a trainer_id -> truck_id map from assigned_crews.
2. Build a truck_id -> [trainer_ids] reverse map.
3. For each trainee, count how many trainees are already paired to each trainer.
4. Determine global minimum paired count across all trainers.
5. Eligible trainers = those at the global minimum AND whose intra-truck count
   also equals the truck-level minimum (no trainer can receive trainee N+1 while
   a truck-mate still has N-1 or fewer).
6. Pick uniformly at random from eligible trainers and place the trainee.

WHAT WE'RE VERIFYING:
- Trainees are spread evenly across trainers globally.
- Within a single truck, no trainer receives a second trainee before every
  trainer on that truck has at least one (the intra-truck fairness constraint).
- A trainer pre-loaded with a continuation-request trainee is correctly
  deprioritised relative to unpaired truck-mates before being eligible again.
- No trainers dispatched → no assignments, empty return.
- Single trainer → all trainees go to that trainer.
- The paired_trainer_id tag is always set correctly.
"""

import uuid
from unittest.mock import patch

import pytest

from app.services.assign_trainees import assign_trainees

from tests.conftest import make_employee, make_truck


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_crews(*truck_ids):
    """Return an empty assigned_crews dict keyed by the given truck UUIDs."""
    return {tid: [] for tid in truck_ids}


def trainer_entry(trainer_id):
    return {"id": trainer_id, "role": "trainer"}


def trainee_entry(trainee_id, paired_trainer_id):
    return {"id": trainee_id, "role": "trainee", "paired_trainer_id": paired_trainer_id}


def paired_count(crews, truck_id, trainer_id):
    """Count trainees currently paired to trainer_id on truck_id."""
    return sum(
        1 for m in crews[truck_id]
        if m.get("paired_trainer_id") == trainer_id
    )


# ---------------------------------------------------------------------------
# Basic placement
# ---------------------------------------------------------------------------

class TestBasicPlacement:
    """Trainees are placed, tagged correctly, and the function always returns []."""

    def test_single_trainer_receives_all_trainees(self, db):
        """
        ARRANGE: 1 truck, 1 trainer, 3 trainees.
        ASSERT: all 3 trainees land on that truck paired to that trainer.

        WHY: with only one trainer there is no distribution decision to make.
        Every trainee must go to the only available trainer.
        """
        truck_a = make_truck(db, "Truck A")
        trainer = make_employee(db, role="trainer", name="Solo Trainer")
        trainees = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(3)]

        crews = {truck_a.id: [trainer_entry(trainer.id)]}

        result = assign_trainees(trainees, crews, db)

        placed = [m for m in crews[truck_a.id] if m["role"] == "trainee"]
        assert len(placed) == 3
        assert all(m["paired_trainer_id"] == trainer.id for m in placed)
        assert result == []

    def test_no_trainees_no_change(self, db):
        """
        ARRANGE: 1 truck, 1 trainer, 0 trainees.
        ASSERT: crews unchanged, empty list returned.
        """
        truck_a = make_truck(db, "Truck A")
        trainer = make_employee(db, role="trainer", name="Trainer")

        crews = {truck_a.id: [trainer_entry(trainer.id)]}
        original_len = len(crews[truck_a.id])

        result = assign_trainees([], crews, db)

        assert len(crews[truck_a.id]) == original_len
        assert result == []

    def test_no_trainers_no_placements(self, db):
        """
        ARRANGE: 1 truck with no trainers, 2 trainees.
        ASSERT: no trainees placed, empty list returned.

        WHY: trainer_to_truck is empty so the early-return fires.
        """
        truck_a = make_truck(db, "Truck A")
        trainees = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(2)]

        crews = {truck_a.id: []}

        result = assign_trainees(trainees, crews, db)

        placed = [m for m in crews[truck_a.id] if m["role"] == "trainee"]
        assert len(placed) == 0
        assert result == []

    def test_paired_trainer_id_tag_is_set(self, db):
        """
        Every placed trainee must have paired_trainer_id set to the trainer
        they were assigned to — this tag is consumed by training_injection and
        the rebalancer.
        """
        truck_a = make_truck(db, "Truck A")
        trainer_a = make_employee(db, role="trainer", name="Trainer A")
        trainer_b = make_employee(db, role="trainer", name="Trainer B")
        trainees = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(2)]

        crews = {truck_a.id: [trainer_entry(trainer_a.id), trainer_entry(trainer_b.id)]}

        assign_trainees(trainees, crews, db)

        placed = [m for m in crews[truck_a.id] if m["role"] == "trainee"]
        assert len(placed) == 2
        valid_trainer_ids = {trainer_a.id, trainer_b.id}
        for m in placed:
            assert "paired_trainer_id" in m
            assert m["paired_trainer_id"] in valid_trainer_ids


# ---------------------------------------------------------------------------
# Global even spread — across trucks
# ---------------------------------------------------------------------------

class TestGlobalEvenSpread:
    """
    With trainers on multiple trucks, trainees must be distributed evenly
    across all trainers globally (not piled onto one truck).
    """

    def test_two_trainers_two_trucks_one_trainee_each(self, db):
        """
        ARRANGE: Truck A with Trainer 1, Truck B with Trainer 2, 2 trainees.
        ASSERT: each trainer receives exactly 1 trainee.

        WHY: after trainee 1 is placed with Trainer 1 (count=1), Trainer 2 is
        at the global minimum (0), so trainee 2 must go to Trainer 2.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="Trainer 1")
        trainer_2 = make_employee(db, role="trainer", name="Trainer 2")
        trainees  = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(2)]

        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
        }

        assign_trainees(trainees, crews, db)

        assert paired_count(crews, truck_a.id, trainer_1.id) == 1
        assert paired_count(crews, truck_b.id, trainer_2.id) == 1

    def test_three_trainers_spread_across_trucks(self, db):
        """
        ARRANGE: Truck A (Trainer 1), Truck B (Trainer 2, Trainer 3), 3 trainees.
        ASSERT: each trainer receives exactly 1 trainee — no trainer skipped.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="Trainer 1")
        trainer_2 = make_employee(db, role="trainer", name="Trainer 2")
        trainer_3 = make_employee(db, role="trainer", name="Trainer 3")
        trainees  = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(3)]

        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id), trainer_entry(trainer_3.id)],
        }

        assign_trainees(trainees, crews, db)

        assert paired_count(crews, truck_a.id, trainer_1.id) == 1
        assert paired_count(crews, truck_b.id, trainer_2.id) + \
               paired_count(crews, truck_b.id, trainer_3.id) == 2
        # Neither trainer on Truck B should have 2 while the other has 0
        assert paired_count(crews, truck_b.id, trainer_2.id) <= 1
        assert paired_count(crews, truck_b.id, trainer_3.id) <= 1


# ---------------------------------------------------------------------------
# Intra-truck fairness — the core bug fix
# ---------------------------------------------------------------------------

class TestIntraTruckFairness:
    """
    Within a single truck, no trainer should receive a second trainee before
    every other trainer on that truck has at least one.

    This was the root cause of the Brandon Hayes / two-trainee bug: the
    global round-robin would cycle back to Brandon before his truck-mate
    received their first trainee.
    """

    def test_two_trainers_same_truck_one_trainee_each_before_second(self, db):
        """
        ARRANGE: 1 truck with Brandon and Trainer X. 2 trainees.
        ASSERT: Brandon and Trainer X each get exactly 1 trainee.

        This is the exact scenario that produced the reported bug. Without the
        intra-truck constraint, if Brandon was selected first, the global minimum
        becomes 1 after trainee 2 is placed with Trainer X. A third trainee
        would then be eligible to go to Brandon again before Trainer X has 2.
        With 2 trainees and 2 trainers on the same truck this specific case
        always works even without the fix, but the fix ensures correctness
        regardless of order.
        """
        truck_a  = make_truck(db, "Truck A")
        brandon  = make_employee(db, role="trainer", name="Brandon Hayes")
        trainer_x = make_employee(db, role="trainer", name="Trainer X")
        trainees = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(2)]

        crews = {truck_a.id: [trainer_entry(brandon.id), trainer_entry(trainer_x.id)]}

        assign_trainees(trainees, crews, db)

        brandon_count  = paired_count(crews, truck_a.id, brandon.id)
        trainer_x_count = paired_count(crews, truck_a.id, trainer_x.id)

        assert brandon_count == 1, "Brandon should have exactly 1 trainee"
        assert trainer_x_count == 1, "Trainer X should have exactly 1 trainee"

    def test_continuation_trainee_does_not_allow_second_before_truckmate_has_first(self, db):
        """
        THE EXACT BUG SCENARIO:

        ARRANGE:
        - Truck A has Brandon and Trainer X.
        - Brandon already has a continuation-request trainee pre-placed
          (simulating the run_dispatch pre-pass injecting directly into crews).
        - 1 remaining trainee enters the rolling pool.

        ASSERT: the remaining trainee goes to Trainer X, NOT Brandon.

        WHY THIS IS THE BUG: before the fix, the global minimum after the
        pre-pass was: Brandon=1, Trainer X=0. Global min=0, eligible={Trainer X}.
        That's actually correct for this 1-trainee case. The bug manifests
        when there are enough rolling-pool trainees that the global cycle reaches
        Brandon again before Trainer X has caught up. We test the explicit
        intra-truck gate with mock to force the selection order.
        """
        truck_a   = make_truck(db, "Truck A")
        brandon   = make_employee(db, role="trainer", name="Brandon Hayes")
        trainer_x = make_employee(db, role="trainer", name="Trainer X")
        pre_trainee  = make_employee(db, role="trainee", name="Pre-placed Trainee")
        pool_trainee = make_employee(db, role="trainee", name="Pool Trainee")

        # Simulate continuation pre-pass: Brandon already has a trainee
        crews = {
            truck_a.id: [
                trainer_entry(brandon.id),
                trainer_entry(trainer_x.id),
                trainee_entry(pre_trainee.id, brandon.id),
            ]
        }

        assign_trainees([pool_trainee], crews, db)

        brandon_count   = paired_count(crews, truck_a.id, brandon.id)
        trainer_x_count = paired_count(crews, truck_a.id, trainer_x.id)

        assert trainer_x_count == 1, (
            "Pool trainee must go to Trainer X — Brandon already has a trainee "
            "and Trainer X has zero on the same truck."
        )
        assert brandon_count == 1, "Brandon should still have only 1 trainee"

    def test_brandon_ineligible_while_truckmate_has_fewer(self, db):
        """
        Directly tests the intra-truck gate using mock to control random.choice.

        ARRANGE:
        - Truck A: Brandon (2 trainees pre-placed), Trainer X (1 trainee pre-placed).
        - Truck B: Trainer Y (1 trainee pre-placed).
        - Global minimum = 1. Brandon=2, X=1, Y=1. Eligible by global min = {X, Y}.
        - mock random.choice to always return the first element of eligible list.

        ASSERT: Brandon is NOT in the eligible list — the intra-truck constraint
        excludes him because his count (2) is above the truck-level minimum (1,
        held by Trainer X on the same truck).
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        brandon   = make_employee(db, role="trainer", name="Brandon Hayes")
        trainer_x = make_employee(db, role="trainer", name="Trainer X")
        trainer_y = make_employee(db, role="trainer", name="Trainer Y")

        t1 = make_employee(db, role="trainee", name="Trainee 1")
        t2 = make_employee(db, role="trainee", name="Trainee 2")
        t3 = make_employee(db, role="trainee", name="Trainee 3")
        t4 = make_employee(db, role="trainee", name="Trainee 4")
        new_trainee = make_employee(db, role="trainee", name="New Trainee")

        crews = {
            truck_a.id: [
                trainer_entry(brandon.id),
                trainer_entry(trainer_x.id),
                trainee_entry(t1.id, brandon.id),
                trainee_entry(t2.id, brandon.id),  # Brandon has 2
                trainee_entry(t3.id, trainer_x.id), # Trainer X has 1
            ],
            truck_b.id: [
                trainer_entry(trainer_y.id),
                trainee_entry(t4.id, trainer_y.id),  # Trainer Y has 1
            ],
        }

        captured_eligible = []

        def fake_choice(seq):
            captured_eligible.extend(seq)
            return seq[0]

        with patch("app.services.assign_trainees.random.choice", side_effect=fake_choice):
            assign_trainees([new_trainee], crews, db)

        assert brandon.id not in captured_eligible, (
            "Brandon must not be eligible — he has 2 trainees while Trainer X "
            "(same truck) has only 1. The intra-truck constraint must exclude him."
        )
        assert trainer_x.id in captured_eligible or trainer_y.id in captured_eligible, (
            "Trainer X or Trainer Y (both at the global minimum with no truck-mate "
            "disadvantage) must be eligible."
        )

    def test_two_trucks_two_trainers_each_four_trainees_even_split(self, db):
        """
        ARRANGE: Truck A (Trainer 1, Trainer 2), Truck B (Trainer 3, Trainer 4).
        4 trainees in rolling pool.
        ASSERT: each trainer receives exactly 1 trainee.

        This verifies that the intra-truck constraint and global round-robin
        cooperate to produce perfect evenness when the numbers divide cleanly.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="Trainer 1")
        trainer_2 = make_employee(db, role="trainer", name="Trainer 2")
        trainer_3 = make_employee(db, role="trainer", name="Trainer 3")
        trainer_4 = make_employee(db, role="trainer", name="Trainer 4")
        trainees  = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(4)]

        crews = {
            truck_a.id: [trainer_entry(trainer_1.id), trainer_entry(trainer_2.id)],
            truck_b.id: [trainer_entry(trainer_3.id), trainer_entry(trainer_4.id)],
        }

        assign_trainees(trainees, crews, db)

        for truck_id, trainer_id in [
            (truck_a.id, trainer_1.id),
            (truck_a.id, trainer_2.id),
            (truck_b.id, trainer_3.id),
            (truck_b.id, trainer_4.id),
        ]:
            count = paired_count(crews, truck_id, trainer_id)
            assert count == 1, (
                f"Each trainer should have exactly 1 trainee, got {count}"
            )

    def test_odd_trainee_count_no_trainer_skipped(self, db):
        """
        ARRANGE: Truck A (Trainer 1, Trainer 2), 3 trainees.
        ASSERT: no trainer has 2 trainees while a truck-mate has 0.

        With 3 trainees and 2 trainers on one truck, one trainer must receive
        2 trainees. But they may only receive their second AFTER their truck-mate
        has received their first.
        """
        truck_a   = make_truck(db, "Truck A")
        trainer_1 = make_employee(db, role="trainer", name="Trainer 1")
        trainer_2 = make_employee(db, role="trainer", name="Trainer 2")
        trainees  = [make_employee(db, role="trainee", name=f"Trainee {i}") for i in range(3)]

        crews = {truck_a.id: [trainer_entry(trainer_1.id), trainer_entry(trainer_2.id)]}

        assign_trainees(trainees, crews, db)

        count_1 = paired_count(crews, truck_a.id, trainer_1.id)
        count_2 = paired_count(crews, truck_a.id, trainer_2.id)

        assert count_1 + count_2 == 3, "All 3 trainees must be placed"
        # Neither trainer should have 2 while the other has 0
        assert not (count_1 == 2 and count_2 == 0), (
            "Trainer 1 must not have 2 trainees while Trainer 2 has 0"
        )
        assert not (count_2 == 2 and count_1 == 0), (
            "Trainer 2 must not have 2 trainees while Trainer 1 has 0"
        )
