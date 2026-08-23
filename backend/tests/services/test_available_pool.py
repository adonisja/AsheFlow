"""
Tests for available_pool — get_available_pool and get_unavailable_staff.

WHAT WE'RE TESTING:
get_available_pool() returns active field staff grouped by role, excluding
employees with an approved recurring off-day or approved PTO on the target date.

get_unavailable_staff() is the inverse: returns the excluded employees with
a reason (time_off_request | recurring_off_day).

COVERAGE:
- Active employees with no exclusions appear in the pool by role
- Inactive employees are never in the pool
- Recurring off-day on target weekday excludes employee
- Recurring off-day on a different weekday does NOT exclude
- Pending off-day (not approved) does NOT exclude
- Approved PTO on target date excludes employee
- PTO on a different date does NOT exclude
- Pending PTO does NOT exclude
- Management/admin/dispatch roles are never in the pool (field-only)
- company_id isolation: only same-company employees returned
- get_unavailable_staff returns correct reason field
- get_unavailable_staff filters by requested roles list
- Trainees are excluded from get_unavailable_staff (training system owns them)
- Empty pool when all staff are off
- company_id required: ValueError raised when omitted
"""

import uuid
from datetime import date, timedelta

import pytest

from app.services.available_pool import get_available_pool, get_unavailable_staff
from tests.conftest import (
    SEED_COMPANY_ID,
    make_employee,
    make_off_day,
    make_time_off_request,
)


# ---------------------------------------------------------------------------
# Helper — a date whose weekday we can control
# ---------------------------------------------------------------------------

def _date_for_weekday(weekday_name: str) -> date:
    """Return the next occurrence of weekday_name on or after today."""
    target = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
               "Friday": 4, "Saturday": 5, "Sunday": 6}[weekday_name]
    d = date.today()
    while d.weekday() != target:
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# Basic pool construction
# ---------------------------------------------------------------------------

class TestPoolConstruction:
    """Active field-staff employees with no exclusions appear in the pool."""

    def test_driver_appears_in_pool(self, db):
        driver = make_employee(db, role="driver", name="Driver")
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        assert driver in pool["drivers"]

    def test_walker_appears_in_pool(self, db):
        walker = make_employee(db, role="walker", name="Walker")
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        assert walker in pool["walkers"]

    def test_trainer_appears_in_pool(self, db):
        trainer = make_employee(db, role="trainer", name="Trainer")
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        assert trainer in pool["trainers"]

    def test_trainee_appears_in_pool(self, db):
        trainee = make_employee(db, role="trainee", name="Trainee")
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        assert trainee in pool["trainees"]

    def test_inactive_employee_excluded(self, db):
        driver = make_employee(db, role="driver", name="Inactive Driver")
        driver.is_active = False
        db.commit()
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        assert driver not in pool["drivers"]

    def test_management_not_in_pool(self, db):
        mgr = make_employee(db, role="management", name="Manager")
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        all_pool = pool["drivers"] + pool["trainers"] + pool["walkers"] + pool["trainees"]
        assert mgr not in all_pool

    def test_admin_not_in_pool(self, db):
        admin = make_employee(db, role="admin", name="Admin")
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        all_pool = pool["drivers"] + pool["trainers"] + pool["walkers"] + pool["trainees"]
        assert admin not in all_pool

    def test_empty_pool_when_no_employees(self, db):
        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        # "captains" added by ADR-256, "driver_trainees" by ADR-264. Asserted as
        # an exact dict on purpose: a bucket appearing or vanishing changes the
        # headcount-cap arithmetic in run_dispatch, which sums these keys by
        # name — this test failing on a new bucket is the guard working.
        assert pool == {
            "drivers": [], "trainers": [], "trainees": [], "walkers": [],
            "captains": [], "driver_trainees": [],
        }


# ---------------------------------------------------------------------------
# Recurring off-day exclusion
# ---------------------------------------------------------------------------

class TestRecurringOffDay:
    """Approved off-day on the target weekday removes the employee from the pool."""

    def test_approved_off_day_on_target_weekday_excludes(self, db):
        target = date.today()
        weekday = target.strftime("%A")
        driver = make_employee(db, role="driver")
        make_off_day(db, driver, weekday, status="approved")

        pool = get_available_pool(db, target_date=target, company_id=SEED_COMPANY_ID)
        assert driver not in pool["drivers"]

    def test_off_day_on_different_weekday_does_not_exclude(self, db):
        target = date.today()
        # Pick a different weekday than today
        other_day = (date.today() + timedelta(days=1)).strftime("%A")
        driver = make_employee(db, role="driver")
        make_off_day(db, driver, other_day, status="approved")

        pool = get_available_pool(db, target_date=target, company_id=SEED_COMPANY_ID)
        assert driver in pool["drivers"]

    def test_pending_off_day_does_not_exclude(self, db):
        target = date.today()
        weekday = target.strftime("%A")
        driver = make_employee(db, role="driver")
        make_off_day(db, driver, weekday, status="pending")

        pool = get_available_pool(db, target_date=target, company_id=SEED_COMPANY_ID)
        assert driver in pool["drivers"]


# ---------------------------------------------------------------------------
# PTO / time-off-request exclusion
# ---------------------------------------------------------------------------

class TestPTOExclusion:
    """Approved PTO on the exact target date removes the employee from the pool."""

    def test_approved_pto_on_target_date_excludes(self, db):
        target = date.today()
        driver = make_employee(db, role="driver")
        make_time_off_request(db, driver, target_date=target, status="approved")

        pool = get_available_pool(db, target_date=target, company_id=SEED_COMPANY_ID)
        assert driver not in pool["drivers"]

    def test_pto_on_different_date_does_not_exclude(self, db):
        target = date.today()
        other_date = target + timedelta(days=1)
        driver = make_employee(db, role="driver")
        make_time_off_request(db, driver, target_date=other_date, status="approved")

        pool = get_available_pool(db, target_date=target, company_id=SEED_COMPANY_ID)
        assert driver in pool["drivers"]

    def test_pending_pto_does_not_exclude(self, db):
        target = date.today()
        driver = make_employee(db, role="driver")
        make_time_off_request(db, driver, target_date=target, status="pending")

        pool = get_available_pool(db, target_date=target, company_id=SEED_COMPANY_ID)
        assert driver in pool["drivers"]

    def test_pto_and_off_day_both_exclude(self, db):
        """Employee with both PTO and recurring off-day is still excluded exactly once."""
        target = date.today()
        weekday = target.strftime("%A")
        driver = make_employee(db, role="driver")
        make_off_day(db, driver, weekday, status="approved")
        make_time_off_request(db, driver, target_date=target, status="approved")

        pool = get_available_pool(db, target_date=target, company_id=SEED_COMPANY_ID)
        assert driver not in pool["drivers"]
        assert pool["drivers"].count(driver) == 0


# ---------------------------------------------------------------------------
# Multi-tenant isolation
# ---------------------------------------------------------------------------

class TestCompanyIsolation:
    """Employees from a different company must never appear in the pool."""

    def test_other_company_employee_excluded(self, db):
        other_company_id = uuid.uuid4()
        outsider = make_employee(db, role="driver", name="Outsider")
        outsider.company_id = other_company_id
        db.commit()

        pool = get_available_pool(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        assert outsider not in pool["drivers"]

    def test_company_id_required(self, db):
        with pytest.raises(ValueError, match="company_id is required"):
            get_available_pool(db, target_date=date.today(), company_id=None)


# ---------------------------------------------------------------------------
# get_unavailable_staff
# ---------------------------------------------------------------------------

class TestUnavailableStaff:
    """get_unavailable_staff returns excluded employees with the correct reason."""

    def test_pto_reason_is_time_off_request(self, db):
        target = date.today()
        driver = make_employee(db, role="driver", name="PTO Driver")
        make_time_off_request(db, driver, target_date=target, status="approved")

        result = get_unavailable_staff(db, target_date=target, company_id=SEED_COMPANY_ID)
        entry = next((r for r in result if r["id"] == str(driver.id)), None)
        assert entry is not None
        assert entry["reason"] == "time_off_request"

    def test_off_day_reason_is_recurring_off_day(self, db):
        target = date.today()
        weekday = target.strftime("%A")
        driver = make_employee(db, role="driver", name="Off Day Driver")
        make_off_day(db, driver, weekday, status="approved")

        result = get_unavailable_staff(db, target_date=target, company_id=SEED_COMPANY_ID)
        entry = next((r for r in result if r["id"] == str(driver.id)), None)
        assert entry is not None
        assert entry["reason"] == "recurring_off_day"

    def test_available_employee_not_in_unavailable_list(self, db):
        driver = make_employee(db, role="driver", name="Available Driver")
        result = get_unavailable_staff(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        ids = [r["id"] for r in result]
        assert str(driver.id) not in ids

    def test_roles_filter_excludes_unspecified_roles(self, db):
        target = date.today()
        weekday = target.strftime("%A")
        driver = make_employee(db, role="driver", name="Driver Off")
        trainer = make_employee(db, role="trainer", name="Trainer Off")
        make_off_day(db, driver, weekday)
        make_off_day(db, trainer, weekday)

        # Ask for only trainers
        result = get_unavailable_staff(
            db, target_date=target, roles=["trainer"], company_id=SEED_COMPANY_ID
        )
        ids = [r["id"] for r in result]
        assert str(trainer.id) in ids
        assert str(driver.id) not in ids

    def test_trainees_excluded_from_unavailable_staff(self, db):
        """Trainees are never in get_unavailable_staff — the training system owns them."""
        target = date.today()
        weekday = target.strftime("%A")
        trainee = make_employee(db, role="trainee", name="Trainee Off")
        make_off_day(db, trainee, weekday)

        result = get_unavailable_staff(db, target_date=target, company_id=SEED_COMPANY_ID)
        ids = [r["id"] for r in result]
        assert str(trainee.id) not in ids

    def test_result_includes_contact_fields(self, db):
        target = date.today()
        weekday = target.strftime("%A")
        driver = make_employee(db, role="driver", name="Contact Driver")
        make_off_day(db, driver, weekday)

        result = get_unavailable_staff(db, target_date=target, company_id=SEED_COMPANY_ID)
        entry = next(r for r in result if r["id"] == str(driver.id))
        assert "name" in entry
        assert "role" in entry
        assert "discord_id" in entry
        assert "phone_number" in entry

    def test_company_id_required_for_unavailable_staff(self, db):
        with pytest.raises(ValueError, match="company_id is required"):
            get_unavailable_staff(db, target_date=date.today(), company_id=None)

    def test_empty_when_no_exclusions(self, db):
        make_employee(db, role="driver")
        result = get_unavailable_staff(db, target_date=date.today(), company_id=SEED_COMPANY_ID)
        assert result == []


# ---------------------------------------------------------------------------
# get_emergency_pool — ADR-267
#
# The call-in list's successor. Membership is deliberately NOT the same:
#   included: scheduled_off, declined, unassigned
#   excluded: approved PTO (they asked for the day), trainees
# ---------------------------------------------------------------------------

from app.models.dispatch_confirmation import DispatchConfirmation  # noqa: E402
from app.services.available_pool import get_emergency_pool  # noqa: E402
from tests.conftest import make_assignment, make_member, make_truck  # noqa: E402


def _decline(db, employee, target_date, status="declined"):
    row = DispatchConfirmation(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=employee.id,
        date=target_date, status=status,
    )
    db.add(row)
    db.commit()
    return row


class TestEmergencyPoolMembership:
    def test_unassigned_staff_are_contactable(self, db):
        e = make_employee(db, role="walker", name="Una Signed")
        pool = get_emergency_pool(db, date.today(), company_id=SEED_COMPANY_ID)
        row = next(p for p in pool if p["id"] == str(e.id))
        assert row["reason"] == "unassigned"

    def test_scheduled_off_staff_are_contactable(self, db):
        d = _date_for_weekday("Wednesday")
        e = make_employee(db, role="walker", name="Ola Off")
        make_off_day(db, e, "Wednesday")
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        row = next(p for p in pool if p["id"] == str(e.id))
        assert row["reason"] == "scheduled_off"

    def test_decliners_are_contactable(self, db):
        """The group the old call-in list omitted — and the whole reason the
        pool exists. A decline is often circumstantial and negotiable."""
        d = date.today()
        e = make_employee(db, role="walker", name="Dee Clined")
        _decline(db, e, d)
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        row = next(p for p in pool if p["id"] == str(e.id))
        assert row["reason"] == "declined"

    def test_approved_pto_is_never_contactable(self, db):
        """THE inversion vs the old list, which showed PTO. They requested the
        day and it was granted; offering them a shift is the wrong call."""
        d = date.today()
        e = make_employee(db, role="walker", name="Pia Teeoh")
        make_time_off_request(db, e, d, status="approved")
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        assert str(e.id) not in {p["id"] for p in pool}

    def test_pto_wins_over_being_unassigned(self, db):
        """Someone on PTO is also trivially unassigned. The exclusion must not
        be defeated by the broader group."""
        d = date.today()
        e = make_employee(db, role="driver", name="Both Ways")
        make_time_off_request(db, e, d, status="approved")
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        assert str(e.id) not in {p["id"] for p in pool}

    def test_pending_pto_does_not_exclude(self, db):
        """Only APPROVED time off is a real commitment."""
        d = date.today()
        e = make_employee(db, role="walker", name="Penny Ding")
        make_time_off_request(db, e, d, status="pending")
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        assert str(e.id) in {p["id"] for p in pool}

    def test_trainees_are_excluded(self, db):
        """Their assignment runs through the training system, not a phone call."""
        make_employee(db, role="trainee", name="Tia Rainee")
        pool = get_emergency_pool(db, date.today(), company_id=SEED_COMPANY_ID)
        assert "trainee" not in {p["role"] for p in pool}

    def test_inactive_staff_are_excluded(self, db):
        e = make_employee(db, role="walker", name="Ina Ctive")
        e.is_active = False
        db.commit()
        pool = get_emergency_pool(db, date.today(), company_id=SEED_COMPANY_ID)
        assert str(e.id) not in {p["id"] for p in pool}

    def test_assigned_and_not_declined_is_not_in_the_pool(self, db):
        """Someone already on a truck who has said nothing is working. Listing
        them would drown the real candidates."""
        d = date.today()
        e = make_employee(db, role="walker", name="Onna Truck")
        truck = make_truck(db, name="T-EP1")
        assignment = make_assignment(db, truck, target_date=d)
        make_member(db, assignment, e, "walker")
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        assert str(e.id) not in {p["id"] for p in pool}

    def test_an_assigned_decliner_IS_in_the_pool(self, db):
        """The core case: they were on a truck and pulled out. Being assigned
        must not mask the decline."""
        d = date.today()
        e = make_employee(db, role="driver", name="Quit Lastminute")
        truck = make_truck(db, name="T-EP2")
        assignment = make_assignment(db, truck, target_date=d)
        make_member(db, assignment, e, "driver")
        _decline(db, e, d)
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        row = next(p for p in pool if p["id"] == str(e.id))
        assert row["reason"] == "declined"

    def test_confirmed_staff_are_not_in_the_pool(self, db):
        d = date.today()
        e = make_employee(db, role="walker", name="Yes Confirmed")
        truck = make_truck(db, name="T-EP3")
        assignment = make_assignment(db, truck, target_date=d)
        make_member(db, assignment, e, "walker")
        _decline(db, e, d, status="confirmed")
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        assert str(e.id) not in {p["id"] for p in pool}

    def test_decline_outranks_scheduled_off_as_the_reason(self, db):
        """Where several apply, the most actionable wins — a fresh decline is a
        signal to react to, an off-day is a standing fact."""
        d = _date_for_weekday("Thursday")
        e = make_employee(db, role="walker", name="Both Reasons")
        make_off_day(db, e, "Thursday")
        _decline(db, e, d)
        pool = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)
        row = next(p for p in pool if p["id"] == str(e.id))
        assert row["reason"] == "declined"


class TestEmergencyPoolShape:
    def test_contact_channels_are_returned(self, db):
        """Dispatch must be able to reach someone without leaving the page."""
        e = make_employee(db, role="walker", name="Contact Able")
        e.phone_number, e.email, e.discord_id = "+15551234567", "c@x.com", "12345"
        db.commit()
        pool = get_emergency_pool(db, date.today(), company_id=SEED_COMPANY_ID)
        row = next(p for p in pool if p["id"] == str(e.id))
        assert row["phone_number"] == "+15551234567"
        assert row["email"] == "c@x.com"
        assert row["discord_id"] == "12345"

    def test_drivers_and_captains_sort_first(self, db):
        """Their absence strands a truck, so they are what dispatch reaches for."""
        make_employee(db, role="walker",  name="Zeb Walker")
        make_employee(db, role="driver",  name="Zoe Driver")
        make_employee(db, role="captain", name="Zack Captain")
        pool = get_emergency_pool(db, date.today(), company_id=SEED_COMPANY_ID)
        roles = [p["role"] for p in pool if p["name"].startswith("Z")]
        assert roles == ["driver", "captain", "walker"]

    def test_company_id_is_required(self, db):
        with pytest.raises(ValueError):
            get_emergency_pool(db, date.today())

    def test_other_company_staff_are_never_returned(self, db):
        pool = get_emergency_pool(db, date.today(), company_id=uuid.uuid4())
        assert pool == []


class TestDayOfWeekCaseConsistency:
    """The three readers of EmployeeOffDay.day_of_week must never disagree.

    Three places ask "is this person off today" — /schedule/available,
    get_emergency_pool and get_available_pool — and they historically mixed
    `ilike` with `==`. That looked like a latent bug: a row stored as "friday"
    would satisfy one and not the others, putting the same person in the
    dispatch pool AND the emergency pool.

    It turned out the schema already prevents it. A CHECK constraint
    (`ck_employee_off_days_day_of_week`, present since the initial migration)
    admits only exact Title-case day names, so the two comparisons cannot
    diverge on stored data.

    These tests pin BOTH halves of that: the constraint that makes it true, and
    the agreement it guarantees. If someone relaxes the constraint to accept
    free-form casing, the first test fails and points at the second.
    """

    def test_the_schema_rejects_non_title_case_days(self):
        """The constraint is what makes ilike-vs-== a non-issue. Without it the
        comparison mismatch becomes real, so its existence is load-bearing."""
        from app.models.employee_off_day import EmployeeOffDay
        checks = [
            str(c.sqltext) for c in EmployeeOffDay.__table__.constraints
            if hasattr(c, "sqltext")
        ]
        joined = " ".join(checks)
        assert "day_of_week IN" in joined
        for day in ("Monday", "Friday", "Sunday"):
            assert f"'{day}'" in joined
        assert "'friday'" not in joined, "lowercase accepted — comparisons can now diverge"

    def test_a_stored_off_day_agrees_across_both_pools(self, db):
        """The invariant that matters: nobody may be simultaneously 'available
        for dispatch' and 'off, call them in an emergency'."""
        d = _date_for_weekday("Friday")
        e = make_employee(db, role="walker", name="Both Pools")
        make_off_day(db, e, "Friday")

        available = get_available_pool(db, d, company_id=SEED_COMPANY_ID)
        emergency = get_emergency_pool(db, d, company_id=SEED_COMPANY_ID)

        in_available = e.id in {x.id for x in available["walkers"]}
        in_emergency = str(e.id) in {m["id"] for m in emergency}
        assert not in_available, "off-day staff must not be in the dispatch pool"
        assert in_emergency, "off-day staff must be callable in an emergency"
