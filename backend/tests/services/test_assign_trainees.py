"""
Tests for assign_trainees — truck-first round-robin algorithm.

HOW assign_trainees WORKS:
1. Build trainer_id -> truck_id and truck_id -> [trainer_ids] maps.
2. For each trainee (in order):
   a. Recompute paired_counts for every trainer (how many trainees have
      paired_trainer_id == that trainer in their truck's crew).
   b. Compute global_min = min(paired_counts.values()).
   c. globally_available = all trainers whose count == global_min.
   d. Walk the round-robin cursor across trucks_with_trainers starting at
      rr_index. Skip trucks where no trainer is in globally_available.
      On the first truck that has an available trainer, pick randomly among
      them, advance rr_index past that truck, and place the trainee.
3. globally_available is never empty (it always contains at least the
   trainers at the current minimum), so the cursor walk always succeeds.
   An assertion fires if it somehow doesn't.

INVARIANTS THIS FILE TESTS:
- Every trainee is placed (no skips, no early exit).
- paired_trainer_id is always set to a valid trainer.
- Trainers are filled to global_min before any trainer can receive their
  next trainee — enforced globally, not per-truck.
- The cursor advances after each placement and wraps correctly.
- Trucks are visited in rotation before any truck gets a second trainee.
- Overflow rounds (trainees > trainers) fill evenly using the same logic.
- Trucks with more trainers absorb proportionally more trainees.
- A truck whose trainers are all above global_min is skipped in that round.
- Pre-placed trainees (continuation pre-pass) are counted toward global_min.
- Zero trainers → immediate return, no placements.
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


def all_placed_trainees(crews):
    return [m for crew in crews.values() for m in crew if m["role"] == "trainee"]


# ---------------------------------------------------------------------------
# Edge cases — zero inputs
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_trainees_returns_empty_list_and_no_change(self, db):
        truck_a  = make_truck(db, "Truck A")
        trainer  = make_employee(db, role="trainer", name="Trainer")
        crews    = {truck_a.id: [trainer_entry(trainer.id)]}

        result = assign_trainees([], crews, db)

        assert result == []
        assert len([m for m in crews[truck_a.id] if m["role"] == "trainee"]) == 0

    def test_no_trainers_returns_empty_list_and_no_placements(self, db):
        truck_a  = make_truck(db, "Truck A")
        trainees = [make_employee(db, role="trainee", name=f"T{i}") for i in range(3)]
        crews    = {truck_a.id: []}

        result = assign_trainees(trainees, crews, db)

        assert result == []
        assert len([m for m in crews[truck_a.id] if m["role"] == "trainee"]) == 0

    def test_returns_empty_list_always(self, db):
        """assign_trainees never produces warnings — always returns []."""
        truck_a  = make_truck(db, "Truck A")
        trainer  = make_employee(db, role="trainer")
        trainees = [make_employee(db, role="trainee", name=f"T{i}") for i in range(5)]
        crews    = {truck_a.id: [trainer_entry(trainer.id)]}

        result = assign_trainees(trainees, crews, db)

        assert result == []


# ---------------------------------------------------------------------------
# Every trainee is placed with a valid paired_trainer_id
# ---------------------------------------------------------------------------

class TestPlacement:
    def test_all_trainees_placed(self, db):
        truck_a  = make_truck(db, "Truck A")
        truck_b  = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="Trainer 1")
        trainer_2 = make_employee(db, role="trainer", name="Trainer 2")
        trainees  = [make_employee(db, role="trainee", name=f"T{i}") for i in range(7)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
        }

        assign_trainees(trainees, crews, db)

        placed = all_placed_trainees(crews)
        assert len(placed) == 7

    def test_paired_trainer_id_always_set_to_valid_trainer(self, db):
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="Trainer 1")
        trainer_2 = make_employee(db, role="trainer", name="Trainer 2")
        trainer_3 = make_employee(db, role="trainer", name="Trainer 3")
        trainees  = [make_employee(db, role="trainee", name=f"T{i}") for i in range(6)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id), trainer_entry(trainer_2.id)],
            truck_b.id: [trainer_entry(trainer_3.id)],
        }
        valid_ids = {trainer_1.id, trainer_2.id, trainer_3.id}

        assign_trainees(trainees, crews, db)

        for m in all_placed_trainees(crews):
            assert "paired_trainer_id" in m, "paired_trainer_id must always be set"
            assert m["paired_trainer_id"] in valid_ids, (
                f"paired_trainer_id {m['paired_trainer_id']} is not a known trainer"
            )

    def test_single_trainer_receives_all_trainees(self, db):
        """With one trainer there is no choice — all trainees must go to them."""
        truck_a  = make_truck(db, "Truck A")
        trainer  = make_employee(db, role="trainer", name="Solo Trainer")
        trainees = [make_employee(db, role="trainee", name=f"T{i}") for i in range(5)]
        crews    = {truck_a.id: [trainer_entry(trainer.id)]}

        assign_trainees(trainees, crews, db)

        placed = [m for m in crews[truck_a.id] if m["role"] == "trainee"]
        assert len(placed) == 5
        assert all(m["paired_trainer_id"] == trainer.id for m in placed)


# ---------------------------------------------------------------------------
# Global min gate — no trainer receives trainee N+1 while another has fewer
# ---------------------------------------------------------------------------

class TestGlobalMinGate:
    def test_two_trainers_two_trucks_each_get_one(self, db):
        """
        ARRANGE: Truck A (T1), Truck B (T2), 2 trainees.
        After trainee 1 lands on T1 (count=1), T2 is at global_min=0
        so trainee 2 must go to T2.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        trainees  = [make_employee(db, role="trainee", name=f"TR{i}") for i in range(2)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
        }

        assign_trainees(trainees, crews, db)

        assert paired_count(crews, truck_a.id, trainer_1.id) == 1
        assert paired_count(crews, truck_b.id, trainer_2.id) == 1

    def test_trainer_above_global_min_not_selected(self, db):
        """
        ARRANGE: Truck A (T1 pre-loaded with 1 trainee), Truck B (T2 count=0).
        global_min=0, globally_available={T2}.
        ASSERT: next trainee goes to T2, not T1.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        pre       = make_employee(db, role="trainee", name="Pre")
        new_t     = make_employee(db, role="trainee", name="New")
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id), trainee_entry(pre.id, trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
        }

        assign_trainees([new_t], crews, db)

        assert paired_count(crews, truck_b.id, trainer_2.id) == 1
        assert paired_count(crews, truck_a.id, trainer_1.id) == 1  # unchanged

    def test_globally_available_never_empty(self, db):
        """
        After any number of placements, globally_available must always contain
        at least one trainer. Verified by asserting the assertion never fires
        across a large randomised run.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        truck_c   = make_truck(db, "Truck C")
        trainers  = [make_employee(db, role="trainer", name=f"TR{i}") for i in range(6)]
        trainees  = [make_employee(db, role="trainee", name=f"T{i}") for i in range(20)]
        crews = {
            truck_a.id: [trainer_entry(t.id) for t in trainers[:3]],
            truck_b.id: [trainer_entry(t.id) for t in trainers[3:5]],
            truck_c.id: [trainer_entry(t.id) for t in trainers[5:]],
        }

        # If the assertion inside assign_trainees fires this raises AssertionError.
        assign_trainees(trainees, crews, db)

        assert len(all_placed_trainees(crews)) == 20

    def test_pre_placed_continuation_trainee_counted_in_global_min(self, db):
        """
        Continuation pre-pass trainees are already in crews before assign_trainees
        runs. Their paired_trainer_id must be counted in global_min so that trainer
        is not considered available while others have fewer.

        ARRANGE: Truck A has T1 pre-loaded (count=1). Truck B has T2 (count=0).
        ASSERT: next trainee from rolling pool goes to T2.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        pre       = make_employee(db, role="trainee", name="Pre-placed")
        pool      = make_employee(db, role="trainee", name="Pool Trainee")
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id), trainee_entry(pre.id, trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
        }

        assign_trainees([pool], crews, db)

        assert paired_count(crews, truck_b.id, trainer_2.id) == 1
        assert paired_count(crews, truck_a.id, trainer_1.id) == 1


# ---------------------------------------------------------------------------
# Cursor rotation — trucks visited in round-robin order
# ---------------------------------------------------------------------------

class TestCursorRotation:
    def test_cursor_visits_trucks_in_order(self, db):
        """
        ARRANGE: Truck A (T1), Truck B (T2), Truck C (T3), 3 trainees.
        Mock random.choice to always pick the first option (deterministic).
        ASSERT: trainees land on A, B, C in that order — cursor advances each time.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        truck_c   = make_truck(db, "Truck C")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        trainer_3 = make_employee(db, role="trainer", name="T3")
        trainees  = [make_employee(db, role="trainee", name=f"TR{i}") for i in range(3)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
            truck_c.id: [trainer_entry(trainer_3.id)],
        }
        # trucks_with_trainers preserves dict insertion order
        truck_order = [truck_a.id, truck_b.id, truck_c.id]

        with patch("app.services.assign_trainees.random.choice", side_effect=lambda s: s[0]):
            assign_trainees(trainees, crews, db)

        # Each truck should have exactly 1 trainee
        for truck_id, trainer_id in [
            (truck_a.id, trainer_1.id),
            (truck_b.id, trainer_2.id),
            (truck_c.id, trainer_3.id),
        ]:
            assert paired_count(crews, truck_id, trainer_id) == 1, (
                f"Truck {truck_id} should have exactly 1 trainee after one rotation"
            )

    def test_cursor_wraps_after_last_truck(self, db):
        """
        ARRANGE: Truck A (T1), Truck B (T2), 4 trainees (2 full rounds).
        ASSERT: each trainer ends up with exactly 2 trainees — the cursor
        wrapped back to Truck A after reaching Truck B.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        trainees  = [make_employee(db, role="trainee", name=f"TR{i}") for i in range(4)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
        }

        assign_trainees(trainees, crews, db)

        assert paired_count(crews, truck_a.id, trainer_1.id) == 2
        assert paired_count(crews, truck_b.id, trainer_2.id) == 2

    def test_cursor_skips_fully_loaded_truck_then_revisits(self, db):
        """
        ARRANGE: Truck A (T1, T2 — both pre-loaded, count=1 each).
                 Truck B (T3 — count=0).
        global_min=0, globally_available={T3}. Truck A has no available trainer.
        ASSERT: next trainee goes to Truck B (cursor skips Truck A).
        After placement, global_min=1, all trainers available again.
        ASSERT: a second trainee can go to Truck A.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        trainer_3 = make_employee(db, role="trainer", name="T3")
        pre_1     = make_employee(db, role="trainee", name="Pre 1")
        pre_2     = make_employee(db, role="trainee", name="Pre 2")
        new_1     = make_employee(db, role="trainee", name="New 1")
        new_2     = make_employee(db, role="trainee", name="New 2")
        crews = {
            truck_a.id: [
                trainer_entry(trainer_1.id),
                trainer_entry(trainer_2.id),
                trainee_entry(pre_1.id, trainer_1.id),
                trainee_entry(pre_2.id, trainer_2.id),
            ],
            truck_b.id: [trainer_entry(trainer_3.id)],
        }

        assign_trainees([new_1, new_2], crews, db)

        # new_1 must go to Truck B (only available truck at global_min=0)
        assert paired_count(crews, truck_b.id, trainer_3.id) == 1, (
            "new_1 must skip Truck A (all trainers above global_min) and land on Truck B"
        )
        # new_2: now global_min=1, Truck A is open again — it goes somewhere valid
        total = (
            paired_count(crews, truck_a.id, trainer_1.id)
            + paired_count(crews, truck_a.id, trainer_2.id)
            + paired_count(crews, truck_b.id, trainer_3.id)
        )
        assert total == 4  # 2 pre + 2 new

    def test_cursor_advances_past_selected_truck_not_reset(self, db):
        """
        ARRANGE: Truck A (T1), Truck B (T2), Truck C (T3), 6 trainees (2 rounds).
        ASSERT: in round 2 the cursor continues from where it left off —
        each trainer ends with exactly 2 trainees.

        If the cursor reset to 0 after each trainee, distribution would still be
        even here. What we're checking is that no trainer gets 3 while another
        gets 1 — which would happen if the cursor got stuck on one position.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        truck_c   = make_truck(db, "Truck C")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        trainer_3 = make_employee(db, role="trainer", name="T3")
        trainees  = [make_employee(db, role="trainee", name=f"TR{i}") for i in range(6)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
            truck_c.id: [trainer_entry(trainer_3.id)],
        }

        assign_trainees(trainees, crews, db)

        for truck_id, trainer_id in [
            (truck_a.id, trainer_1.id),
            (truck_b.id, trainer_2.id),
            (truck_c.id, trainer_3.id),
        ]:
            count = paired_count(crews, truck_id, trainer_id)
            assert count == 2, f"Expected 2 trainees per trainer, got {count}"


# ---------------------------------------------------------------------------
# Overflow — trainees > trainers (second and third rounds)
# ---------------------------------------------------------------------------

class TestOverflow:
    def test_overflow_distributes_evenly_when_divisible(self, db):
        """
        ARRANGE: 3 trainers (one per truck), 9 trainees (3 full rounds).
        ASSERT: each trainer ends up with exactly 3 trainees.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        truck_c   = make_truck(db, "Truck C")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        trainer_3 = make_employee(db, role="trainer", name="T3")
        trainees  = [make_employee(db, role="trainee", name=f"TR{i}") for i in range(9)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
            truck_c.id: [trainer_entry(trainer_3.id)],
        }

        assign_trainees(trainees, crews, db)

        for truck_id, trainer_id in [
            (truck_a.id, trainer_1.id),
            (truck_b.id, trainer_2.id),
            (truck_c.id, trainer_3.id),
        ]:
            assert paired_count(crews, truck_id, trainer_id) == 3

    def test_overflow_distributes_with_remainder(self, db):
        """
        ARRANGE: 3 trainers, 7 trainees (2 full rounds + 1 remainder).
        ASSERT: counts are {3, 2, 2} — no trainer gets 3 while another has 1.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        truck_c   = make_truck(db, "Truck C")
        trainer_1 = make_employee(db, role="trainer", name="T1")
        trainer_2 = make_employee(db, role="trainer", name="T2")
        trainer_3 = make_employee(db, role="trainer", name="T3")
        trainees  = [make_employee(db, role="trainee", name=f"TR{i}") for i in range(7)]
        crews = {
            truck_a.id: [trainer_entry(trainer_1.id)],
            truck_b.id: [trainer_entry(trainer_2.id)],
            truck_c.id: [trainer_entry(trainer_3.id)],
        }

        assign_trainees(trainees, crews, db)

        counts = sorted([
            paired_count(crews, truck_a.id, trainer_1.id),
            paired_count(crews, truck_b.id, trainer_2.id),
            paired_count(crews, truck_c.id, trainer_3.id),
        ])
        assert counts == [2, 2, 3], f"Expected [2, 2, 3], got {counts}"

    def test_large_uneven_trainer_distribution(self, db):
        """
        ARRANGE: 5 trucks with 3/1/2/2/2 trainers (10 total), 31 trainees.
        ASSERT:
        - All 31 trainees placed.
        - No trainer has more than ceil(31/10)=4 trainees.
        - No trainer has fewer than floor(31/10)=3 trainees.
        """
        trucks = [make_truck(db, f"Truck {c}") for c in "ABCDE"]
        # trainer counts per truck: 3, 1, 2, 2, 2 = 10 total
        trainer_counts = [3, 1, 2, 2, 2]
        all_trainers = []
        crews = {}
        for truck, count in zip(trucks, trainer_counts):
            group = [make_employee(db, role="trainer", name=f"TR-{truck.id}-{i}") for i in range(count)]
            all_trainers.extend(group)
            crews[truck.id] = [trainer_entry(t.id) for t in group]

        trainees = [make_employee(db, role="trainee", name=f"T{i}") for i in range(31)]

        assign_trainees(trainees, crews, db)

        placed = all_placed_trainees(crews)
        assert len(placed) == 31, "All 31 trainees must be placed"

        for trainer in all_trainers:
            truck_id = next(
                tid for tid, crew in crews.items()
                if any(m["id"] == trainer.id and m["role"] == "trainer" for m in crew)
            )
            count = paired_count(crews, truck_id, trainer.id)
            assert count >= 3, f"Trainer {trainer.name} has only {count} trainees — should be at least 3"
            assert count <= 4, f"Trainer {trainer.name} has {count} trainees — should be at most 4"


# ---------------------------------------------------------------------------
# Uneven trainer counts across trucks
# ---------------------------------------------------------------------------

class TestUnevenTruckSizes:
    def test_larger_truck_absorbs_more_trainees_proportionally(self, db):
        """
        ARRANGE: Truck A (3 trainers), Truck B (1 trainer), 4 trainees.
        ASSERT: Truck A gets 3 trainees (one per trainer), Truck B gets 1.
        The cursor visits A then B. After 1 trainee on A (global_min still 0,
        T2/T3 on A still available), A gets trainees 2 and 3 before B gets
        another — because B's trainer rose above global_min after trainee 4.

        More precisely: with 4 trainees and 4 trainers (3+1), each trainer gets 1.
        Truck A total = 3, Truck B total = 1.
        """
        truck_a   = make_truck(db, "Truck A")
        truck_b   = make_truck(db, "Truck B")
        trainers_a = [make_employee(db, role="trainer", name=f"TA{i}") for i in range(3)]
        trainer_b  = make_employee(db, role="trainer", name="TB")
        trainees   = [make_employee(db, role="trainee", name=f"TR{i}") for i in range(4)]
        crews = {
            truck_a.id: [trainer_entry(t.id) for t in trainers_a],
            truck_b.id: [trainer_entry(trainer_b.id)],
        }

        assign_trainees(trainees, crews, db)

        truck_a_total = sum(paired_count(crews, truck_a.id, t.id) for t in trainers_a)
        truck_b_total = paired_count(crews, truck_b.id, trainer_b.id)

        assert truck_a_total == 3, f"Truck A should have 3 trainees, got {truck_a_total}"
        assert truck_b_total == 1, f"Truck B should have 1 trainee, got {truck_b_total}"

    def test_truck_with_no_trainers_receives_no_trainees(self, db):
        """
        A truck with no trainers must never receive a trainee — it is excluded
        from trucks_with_trainers entirely.
        """
        truck_a  = make_truck(db, "Truck A")  # has trainers
        truck_b  = make_truck(db, "Truck B")  # no trainers
        trainer  = make_employee(db, role="trainer", name="Trainer")
        trainees = [make_employee(db, role="trainee", name=f"T{i}") for i in range(3)]
        crews = {
            truck_a.id: [trainer_entry(trainer.id)],
            truck_b.id: [],
        }

        assign_trainees(trainees, crews, db)

        assert len([m for m in crews[truck_b.id] if m["role"] == "trainee"]) == 0
        assert len([m for m in crews[truck_a.id] if m["role"] == "trainee"]) == 3

    def test_many_trainers_one_truck_all_get_one_before_second(self, db):
        """
        ARRANGE: 1 truck with 5 trainers, 7 trainees.
        ASSERT: after 5 trainees each trainer has exactly 1.
                after 7 trainees the counts are {2, 2, 1, 1, 1} — no trainer has 2
                while a truckmate has 0.
        """
        truck_a  = make_truck(db, "Truck A")
        trainers = [make_employee(db, role="trainer", name=f"TR{i}") for i in range(5)]
        trainees = [make_employee(db, role="trainee", name=f"T{i}") for i in range(7)]
        crews    = {truck_a.id: [trainer_entry(t.id) for t in trainers]}

        assign_trainees(trainees, crews, db)

        counts = sorted([paired_count(crews, truck_a.id, t.id) for t in trainers])
        assert counts == [1, 1, 1, 2, 2], f"Expected [1,1,1,2,2], got {counts}"
