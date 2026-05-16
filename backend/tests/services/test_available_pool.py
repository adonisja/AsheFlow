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
        assert pool == {"drivers": [], "trainers": [], "trainees": [], "walkers": []}


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
