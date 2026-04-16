"""
Tests for calculate_weights and assign_drivers.

WHAT WE'RE TESTING:
calculate_weights() takes a candidate employee and returns a dict of
{truck_id: weight} — higher weight = more likely to be placed on that truck.
We verify that:
  - Banned trucks get zeroed out (hard exclusion)
  - Consecutive assignment penalty reduces (not eliminates) a truck's weight
  - A fan on a truck boosts that truck's weight
  - Bidirectional fav gives an additional bonus on top of the role boost
  - Base weights are never mutated (caller's dict stays unchanged)

assign_drivers() consumes a list of drivers and fills assigned_crews in place.
We verify that:
  - Exactly one driver ends up on each truck
  - No driver is double-assigned
  - A driver is removed from the pool after being assigned
  - Consecutive penalty is applied (weight = 0.05 for that truck)
"""

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.services.calculate_weights import calculate_weights
from app.services.assign_drivers import assign_drivers
from app.services.constants import ROLE_BOOST, MUTUAL_BONUS

from tests.conftest import make_employee, make_truck, make_assignment, make_member, make_relationship


# ---------------------------------------------------------------------------
# calculate_weights — banned trucks
# ---------------------------------------------------------------------------

class TestBannedTrucks:
    """
    A banned truck must have weight == 0 regardless of fans or history.
    This is the hardest constraint in the weight system.
    """

    def test_banned_truck_zeroed(self, db):
        """
        ARRANGE: two trucks, candidate is banned from truck_b.
        ACT: calculate_weights with truck_b in banned_truck_ids.
        ASSERT: truck_b weight is 0; truck_a weight is untouched.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        candidate = make_employee(db, role="driver")

        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}
        assigned_crews = {truck_a.id: [], truck_b.id: []}

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="driver",
            base_weights=base_weights,
            assigned_crews=assigned_crews,
            banned_truck_ids=[truck_b.id],
            db=db,
        )

        assert result[truck_b.id] == 0, "Banned truck must be zeroed out"
        assert result[truck_a.id] > 0, "Non-banned truck must retain positive weight"

    def test_all_trucks_banned_returns_all_zeros(self, db):
        """
        Edge case: if all trucks are banned, all weights are 0.
        (The caller handles this by falling back to uniform weights.)
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        candidate = make_employee(db, role="driver")

        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}
        assigned_crews = {truck_a.id: [], truck_b.id: []}

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="driver",
            base_weights=base_weights,
            assigned_crews=assigned_crews,
            banned_truck_ids=[truck_a.id, truck_b.id],
            db=db,
        )

        assert result[truck_a.id] == 0
        assert result[truck_b.id] == 0


# ---------------------------------------------------------------------------
# calculate_weights — consecutive penalty
# ---------------------------------------------------------------------------

class TestConsecutivePenalty:
    """
    When an employee was on truck X in their last dispatch, truck X's weight
    is multiplied by 0.05 — dramatically reducing (but not zeroing) it.
    """

    def test_consecutive_truck_penalized(self, db):
        """
        ARRANGE: candidate was assigned to truck_a yesterday.
        ACT: calculate_weights with no bans.
        ASSERT: truck_a weight < truck_b weight (penalty applied).
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        candidate = make_employee(db, role="driver")

        # Create a past assignment — candidate was on truck_a yesterday
        yesterday = date.today() - timedelta(days=1)
        assignment = make_assignment(db, truck_a, yesterday)
        make_member(db, assignment, candidate, role="driver")

        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}
        assigned_crews = {truck_a.id: [], truck_b.id: []}

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="driver",
            base_weights=base_weights,
            assigned_crews=assigned_crews,
            banned_truck_ids=[],
            db=db,
        )

        assert result[truck_a.id] < result[truck_b.id], (
            "Consecutive truck should have lower weight than a fresh truck"
        )
        assert result[truck_a.id] == pytest.approx(0.05), (
            "Consecutive penalty should reduce weight to 5% of base"
        )
        assert result[truck_b.id] == pytest.approx(1.0), (
            "Non-consecutive truck should keep base weight"
        )

    def test_no_history_no_penalty(self, db):
        """
        A brand-new employee with no assignment history should not be penalized
        on any truck.
        """
        truck_a = make_truck(db, "Truck A")
        candidate = make_employee(db, role="driver")

        base_weights = {truck_a.id: 1.0}
        assigned_crews = {truck_a.id: []}

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="driver",
            base_weights=base_weights,
            assigned_crews=assigned_crews,
            banned_truck_ids=[],
            db=db,
        )

        assert result[truck_a.id] == pytest.approx(1.0), (
            "No history means no consecutive penalty"
        )


# ---------------------------------------------------------------------------
# calculate_weights — fan boost
# ---------------------------------------------------------------------------

class TestFanBoost:
    """
    When an already-placed crew member (fan) has the candidate in their fav
    list, that truck gets a boost of ROLE_BOOST[fan_role] * base_weight.
    """

    def test_driver_fan_boosts_truck(self, db):
        """
        ARRANGE: a driver is already on truck_a and has fav'd the candidate walker.
        ACT: calculate_weights for the candidate.
        ASSERT: truck_a weight > truck_b weight by exactly the driver boost amount.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver = make_employee(db, role="driver", name="Driver Fan")
        candidate = make_employee(db, role="walker", name="Walker Candidate")

        # Driver fav'd the candidate
        make_relationship(db, driver, candidate, rel_type="fav")

        base_weights = {truck_a.id: 1.0, truck_b.id: 1.0}
        # Driver is already on truck_a
        assigned_crews = {
            truck_a.id: [{"id": driver.id, "role": "driver"}],
            truck_b.id: [],
        }

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="walker",
            base_weights=base_weights,
            assigned_crews=assigned_crews,
            banned_truck_ids=[],
            db=db,
        )

        expected_boost = 1.0 * ROLE_BOOST["driver"]   # base * 0.70
        assert result[truck_a.id] == pytest.approx(1.0 + expected_boost), (
            "Driver fan should boost truck_a by ROLE_BOOST['driver'] * base_weight"
        )
        assert result[truck_b.id] == pytest.approx(1.0), (
            "Truck with no fans should keep base weight"
        )

    def test_trainer_fan_boost_is_smaller_than_driver(self, db):
        """
        ROLE_BOOST constants: driver=0.70, trainer=0.50, walker=0.30.
        A trainer fan should produce a smaller boost than a driver fan.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        trainer = make_employee(db, role="trainer", name="Trainer Fan")
        candidate = make_employee(db, role="walker", name="Walker")

        make_relationship(db, trainer, candidate, rel_type="fav")

        base = {truck_a.id: 1.0, truck_b.id: 1.0}
        crews = {
            truck_a.id: [{"id": trainer.id, "role": "trainer"}],
            truck_b.id: [],
        }

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="walker",
            base_weights=base,
            assigned_crews=crews,
            banned_truck_ids=[],
            db=db,
        )

        trainer_boost = 1.0 + ROLE_BOOST["trainer"]   # 1.5
        driver_boost  = 1.0 + ROLE_BOOST["driver"]    # 1.7
        assert result[truck_a.id] == pytest.approx(trainer_boost)
        assert result[truck_a.id] < driver_boost, (
            "Trainer fan boost must be less than driver fan boost"
        )

    def test_fan_on_banned_truck_has_no_effect(self, db):
        """
        A fan on a banned truck cannot pull the candidate there.
        The truck stays at weight 0.
        """
        truck_a = make_truck(db, "Truck A")
        driver = make_employee(db, role="driver", name="Fan Driver")
        candidate = make_employee(db, role="walker", name="Walker")

        make_relationship(db, driver, candidate, rel_type="fav")

        base = {truck_a.id: 1.0}
        crews = {truck_a.id: [{"id": driver.id, "role": "driver"}]}

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="walker",
            base_weights=base,
            assigned_crews=crews,
            banned_truck_ids=[truck_a.id],   # banned despite the fan
            db=db,
        )

        assert result[truck_a.id] == 0, (
            "A fan on a banned truck must not override the ban"
        )


# ---------------------------------------------------------------------------
# calculate_weights — bidirectional bonus
# ---------------------------------------------------------------------------

class TestBidirectionalBonus:
    """
    When the candidate AND the fan mutually fav each other, a MUTUAL_BONUS
    of 0.10 is added on top of the role boost.
    """

    def test_bidirectional_bonus_applied(self, db):
        """
        ARRANGE: driver fav's candidate AND candidate fav's driver (mutual).
        ASSERT: weight = base + role_boost + bidirectional_bonus.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver = make_employee(db, role="driver", name="Driver")
        candidate = make_employee(db, role="driver", name="Candidate Driver")

        # Mutual fav
        make_relationship(db, driver, candidate, rel_type="fav")
        make_relationship(db, candidate, driver, rel_type="fav")

        base = {truck_a.id: 1.0, truck_b.id: 1.0}
        crews = {
            truck_a.id: [{"id": driver.id, "role": "driver"}],
            truck_b.id: [],
        }

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="driver",
            base_weights=base,
            assigned_crews=crews,
            banned_truck_ids=[],
            db=db,
        )

        expected = 1.0 + ROLE_BOOST["driver"] + MUTUAL_BONUS["bidirectional"]
        assert result[truck_a.id] == pytest.approx(expected), (
            "Mutual fav should add role boost + bidirectional bonus"
        )

    def test_one_sided_fav_no_bidirectional_bonus(self, db):
        """
        Only the fan fav'd the candidate — no mutual fav — so only the
        role boost applies. No bidirectional bonus.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver = make_employee(db, role="driver", name="Driver")
        candidate = make_employee(db, role="driver", name="Candidate")

        # Only one direction
        make_relationship(db, driver, candidate, rel_type="fav")
        # candidate did NOT fav driver back

        base = {truck_a.id: 1.0, truck_b.id: 1.0}
        crews = {
            truck_a.id: [{"id": driver.id, "role": "driver"}],
            truck_b.id: [],
        }

        result = calculate_weights(
            employee_id=candidate.id,
            employee_role="driver",
            base_weights=base,
            assigned_crews=crews,
            banned_truck_ids=[],
            db=db,
        )

        expected_with_bonus    = 1.0 + ROLE_BOOST["driver"] + MUTUAL_BONUS["bidirectional"]
        expected_without_bonus = 1.0 + ROLE_BOOST["driver"]

        assert result[truck_a.id] == pytest.approx(expected_without_bonus), (
            "One-sided fav should only apply role boost, not bidirectional bonus"
        )
        assert result[truck_a.id] < expected_with_bonus


# ---------------------------------------------------------------------------
# calculate_weights — base_weights immutability
# ---------------------------------------------------------------------------

class TestBaseWeightsImmutability:
    """
    calculate_weights must never modify the caller's base_weights dict.
    The service operates on an internal copy.
    """

    def test_base_weights_not_mutated(self, db):
        truck_a = make_truck(db, "Truck A")
        driver = make_employee(db, role="driver", name="Fan")
        candidate = make_employee(db, role="driver", name="Candidate")
        make_relationship(db, driver, candidate, rel_type="fav")

        base = {truck_a.id: 1.0}
        original_base = base.copy()
        crews = {truck_a.id: [{"id": driver.id, "role": "driver"}]}

        calculate_weights(
            employee_id=candidate.id,
            employee_role="driver",
            base_weights=base,
            assigned_crews=crews,
            banned_truck_ids=[],
            db=db,
        )

        assert base == original_base, (
            "calculate_weights must not mutate the caller's base_weights dict"
        )


# ---------------------------------------------------------------------------
# assign_drivers
# ---------------------------------------------------------------------------

class TestAssignDrivers:
    """
    assign_drivers() places exactly one driver on each truck, consuming
    drivers from the pool without double-assigning anyone.
    """

    def test_one_driver_per_truck(self, db):
        """
        ARRANGE: 2 trucks, 2 drivers.
        ASSERT: each truck has exactly one driver in assigned_crews.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver_1 = make_employee(db, role="driver", name="Driver 1")
        driver_2 = make_employee(db, role="driver", name="Driver 2")

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_drivers(
            available_drivers=[driver_1, driver_2],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        for truck_id in [truck_a.id, truck_b.id]:
            drivers_on_truck = [c for c in assigned_crews[truck_id] if c["role"] == "driver"]
            assert len(drivers_on_truck) == 1, f"Truck {truck_id} should have exactly 1 driver"

    def test_no_driver_double_assigned(self, db):
        """
        Each driver UUID should appear in assigned_crews exactly once
        across all trucks.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver_1 = make_employee(db, role="driver", name="Driver 1")
        driver_2 = make_employee(db, role="driver", name="Driver 2")

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_drivers(
            available_drivers=[driver_1, driver_2],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        all_assigned_ids = [
            c["id"]
            for crew in assigned_crews.values()
            for c in crew
        ]
        # No UUID should appear more than once
        assert len(all_assigned_ids) == len(set(all_assigned_ids)), (
            "No driver should be assigned to more than one truck"
        )

    def test_fewer_drivers_than_trucks_leaves_trucks_empty(self, db):
        """
        If there are fewer drivers than trucks, the remaining trucks stay empty.
        This is the scenario that causes dispatch to raise a ValueError in run_dispatch.
        assign_drivers itself does not raise — it just runs out of drivers.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver_1 = make_employee(db, role="driver", name="Only Driver")

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        assign_drivers(
            available_drivers=[driver_1],
            assigned_crews=assigned_crews,
            base_weights=base_weights,
            db=db,
        )

        total_drivers_placed = sum(
            1 for crew in assigned_crews.values()
            for c in crew if c["role"] == "driver"
        )
        assert total_drivers_placed == 1, (
            "Only 1 driver available — only 1 should be placed"
        )

    def test_consecutive_penalty_reduces_same_truck_probability(self, db):
        """
        When a driver was on truck_a yesterday, their weight for truck_a is 0.05.
        We can't assert the random outcome, but we CAN assert the weights array
        that assign_drivers builds internally. We do this by patching random.choices
        to capture the weights it was called with.

        WHAT 'patch' DOES:
        unittest.mock.patch temporarily replaces random.choices with a fake version
        during the test. The fake records every call and its arguments, then we
        inspect them. After the test, random.choices is restored automatically.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        driver = make_employee(db, role="driver", name="Driver")

        # Give the driver a history on truck_a
        yesterday = date.today() - timedelta(days=1)
        assignment = make_assignment(db, truck_a, yesterday)
        make_member(db, assignment, driver, role="driver")

        assigned_crews = {truck_a.id: [], truck_b.id: []}
        base_weights   = {truck_a.id: 1.0, truck_b.id: 1.0}

        captured_weights = []

        def fake_choices(population, weights=None, k=1):
            # Record the weights, then return the first candidate so dispatch can proceed
            captured_weights.extend(weights or [])
            return [population[0]]

        with patch("app.services.assign_drivers.random.choices", side_effect=fake_choices):
            assign_drivers(
                available_drivers=[driver],
                assigned_crews=assigned_crews,
                base_weights=base_weights,
                db=db,
            )

        # The first (and only) call to random.choices should have passed weight=0.05
        # for this driver because truck_a is their consecutive truck
        assert captured_weights[0] == pytest.approx(0.05), (
            "Consecutive truck should get weight 0.05 in the driver weight list"
        )
