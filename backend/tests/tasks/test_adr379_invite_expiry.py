"""A registered employee is not a stale invite (ADR-379).

`account_status = pending_verification` carried TWO meanings, and
`expire_pending_invites` only knew one.

`complete_registration` deliberately leaves the status alone -- its own comment
says "account_status stays pending_verification until they actually sign in" --
and only `get_caller_employee` promotes it, on an authenticated API call rather
than on Cognito sign-in.

So an employee invited on day 1 who registered on day 6 and first signed in on
day 8 was DELETED on day 7: DB row and Cognito user both, having done everything
asked of them.

There was no test for this task at all, which is how it survived. These run the
REAL query against a database rather than asserting on source text -- a
source-text test would have passed against the broken filter too.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.employee import Employee
from app.tasks.cleanup import expire_pending_invites, expire_registered_unused
from tests.conftest import SEED_COMPANY_ID

NOW = datetime.now(timezone.utc)


def _emp(db, *, name, username, invited_days_ago, status="pending_verification"):
    e = Employee(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=name, role="trainee",
        is_active=False, account_status=status,
        invited_at=NOW - timedelta(days=invited_days_ago),
        username=username, email=f"{name.lower().replace(' ', '.')}@x.com",
        reset_on_graduation=False, hr_system_id_adp=uuid.uuid4(),
        hr_system_id_adp_verified=False,
    )
    db.add(e)
    db.commit()
    return e


def _run(task, db):
    """Run a cleanup task against the test session, with Cognito stubbed.

    SessionLocal is patched to hand back the test's session so the task operates
    on the same rows the test created; boto3 is stubbed because the DB deletion
    is what is under test, not the pool cleanup.
    """
    db.close = lambda: None          # the task closes its session; the test still needs it
    with patch("app.tasks.cleanup.SessionLocal", return_value=db), \
         patch("app.tasks.cleanup.boto3.client", return_value=MagicMock()):
        return task()


class TestTheBugItself:
    def test_a_registered_employee_is_not_deleted(self, db):
        """THE regression. Registered on day 6, has not signed in, day 7 sweep."""
        e = _emp(db, name="Registered Hire", username="registered.hire",
                 invited_days_ago=8)

        _run(expire_pending_invites, db)

        assert db.query(Employee).filter(Employee.id == e.id).first() is not None, (
            "an employee who COMPLETED registration was deleted for not having "
            "signed in yet -- ADR-379 D1"
        )

    def test_an_unregistered_invite_is_still_deleted(self, db):
        """The behaviour the task exists for must survive the fix."""
        e = _emp(db, name="Never Registered", username=None, invited_days_ago=8)

        _run(expire_pending_invites, db)

        assert db.query(Employee).filter(Employee.id == e.id).first() is None, (
            "a stale unanswered invite must still expire"
        )

    def test_a_fresh_unregistered_invite_survives(self, db):
        e = _emp(db, name="Fresh Invite", username=None, invited_days_ago=1)
        _run(expire_pending_invites, db)
        assert db.query(Employee).filter(Employee.id == e.id).first() is not None

    def test_an_active_employee_is_never_touched(self, db):
        e = _emp(db, name="Working Person", username="working.person",
                 invited_days_ago=400, status="active")
        _run(expire_pending_invites, db)
        assert db.query(Employee).filter(Employee.id == e.id).first() is not None


class TestTheSecondSweep:
    """ADR-379 D2 -- registered but never used is a different question, so it
    gets a different clock (30 days, not 7)."""

    def test_a_long_unused_registered_account_is_expired(self, db):
        e = _emp(db, name="Never Signed In", username="never.signedin",
                 invited_days_ago=40)

        _run(expire_registered_unused, db)

        assert db.query(Employee).filter(Employee.id == e.id).first() is None, (
            "a registered account unused for 40 days leaves a live Cognito "
            "credential; it must expire"
        )

    def test_it_does_not_fire_inside_the_window(self, db):
        e = _emp(db, name="Recently Registered", username="recently.registered",
                 invited_days_ago=29)
        _run(expire_registered_unused, db)
        assert db.query(Employee).filter(Employee.id == e.id).first() is not None

    def test_it_ignores_unregistered_invites(self, db):
        """The other task owns those. Both firing on one row would be a double
        delete and a confusing log."""
        e = _emp(db, name="Old Unanswered", username=None, invited_days_ago=400)
        _run(expire_registered_unused, db)
        assert db.query(Employee).filter(Employee.id == e.id).first() is not None

    def test_it_ignores_active_employees(self, db):
        e = _emp(db, name="Long Timer", username="long.timer",
                 invited_days_ago=400, status="active")
        _run(expire_registered_unused, db)
        assert db.query(Employee).filter(Employee.id == e.id).first() is not None


class TestTheTwoTasksPartition:
    def test_no_row_can_be_selected_by_both(self, db):
        """One filters username IS NULL, the other IS NOT NULL. If that ever
        stops being true, one sweep deletes rows the other is counting."""
        registered = _emp(db, name="Reg Both", username="reg.both", invited_days_ago=400)
        unregistered = _emp(db, name="Unreg Both", username=None, invited_days_ago=400)

        _run(expire_pending_invites, db)
        assert db.query(Employee).filter(Employee.id == registered.id).first() is not None
        assert db.query(Employee).filter(Employee.id == unregistered.id).first() is None

        _run(expire_registered_unused, db)
        assert db.query(Employee).filter(Employee.id == registered.id).first() is None
