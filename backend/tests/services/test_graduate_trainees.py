"""
Tests for graduate_eligible_trainees.

HOW graduate_eligible_trainees WORKS (summary):
1. Query all active trainees.
2. For each trainee, count AssignmentMember rows joined to TruckAssignment
   where date < target_date (past completed assignments only).
3. If count < 5: skip.
4. If reset_on_graduation=True: delete all TrainingRecord + TrainingTask rows
   for this trainee and emit a reset Notification. Role stays 'trainee'.
5. Otherwise: promote trainee.role → 'walker', emit Notifications to all
   management/admin/dispatch staff and to the trainee themselves.
6. Nullify any open (pending/accepted) continuation requests for the trainee.
7. After all trainees processed: db.commit() once, then fire Discord DMs.
8. Return a list of warning dicts describing each graduation/reset.

WHAT WE'RE VERIFYING:
- Trainees with < 5 assignments are not graduated (threshold boundary).
- Trainees with exactly 5 assignments are graduated.
- Graduation promotes role to 'walker' and writes Notification rows.
- reset_on_graduation=True keeps role as 'trainee', resets training records.
- Open continuation requests are nullified on graduation.
- Continuation requests in other states (nullified, rejected) are not touched.
- Multiple trainees are processed independently in one call.
- Inactive trainees are excluded regardless of assignment count.

NOTE ON SQLite vs PostgreSQL:
The conftest db fixture uses SQLite in-memory. graduate_eligible_trainees uses
only standard SQL (no JSONB, no PostgreSQL-specific features), so SQLite is fine
for these tests. TrainingRecord and TrainingTask tables are in DISPATCH_TABLES.
We do need TrainerContinuationRequest, which is also already included.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.services.graduate_trainees import graduate_eligible_trainees
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from tests.conftest import SEED_COMPANY_ID
from app.models.notification import Notification
from app.models.training import TrainingRecord, TrainingTask
from app.models.trainer_continuation_request import TrainerContinuationRequest

from tests.conftest import make_employee, make_truck, make_assignment, make_member


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET = date.today()
PAST   = TARGET - timedelta(days=1)  # yesterday — counts as a past assignment


def make_past_assignment(db, truck: Truck, employee: Employee, days_ago: int = 1) -> AssignmentMember:
    """Add employee to a past TruckAssignment for truck on (TARGET - days_ago).

    Reuses the TruckAssignment if one already exists for that truck+date pair,
    so multiple trainees can share the same daily assignment without violating
    the unique constraint on (truck_id, date).
    """
    past_date = TARGET - timedelta(days=days_ago)
    ta = db.query(TruckAssignment).filter(
        TruckAssignment.truck_id == truck.id,
        TruckAssignment.date == past_date,
    ).first()
    if ta is None:
        ta = TruckAssignment(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=truck.id, date=past_date)
        db.add(ta)
        db.commit()
        db.refresh(ta)
    member = AssignmentMember(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        assignment_id=ta.id,
        employee_id=employee.id,
        role="trainee",
    )
    db.add(member)
    db.commit()
    return member


def give_assignments(db, truck: Truck, trainee: Employee, count: int):
    """Give `count` past assignments to `trainee` across distinct days."""
    for i in range(1, count + 1):
        make_past_assignment(db, truck, trainee, days_ago=i)


def make_continuation_request(db, trainee: Employee, trainer: Employee, status: str = "pending") -> TrainerContinuationRequest:
    req = TrainerContinuationRequest(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        trainee_id=trainee.id,
        trainer_id=trainer.id,
        status=status,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def make_training_record(db, trainee: Employee, trainer: Employee) -> TrainingRecord:
    rec = TrainingRecord(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        trainee_id=trainee.id,
        trainer_id=trainer.id,
        current_day_number=1,
        record_date=date.today(),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def make_training_task(db, record: TrainingRecord) -> TrainingTask:
    task = TrainingTask(
        id=uuid.uuid4(),
        company_id=record.company_id,
        training_record_id=record.id,
        topic_title="Test Topic",
        is_completed=False,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# Silence the Discord DM call in all tests — it reaches out to the bot HTTP server
@pytest.fixture(autouse=True)
def no_discord_dm():
    with patch("app.services.graduate_trainees._send_graduation_dm"):
        yield


# ---------------------------------------------------------------------------
# Threshold boundary — the 5-assignment gate
# ---------------------------------------------------------------------------

class TestThreshold:
    """
    Trainees must have 5+ past assignments (date < target_date) to graduate.
    Exactly 4 → no graduation. Exactly 5 → graduates.
    """

    def test_four_assignments_does_not_graduate(self, db):
        """
        ARRANGE: trainee with 4 past assignments.
        ASSERT: role stays 'trainee', no warnings, no Notifications.

        WHY 4 AND NOT 3:
        We test the boundary at threshold - 1, not some arbitrary small count,
        to confirm the < 5 guard is correct (not ≤ 4 or < 4).
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Almost There")
        give_assignments(db, truck, trainee, count=4)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "trainee", "4 assignments should not graduate"
        assert warnings == [], "No warnings when threshold not met"
        notifs = db.query(Notification).filter(Notification.employee_id == trainee.id).all()
        assert notifs == [], "No Notifications written for ungraduated trainee"

    def test_five_assignments_graduates(self, db):
        """
        ARRANGE: trainee with exactly 5 past assignments.
        ASSERT: role becomes 'walker', 1 warning returned.

        WHY EXACTLY 5:
        This is the boundary the product spec defines. Under-counting by even 1
        would mean a trainee never graduates (off-by-one is the most common bug here).
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Ready")
        give_assignments(db, truck, trainee, count=5)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "walker", "5 assignments should promote to walker"
        assert len(warnings) == 1
        assert warnings[0]["type"] == "trainee_graduated"

    def test_today_assignment_does_not_count(self, db):
        """
        ARRANGE: trainee has 4 past + 1 today assignment (date == target_date).
        ASSERT: not graduated — today's assignment doesn't count.

        WHY: The query filters TruckAssignment.date < target_date. An assignment
        on exactly target_date is excluded. This prevents premature graduation
        before today's dispatch day is actually complete.
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Almost Today")
        give_assignments(db, truck, trainee, count=4)

        # Add one assignment for today (should NOT count)
        ta = TruckAssignment(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=truck.id, date=TARGET)
        db.add(ta); db.commit(); db.refresh(ta)
        db.add(AssignmentMember(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, assignment_id=ta.id, employee_id=trainee.id, role="trainee"))
        db.commit()

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "trainee", "Today's assignment should not count toward graduation"
        assert warnings == []


# ---------------------------------------------------------------------------
# Normal graduation path
# ---------------------------------------------------------------------------

class TestNormalGraduation:
    """
    When a trainee graduates, their role must change and Notifications must
    be written — one for the trainee, one for each privileged staff member.
    """

    def test_graduated_trainee_notified(self, db):
        """
        ASSERT: trainee receives a Notification of type 'trainee_graduated'.
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Graduate")
        give_assignments(db, truck, trainee, count=5)

        graduate_eligible_trainees(db, TARGET)

        notifs = db.query(Notification).filter(
            Notification.employee_id == trainee.id,
            Notification.type == "trainee_graduated",
        ).all()
        assert len(notifs) == 1

    def test_privileged_staff_notified_on_graduation(self, db):
        """
        ARRANGE: 1 management and 1 admin employee in DB.
        ASSERT: each receives a 'trainee_graduated' Notification.

        WHY: Management and admin make staffing decisions. They need to know
        immediately when a trainee is promoted so they can update schedules.
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Graduate")
        manager = make_employee(db, role="management", name="Manager")
        admin   = make_employee(db, role="admin",      name="Admin")
        give_assignments(db, truck, trainee, count=5)

        graduate_eligible_trainees(db, TARGET)

        for emp in [manager, admin]:
            notifs = db.query(Notification).filter(
                Notification.employee_id == emp.id,
                Notification.type == "trainee_graduated",
            ).all()
            assert len(notifs) == 1, f"{emp.name} should receive a graduation Notification"

    def test_warning_message_includes_assignment_count(self, db):
        """
        The warning dict's message should reference the actual assignment count
        so dispatch can verify why the graduation happened.
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Count Check")
        give_assignments(db, truck, trainee, count=6)

        warnings = graduate_eligible_trainees(db, TARGET)

        assert len(warnings) == 1
        assert "6" in warnings[0]["message"], "Warning should mention the assignment count"


# ---------------------------------------------------------------------------
# reset_on_graduation path
# ---------------------------------------------------------------------------

class TestResetOnGraduation:
    """
    Trainees with reset_on_graduation=True should NOT be promoted.
    Their training records are deleted and they remain 'trainee' for the next cycle.
    """

    def test_reset_trainee_stays_trainee(self, db):
        """
        ASSERT: role remains 'trainee' after graduation threshold is met.
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        give_assignments(db, truck, trainee, count=5)

        graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "trainee", "reset_on_graduation trainee must stay 'trainee'"

    def test_reset_deletes_training_records_and_tasks(self, db):
        """
        ARRANGE: trainee has a TrainingRecord with 2 TrainingTasks.
        ASSERT: after reset, both the record and its tasks are deleted.

        WHY: The training injection service checks for an open record to decide
        what phase to inject next. If the record isn't deleted, the trainee
        would resume from where they left off rather than starting Phase 1.
        """
        truck   = make_truck(db)
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        give_assignments(db, truck, trainee, count=5)

        record = make_training_record(db, trainee, trainer)
        make_training_task(db, record)
        make_training_task(db, record)

        graduate_eligible_trainees(db, TARGET)

        remaining_records = db.query(TrainingRecord).filter(TrainingRecord.trainee_id == trainee.id).all()
        remaining_tasks   = db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()

        assert remaining_records == [], "TrainingRecords must be deleted on reset"
        assert remaining_tasks   == [], "TrainingTasks must be deleted on reset"

    def test_reset_emits_reset_notification_not_graduated(self, db):
        """
        ASSERT: Notification type is 'trainee_reset', not 'trainee_graduated'.
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        give_assignments(db, truck, trainee, count=5)

        graduate_eligible_trainees(db, TARGET)

        notifs = db.query(Notification).filter(
            Notification.employee_id == trainee.id,
            Notification.type == "trainee_reset",
        ).all()
        assert len(notifs) == 1, "trainee_reset Notification should be written"

        graduated_notifs = db.query(Notification).filter(
            Notification.employee_id == trainee.id,
            Notification.type == "trainee_graduated",
        ).all()
        assert graduated_notifs == [], "trainee_graduated should NOT be written for reset path"

    def test_reset_warning_type_is_trainee_reset(self, db):
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        give_assignments(db, truck, trainee, count=5)

        warnings = graduate_eligible_trainees(db, TARGET)

        assert len(warnings) == 1
        assert warnings[0]["type"] == "trainee_reset"


# ---------------------------------------------------------------------------
# Continuation request nullification
# ---------------------------------------------------------------------------

class TestContinuationRequests:
    """
    When a trainee graduates (or resets), any open continuation requests
    (status='pending' or 'accepted') must be nullified.
    Requests in other states ('nullified', 'rejected') must not be changed.
    """

    def test_pending_continuation_request_nullified(self, db):
        """
        ASSERT: a 'pending' continuation request becomes 'nullified' after graduation.

        WHY: Once a trainee graduates, they no longer need a trainer-continuation
        pairing. Leaving requests open would create stale approvals that dispatch
        might act on incorrectly.
        """
        truck   = make_truck(db)
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        give_assignments(db, truck, trainee, count=5)
        req = make_continuation_request(db, trainee, trainer, status="pending")

        graduate_eligible_trainees(db, TARGET)

        db.refresh(req)
        assert req.status == "nullified", "Pending continuation request must be nullified"

    def test_accepted_continuation_request_nullified(self, db):
        truck   = make_truck(db)
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        give_assignments(db, truck, trainee, count=5)
        req = make_continuation_request(db, trainee, trainer, status="accepted")

        graduate_eligible_trainees(db, TARGET)

        db.refresh(req)
        assert req.status == "nullified"

    def test_rejected_continuation_request_not_touched(self, db):
        """
        ASSERT: a 'rejected' continuation request stays 'rejected' after graduation.

        WHY: Rejected requests are already resolved — they shouldn't be
        overwritten. Doing so would lose audit information about why it was rejected.
        """
        truck   = make_truck(db)
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        give_assignments(db, truck, trainee, count=5)
        req = make_continuation_request(db, trainee, trainer, status="rejected")

        graduate_eligible_trainees(db, TARGET)

        db.refresh(req)
        assert req.status == "rejected", "Rejected continuation request must not be modified"

    def test_already_nullified_request_not_touched(self, db):
        truck   = make_truck(db)
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        give_assignments(db, truck, trainee, count=5)
        req = make_continuation_request(db, trainee, trainer, status="nullified")

        graduate_eligible_trainees(db, TARGET)

        db.refresh(req)
        assert req.status == "nullified"  # unchanged, already in terminal state


# ---------------------------------------------------------------------------
# Multiple trainees — independent processing
# ---------------------------------------------------------------------------

class TestMultipleTrainees:
    """
    When several trainees exist, each is evaluated independently.
    One graduating does not affect another below threshold.
    """

    def test_only_eligible_trainee_graduates(self, db):
        """
        ARRANGE: 2 trainees — one with 5 assignments, one with 2.
        ASSERT: only the eligible one is promoted.
        """
        truck    = make_truck(db)
        eligible = make_employee(db, role="trainee", name="Ready")
        not_yet  = make_employee(db, role="trainee", name="Not Yet")
        give_assignments(db, truck, eligible, count=5)
        give_assignments(db, truck, not_yet,  count=2)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(eligible)
        db.refresh(not_yet)
        assert eligible.role == "walker"
        assert not_yet.role  == "trainee"
        assert len(warnings) == 1

    def test_two_eligible_trainees_both_graduate(self, db):
        """
        ARRANGE: 2 trainees both with 5+ assignments.
        ASSERT: both become walker, 2 warnings returned.
        """
        truck    = make_truck(db)
        trainee1 = make_employee(db, role="trainee", name="First")
        trainee2 = make_employee(db, role="trainee", name="Second")
        give_assignments(db, truck, trainee1, count=5)
        give_assignments(db, truck, trainee2, count=5)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee1)
        db.refresh(trainee2)
        assert trainee1.role == "walker"
        assert trainee2.role == "walker"
        assert len(warnings) == 2


# ---------------------------------------------------------------------------
# Inactive trainees excluded
# ---------------------------------------------------------------------------

class TestInactiveExclusion:
    """
    Inactive employees (is_active=False) must never be graduated, even if
    their assignment history would qualify them.
    """

    def test_inactive_trainee_not_graduated(self, db):
        """
        WHY: An inactive employee is off the system — promoting them would
        be a data integrity error and could surface them on dispatch boards.
        """
        truck   = make_truck(db)
        trainee = make_employee(db, role="trainee", name="Inactive")
        trainee.is_active = False
        db.commit()
        give_assignments(db, truck, trainee, count=7)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "trainee", "Inactive trainee must not be promoted"
        assert warnings == []


# ---------------------------------------------------------------------------
# No trainees — empty run
# ---------------------------------------------------------------------------

class TestEmptyRun:
    def test_no_trainees_returns_empty_warnings(self, db):
        """
        With no trainees in the DB, the service should return [] without errors.
        """
        warnings = graduate_eligible_trainees(db, TARGET)
        assert warnings == []
