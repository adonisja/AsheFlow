"""
Tests for graduate_eligible_trainees.

HOW graduate_eligible_trainees WORKS (summary):
1. Query all active trainees.
2. For each trainee, look for a GraduationQuiz row where passed=True
   (most recent manager_reviewed_at wins). If none exists: skip.
3. If reset_on_graduation=True: delete all TrainingRecord + TrainingTask rows
   and all GraduationQuiz rows for this trainee, emit a reset Notification.
   Role stays 'trainee'.
4. Otherwise: promote trainee.role → 'walker', emit Notifications to all
   management/admin/dispatch staff and to the trainee themselves.
5. Nullify any open (pending/accepted) continuation requests for the trainee.
6. After all trainees processed: db.commit() once, then fire Discord DMs.
7. Return a list of warning dicts describing each graduation/reset.

WHAT WE'RE VERIFYING:
- Trainees with no passed quiz are not graduated.
- Trainees with a passed quiz (passed=True) are graduated.
- Trainees with a failed quiz (passed=False) are not graduated.
- Graduation promotes role to 'walker' and writes Notification rows.
- reset_on_graduation=True keeps role as 'trainee', resets training records.
- Open continuation requests are nullified on graduation.
- Continuation requests in other states (nullified, rejected) are not touched.
- Multiple trainees are processed independently in one call.
- Inactive trainees are excluded regardless of quiz state.

NOTE ON SQLite vs PostgreSQL:
The conftest db fixture uses SQLite in-memory. graduate_eligible_trainees uses
only standard SQL for all GraduationQuiz queries; SQLite is fine.
graduation_quizzes is added to DISPATCH_TABLES as a SQLite-compatible mirror
(JSONB → JSON) since the ORM model uses the PostgreSQL-specific JSONB type.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.services.graduate_trainees import graduate_eligible_trainees
from app.models.employee import Employee
from app.models.graduation_quiz import GraduationQuiz
from tests.conftest import SEED_COMPANY_ID
from app.models.notification import Notification
from app.models.training import TrainingRecord, TrainingTask
from app.models.trainer_continuation_request import TrainerContinuationRequest

from tests.conftest import make_employee, make_graduation_quiz


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET = date.today()


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
# Quiz gate — passed vs no quiz vs failed
# ---------------------------------------------------------------------------

class TestQuizGate:
    """
    The graduation gate is a passed GraduationQuiz row (passed=True).
    No quiz or a failed quiz → no graduation.
    """

    def test_no_quiz_does_not_graduate(self, db):
        """
        ARRANGE: active trainee with no GraduationQuiz rows at all.
        ASSERT: role stays 'trainee', no warnings, no Notifications.

        WHY: The gate requires passed=True. Absence of any quiz means the
        trainee has not completed the final assessment.
        """
        trainee = make_employee(db, role="trainee", name="No Quiz Yet")

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "trainee", "No quiz → should not graduate"
        assert warnings == []
        notifs = db.query(Notification).filter(Notification.employee_id == trainee.id).all()
        assert notifs == [], "No Notifications written when no quiz exists"

    def test_failed_quiz_does_not_graduate(self, db):
        """
        ARRANGE: trainee has a quiz with passed=False.
        ASSERT: not graduated.

        WHY: Only passed=True triggers graduation. A failed quiz means the
        trainee is scheduled for remediation, not promotion.
        """
        trainee = make_employee(db, role="trainee", name="Failed Quiz")
        make_graduation_quiz(db, trainee, passed=False)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "trainee", "Failed quiz → should not graduate"
        assert warnings == []

    def test_passed_quiz_graduates(self, db):
        """
        ARRANGE: trainee has a quiz with passed=True.
        ASSERT: role becomes 'walker', 1 warning returned.

        WHY: A passed quiz is the explicit sign-off for graduation — it means
        the manager confirmed the trainee demonstrated sufficient knowledge.
        """
        trainee = make_employee(db, role="trainee", name="Ready")
        make_graduation_quiz(db, trainee, passed=True)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "walker", "Passed quiz should promote to walker"
        assert len(warnings) == 1
        assert warnings[0]["type"] == "trainee_graduated"

    def test_most_recent_quiz_wins(self, db):
        """
        ARRANGE: trainee has an old failed quiz and a newer passed quiz.
        ASSERT: graduated (most recent passed quiz wins).

        WHY: A trainee may fail and retake. The latest outcome is what matters.
        The service orders by manager_reviewed_at DESC and takes first().
        """
        from datetime import datetime, timezone, timedelta as td
        trainee = make_employee(db, role="trainee", name="Retry")
        older = datetime.now(timezone.utc) - td(days=2)
        newer = datetime.now(timezone.utc) - td(days=1)
        make_graduation_quiz(db, trainee, passed=False, reviewed_at=older)
        make_graduation_quiz(db, trainee, passed=True,  reviewed_at=newer)

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(trainee)
        assert trainee.role == "walker"
        assert len(warnings) == 1


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
        trainee = make_employee(db, role="trainee", name="Graduate")
        make_graduation_quiz(db, trainee, passed=True)

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
        trainee = make_employee(db, role="trainee", name="Graduate")
        manager = make_employee(db, role="management", name="Manager")
        admin   = make_employee(db, role="admin",      name="Admin")
        make_graduation_quiz(db, trainee, passed=True)

        graduate_eligible_trainees(db, TARGET)

        for emp in [manager, admin]:
            notifs = db.query(Notification).filter(
                Notification.employee_id == emp.id,
                Notification.type == "trainee_graduated",
            ).all()
            assert len(notifs) == 1, f"{emp.name} should receive a graduation Notification"

    def test_warning_message_references_quiz(self, db):
        """
        The warning dict's message should mention the graduation quiz
        so dispatch can identify the reason for the promotion.
        """
        trainee = make_employee(db, role="trainee", name="Count Check")
        make_graduation_quiz(db, trainee, passed=True)

        warnings = graduate_eligible_trainees(db, TARGET)

        assert len(warnings) == 1
        assert "graduation quiz" in warnings[0]["message"].lower(), \
            "Warning should reference the graduation quiz"


# ---------------------------------------------------------------------------
# reset_on_graduation path
# ---------------------------------------------------------------------------

class TestResetOnGraduation:
    """
    Trainees with reset_on_graduation=True should NOT be promoted.
    Their training records and quiz rows are deleted; they remain 'trainee' for the next cycle.
    """

    def test_reset_trainee_stays_trainee(self, db):
        """
        ASSERT: role remains 'trainee' after a passed quiz when reset_on_graduation=True.
        """
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        make_graduation_quiz(db, trainee, passed=True)

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
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        make_graduation_quiz(db, trainee, passed=True)

        record = make_training_record(db, trainee, trainer)
        make_training_task(db, record)
        make_training_task(db, record)

        graduate_eligible_trainees(db, TARGET)

        remaining_records = db.query(TrainingRecord).filter(TrainingRecord.trainee_id == trainee.id).all()
        remaining_tasks   = db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()

        assert remaining_records == [], "TrainingRecords must be deleted on reset"
        assert remaining_tasks   == [], "TrainingTasks must be deleted on reset"

    def test_reset_deletes_graduation_quiz_rows(self, db):
        """
        ASSERT: GraduationQuiz rows are deleted on reset so the next cycle
        starts clean — without a stale passed=True row triggering graduation again.
        """
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        make_graduation_quiz(db, trainee, passed=True)

        graduate_eligible_trainees(db, TARGET)

        remaining = db.query(GraduationQuiz).filter(
            GraduationQuiz.trainee_id == trainee.id,
        ).all()
        assert remaining == [], "GraduationQuiz rows must be deleted on reset"

    def test_reset_emits_reset_notification_not_graduated(self, db):
        """
        ASSERT: Notification type is 'trainee_reset', not 'trainee_graduated'.
        """
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        make_graduation_quiz(db, trainee, passed=True)

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
        trainee = make_employee(db, role="trainee", name="Timmy Reset")
        trainee.reset_on_graduation = True
        db.commit()
        make_graduation_quiz(db, trainee, passed=True)

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
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        make_graduation_quiz(db, trainee, passed=True)
        req = make_continuation_request(db, trainee, trainer, status="pending")

        graduate_eligible_trainees(db, TARGET)

        db.refresh(req)
        assert req.status == "nullified", "Pending continuation request must be nullified"

    def test_accepted_continuation_request_nullified(self, db):
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        make_graduation_quiz(db, trainee, passed=True)
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
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        make_graduation_quiz(db, trainee, passed=True)
        req = make_continuation_request(db, trainee, trainer, status="rejected")

        graduate_eligible_trainees(db, TARGET)

        db.refresh(req)
        assert req.status == "rejected", "Rejected continuation request must not be modified"

    def test_already_nullified_request_not_touched(self, db):
        trainer = make_employee(db, role="trainer", name="Trainer")
        trainee = make_employee(db, role="trainee", name="Graduate")
        make_graduation_quiz(db, trainee, passed=True)
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
    One graduating does not affect another without a passed quiz.
    """

    def test_only_eligible_trainee_graduates(self, db):
        """
        ARRANGE: 2 trainees — one with a passed quiz, one with no quiz.
        ASSERT: only the one with a passed quiz is promoted.
        """
        eligible = make_employee(db, role="trainee", name="Ready")
        not_yet  = make_employee(db, role="trainee", name="Not Yet")
        make_graduation_quiz(db, eligible, passed=True)
        # not_yet has no quiz at all

        warnings = graduate_eligible_trainees(db, TARGET)

        db.refresh(eligible)
        db.refresh(not_yet)
        assert eligible.role == "walker"
        assert not_yet.role  == "trainee"
        assert len(warnings) == 1

    def test_two_eligible_trainees_both_graduate(self, db):
        """
        ARRANGE: 2 trainees both with passed quizzes.
        ASSERT: both become walker, 2 warnings returned.
        """
        trainee1 = make_employee(db, role="trainee", name="First")
        trainee2 = make_employee(db, role="trainee", name="Second")
        make_graduation_quiz(db, trainee1, passed=True)
        make_graduation_quiz(db, trainee2, passed=True)

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
    they have a passed quiz.
    """

    def test_inactive_trainee_not_graduated(self, db):
        """
        WHY: An inactive employee is off the system — promoting them would
        be a data integrity error and could surface them on dispatch boards.
        """
        trainee = make_employee(db, role="trainee", name="Inactive")
        trainee.is_active = False
        db.commit()
        make_graduation_quiz(db, trainee, passed=True)

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
