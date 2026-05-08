"""
Tests for run_dispatch — the integration layer.

HOW run_dispatch WORKS (summary):
1. Graduate eligible trainees (5+ assignments → role becomes walker).
2. Build available_pool from active employees not on a scheduled off day.
3. Optionally trim pool to total_employees cap (walkers first, then trainees, trainers).
4. Emit staffing warnings: understaffed_drivers always; understaffed_walkers only when capped.
5. Distribute excess trainers evenly across trucks (they stay as trainers — no re-slotting).
6. Run assign_drivers → assign_trainers → continuation pre-pass → assign_trainees
   → assign_walkers → rebalance_crews.
7. Persist TruckAssignment + AssignmentMember rows, inject curriculum.
8. Return (formatted_crews dict, warnings list).

WHAT WE'RE VERIFYING AT THIS LEVEL:
- The pipeline produces valid output shape (not tested by unit tests).
- Staffing warnings are emitted under the right conditions.
- The headcount cap trims the pool correctly.
- Excess trainers are distributed as trainers (not re-slotted as walkers).
- TruckAssignment and AssignmentMember rows are committed to the DB.

WHY INTEGRATION TESTS HERE:
The sub-services (assign_drivers, assign_trainers, etc.) are unit-tested elsewhere.
run_dispatch tests focus on: does the pipeline wire correctly? Are the DB writes made?
Are the right warnings surfaced at the right thresholds?
"""

from datetime import date

import pytest

from app.services.run_dispatch import run_dispatch
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember

from tests.conftest import make_employee, make_truck, SEED_COMPANY_ID


# ---------------------------------------------------------------------------
# Happy path — basic pipeline shape
# ---------------------------------------------------------------------------

class TestHappyPath:
    """
    Verify the full pipeline runs without error on a minimal valid setup and
    produces a well-formed output.
    """

    def test_two_trucks_two_drivers_produces_two_crews(self, db):
        """
        ARRANGE: 2 active trucks, 2 drivers, no other staff.
        ACT: run_dispatch.
        ASSERT:
        - formatted_crews has exactly 2 entries (one per truck).
        - Each crew has exactly 1 driver.
        - No staffing warnings.

        WHY MINIMAL SETUP:
        We only care that the pipeline runs end-to-end and writes the right shape.
        Trainers and walkers are tested at the unit level — here we keep noise low.
        """
        truck_a = make_truck(db, "Truck A")
        truck_b = make_truck(db, "Truck B")
        make_employee(db, role="driver", name="Driver A")
        make_employee(db, role="driver", name="Driver B")

        formatted_crews, warnings = run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        assert len(formatted_crews) == 2, "Should produce one crew entry per truck"

        for truck_id_str, crew in formatted_crews.items():
            drivers = [m for m in crew if m["role"] == "driver"]
            assert len(drivers) == 1, f"Truck {truck_id_str} should have exactly 1 driver"

        staffing_warnings = [w for w in warnings if w.get("type") == "understaffed_drivers"]
        assert staffing_warnings == [], "No driver shortage with 2 drivers for 2 trucks"

    def test_output_contains_employee_name_and_id(self, db):
        """
        Spot-check the shape of each crew member dict in formatted_crews.
        ASSERT: each member has 'name', 'employee_id', 'role', 'assignment_id'.

        WHY: run_dispatch builds formatted_crews by querying back through
        TruckAssignment → AssignmentMember → Employee. If any join is wrong,
        these fields go missing. A shape check catches that.
        """
        make_truck(db, "Truck A")
        driver = make_employee(db, role="driver", name="Known Driver")

        formatted_crews, _ = run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        all_members = [m for crew in formatted_crews.values() for m in crew]
        assert len(all_members) >= 1

        member = all_members[0]
        assert "name" in member
        assert "employee_id" in member
        assert "role" in member
        assert "assignment_id" in member
        assert member["name"] == "Known Driver"


# ---------------------------------------------------------------------------
# Driver shortage warning
# ---------------------------------------------------------------------------

class TestDriverShortage:
    """
    When available drivers < number of active trucks, an understaffed_drivers
    warning must be emitted. Dispatch still runs — trucks without drivers are
    left empty for manual assignment.
    """

    def test_fewer_drivers_than_trucks_emits_warning(self, db):
        """
        ARRANGE: 2 trucks, 1 driver.
        ASSERT: warnings contains exactly 1 understaffed_drivers entry.

        WHY DISPATCH STILL RUNS:
        A missing driver is operationally recoverable — the dispatcher assigns
        manually. Raising an exception here would block all dispatch on any
        bad day. Warnings let the caller handle it gracefully.
        """
        make_truck(db, "Truck A")
        make_truck(db, "Truck B")
        make_employee(db, role="driver", name="Solo Driver")

        _, warnings = run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        shortage = [w for w in warnings if w.get("type") == "understaffed_drivers"]
        assert len(shortage) == 1, "Exactly one understaffed_drivers warning expected"
        assert "1 available for 2 trucks" in shortage[0]["message"]

    def test_no_warning_when_drivers_match_trucks(self, db):
        """
        ARRANGE: 2 trucks, 2 drivers (exactly matched).
        ASSERT: no understaffed_drivers warning.
        """
        make_truck(db, "Truck A")
        make_truck(db, "Truck B")
        make_employee(db, role="driver", name="Driver A")
        make_employee(db, role="driver", name="Driver B")

        _, warnings = run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        shortage = [w for w in warnings if w.get("type") == "understaffed_drivers"]
        assert shortage == []


# ---------------------------------------------------------------------------
# Headcount cap — total_employees trimming
# ---------------------------------------------------------------------------

class TestHeadcountCap:
    """
    When total_employees is passed, run_dispatch trims the pool from the
    bottom up: walkers first, then trainees, then trainers. Warnings are
    emitted for trainer/walker shortfalls only when a cap is active.
    """

    def test_cap_trims_walkers_and_emits_warning(self, db):
        """
        ARRANGE:
        - 1 truck, 1 driver, 1 trainer, 2 walkers.
        - total_employees=2 (driver + trainer only — walkers should be cut).
        ASSERT:
        - understaffed_walkers warning emitted.
        - No walkers appear in the assigned crew.

        WHY total_employees=2:
        Driver (1) + Trainer (1) = 2. Both walkers are trimmed. The cap
        applies before any assignment runs, so the walker pool is empty.
        """
        truck = make_truck(db, "Truck A")
        make_employee(db, role="driver",  name="Driver")
        make_employee(db, role="trainer", name="Trainer")
        make_employee(db, role="walker",  name="Walker 1")
        make_employee(db, role="walker",  name="Walker 2")

        formatted_crews, warnings = run_dispatch(
            db, target_date=date.today(), total_employees=2, company_id=SEED_COMPANY_ID
        )

        walker_warning = [w for w in warnings if w.get("type") == "understaffed_walkers"]
        assert len(walker_warning) == 1, "Walker shortage warning should be emitted"

        all_walkers_in_crews = [
            m for crew in formatted_crews.values()
            for m in crew if m["role"] == "walker"
        ]
        assert all_walkers_in_crews == [], "No walkers should be assigned when trimmed by cap"

    def test_no_walker_warning_without_cap(self, db):
        """
        Without total_employees, walker warnings are suppressed — all available
        staff are distributed evenly, there are no unfilled slots.
        ASSERT: no understaffed_walkers warning even with 0 walkers.
        """
        make_truck(db, "Truck A")
        make_employee(db, role="driver", name="Driver")
        # No walkers in pool at all

        _, warnings = run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        walker_warning = [w for w in warnings if w.get("type") == "understaffed_walkers"]
        assert walker_warning == [], "Walker warning should not fire without an explicit cap"


# ---------------------------------------------------------------------------
# Excess trainer distribution
# ---------------------------------------------------------------------------

class TestExcessTrainerReSlot:
    """
    Excess trainers are distributed evenly as trainers across all trucks — they are
    NOT re-slotted as walkers. assign_trainers uses round-robin to spread them.
    """

    def test_excess_trainers_distributed_as_trainers(self, db):
        """
        ARRANGE:
        - 1 truck. 3 trainers available.
        ASSERT:
        - All 3 trainers appear in the crew as trainers (no reslotting).

        Reflects the current business rule: excess trainers stay as trainers
        and are distributed evenly across trucks.
        """
        make_truck(db, "Truck A")
        make_employee(db, role="driver",  name="Driver")
        make_employee(db, role="trainer", name="Trainer 1")
        make_employee(db, role="trainer", name="Trainer 2")
        make_employee(db, role="trainer", name="Trainer 3")

        formatted_crews, _ = run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        all_crew = [m for crew in formatted_crews.values() for m in crew]
        trainers = [m for m in all_crew if m["role"] == "trainer"]

        assert len(trainers) == 3, "All 3 trainers should be assigned as trainers"


# ---------------------------------------------------------------------------
# Persistence — rows written to DB
# ---------------------------------------------------------------------------

class TestPersistence:
    """
    run_dispatch must commit TruckAssignment and AssignmentMember rows.
    These tests query the DB after the call to verify writes happened.
    """

    def test_truck_assignment_rows_created(self, db):
        """
        ARRANGE: 2 trucks, 2 drivers.
        ACT: run_dispatch.
        ASSERT: 2 TruckAssignment rows exist in DB for today.

        WHY: if run_dispatch crashes before commit, or the loop is wrong,
        no rows appear. This catches silent failures in the persist step.
        """
        make_truck(db, "Truck A")
        make_truck(db, "Truck B")
        make_employee(db, role="driver", name="Driver A")
        make_employee(db, role="driver", name="Driver B")

        run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        assignments = db.query(TruckAssignment).filter(
            TruckAssignment.date == date.today()
        ).all()
        assert len(assignments) == 2, "One TruckAssignment row per truck"

    def test_assignment_member_rows_created(self, db):
        """
        ARRANGE: 1 truck, 1 driver.
        ASSERT: at least 1 AssignmentMember row exists linking the driver
        to today's TruckAssignment.

        WHY: the formatted_crews output is built from a re-query, not from
        in-memory state. If AssignmentMember rows aren't written, the output
        would be empty even if assigned_crews was correct internally.
        """
        make_truck(db, "Truck A")
        make_employee(db, role="driver", name="Driver")

        run_dispatch(db, target_date=date.today(), company_id=SEED_COMPANY_ID)

        members = db.query(AssignmentMember).all()
        assert len(members) >= 1, "At least one AssignmentMember row should be committed"

        roles = {m.role for m in members}
        assert "driver" in roles, "Driver should appear in AssignmentMember rows"
