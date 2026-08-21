"""Availability exclusions are company-scoped (ADR-115 D1, ADR-268 audit).

WHAT THIS PROTECTS
`get_coverage_depth`, `get_available_pool` and `get_emergency_pool` all decide
who is available by subtracting two exclusion sets: approved PTO
(`TimeOffRequest`) and approved recurring days off (`EmployeeOffDay`).

Those exclusion queries were filtered by `employee_id.in_(ids)` and NOT by
`company_id`, even though both tables carry the column. That is safe only
TRANSITIVELY: `ids` comes from a company-scoped `Employee` query several
statements earlier, so no foreign row can match today. It stops being safe the
moment anyone widens that list, changes where it comes from, or copies the
pattern into a new function — which is precisely how it reached
`get_coverage_depth` in the first place.

WHY A CROSS-TENANT FIXTURE IS THE ONLY TEST THAT WORKS
Every existing test in this suite is single-tenant. A scoping bug is invisible
to a single-tenant test by construction: with one company in the database,
"filtered by company" and "not filtered at all" return identical rows.

THE MISTAKE THIS FILE ALMOST SHIPPED WITH
The obvious cross-tenant fixture — give THEIR employee a PTO row, assert OUR
count is unchanged — also cannot fail. An unscoped query does return that
foreign row, but the row excludes `theirs.id`, and our driver was never in
that set, so the answer is identical either way. All six planted regressions
passed against that version.

The exclusion queries filter `employee_id.in_(our_ids)`, so the only row that
can do damage is one carrying **our employee's id** under **their company_id**
— a shape that arises from a mis-scoped write, an ID collision, or a tenant
migration. That is the fixture used below, and it is what makes the planted
regressions fail.
"""
import uuid
from datetime import date, timedelta

import pytest

from app.models.company import Company
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest
from app.services.available_pool import get_available_pool, get_emergency_pool
from app.services.outcome_signals import get_coverage_depth
from tests.conftest import SEED_COMPANY_ID, make_employee

OTHER_COMPANY_ID = uuid.UUID("b0000000-0000-0000-0000-000000000002")


@pytest.fixture
def two_tenants(db):
    """Seed a second company and return (ours, theirs) driver employees.

    The two employees are deliberately given the SAME role and the same active
    state, so the only thing distinguishing them is company_id.
    """
    db.add(Company(id=OTHER_COMPANY_ID, name="Other Co", slug="other",
                   is_active=True))
    db.commit()

    ours = make_employee(db, role="driver", name="Our Driver")
    theirs = Employee(
        id=uuid.uuid4(), company_id=OTHER_COMPANY_ID, name="Their Driver",
        role="driver", is_active=True, discord_id=str(uuid.uuid4()),
    )
    db.add(theirs)
    db.commit()
    db.refresh(theirs)
    return ours, theirs


def _pto(db, employee, when, company_id):
    db.add(TimeOffRequest(
        id=uuid.uuid4(), company_id=company_id, employee_id=employee.id,
        date=when, status="approved",
    ))
    db.commit()


def _off_day(db, employee, weekday, company_id):
    db.add(EmployeeOffDay(
        id=uuid.uuid4(), company_id=company_id, employee_id=employee.id,
        day_of_week=weekday, status="approved",
    ))
    db.commit()


class TestCoverageDepthScoping:
    def test_foreign_pto_row_for_our_employee_does_not_exclude(self, db, two_tenants):
        """A PTO row under ANOTHER company's id, naming OUR employee, must not
        exclude them.

        This is the only shape that can do damage: the query filters
        `employee_id.in_(our_ids)`, so a foreign row naming THEIR employee is
        discarded by the id bound regardless of scoping. Only a foreign row
        naming OUR employee reaches the exclusion set, and only the company_id
        filter stops it.
        """
        ours, _ = two_tenants
        today = date.today()

        _pto(db, ours, today, OTHER_COMPANY_ID)   # our employee, their company

        depth = get_coverage_depth(db, SEED_COMPANY_ID, today)
        assert depth.spare_drivers == 1, (
            "a PTO row belonging to another company excluded our driver — "
            "the TimeOffRequest query is not company-scoped"
        )

    def test_foreign_off_day_row_for_our_employee_does_not_exclude(self, db, two_tenants):
        ours, _ = two_tenants
        today = date.today()

        _off_day(db, ours, today.strftime("%A"), OTHER_COMPANY_ID)

        depth = get_coverage_depth(db, SEED_COMPANY_ID, today)
        assert depth.spare_drivers == 1, (
            "a recurring day off belonging to another company excluded our "
            "driver — the EmployeeOffDay query is not company-scoped"
        )

    def test_their_employee_never_counts_as_our_spare(self, db, two_tenants):
        """The outer query's own scoping, pinned separately."""
        depth = get_coverage_depth(db, SEED_COMPANY_ID, date.today())
        assert depth.spare_drivers == 1, "another company's driver was counted"

    def test_our_own_pto_still_excludes(self, db, two_tenants):
        """The counterpart. A scoping fix that excluded EVERYTHING would pass
        the two tests above while breaking the feature — this pins that the
        exclusion still works for rows that legitimately apply."""
        ours, _ = two_tenants
        today = date.today()

        _pto(db, ours, today, SEED_COMPANY_ID)

        depth = get_coverage_depth(db, SEED_COMPANY_ID, today)
        assert depth.spare_drivers == 0, "our own approved PTO stopped excluding"


class TestAvailablePoolScoping:
    def test_foreign_rows_do_not_shrink_our_pool(self, db, two_tenants):
        ours, theirs = two_tenants
        today = date.today()

        # Foreign-company rows naming OUR employee — see the module docstring
        # for why rows naming THEIR employee cannot fail this test.
        _pto(db, ours, today, OTHER_COMPANY_ID)
        _off_day(db, ours, today.strftime("%A"), OTHER_COMPANY_ID)

        pool = get_available_pool(db, target_date=today,
                                  company_id=SEED_COMPANY_ID)
        # get_available_pool returns ORM Employee objects grouped by role —
        # get_emergency_pool returns dicts. Different shapes, same module.
        names = [e.name for group in pool.values() for e in group]
        assert "Our Driver" in names, (
            "another company's exclusion rows removed our driver from the pool"
        )
        assert "Their Driver" not in names, "cross-tenant employee leaked in"

    def test_our_own_rows_still_shrink_it(self, db, two_tenants):
        ours, _ = two_tenants
        today = date.today()

        _pto(db, ours, today, SEED_COMPANY_ID)

        pool = get_available_pool(db, target_date=today,
                                  company_id=SEED_COMPANY_ID)
        # get_available_pool returns ORM Employee objects grouped by role —
        # get_emergency_pool returns dicts. Different shapes, same module.
        names = [e.name for group in pool.values() for e in group]
        assert "Our Driver" not in names, "our own PTO stopped excluding"


class TestEmergencyPoolScoping:
    def test_foreign_pto_does_not_promote_or_demote(self, db, two_tenants):
        """get_emergency_pool uses PTO as a HARD exclusion, so a foreign row
        leaking in would silently drop a callable person from the list shown
        when someone declines last-minute."""
        ours, theirs = two_tenants
        today = date.today()

        _pto(db, ours, today, OTHER_COMPANY_ID)   # our employee, their company

        pool = get_emergency_pool(db, company_id=SEED_COMPANY_ID,
                                  target_date=today)
        names = [p["name"] for p in pool]
        assert "Our Driver" in names, (
            "another company's PTO removed our driver from the emergency pool"
        )
        assert "Their Driver" not in names, "cross-tenant employee leaked in"