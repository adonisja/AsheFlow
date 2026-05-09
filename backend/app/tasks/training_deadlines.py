from datetime import date, timedelta

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.trainer_mark import TrainerMark
from app.models.training import TrainingRecord
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.services.record_trainer_mark import record_trainer_mark
from app.services.company_config import get_company_config


@celery_app.task(name="app.tasks.training_deadlines.check_training_submissions")
def check_training_submissions() -> dict:
    """
    Runs at 00:01 AM daily. Finds all training records from yesterday that were
    not submitted before midnight and takes the following actions:

    1. Verifies the trainee was actually dispatched yesterday (skip non-dispatch days —
       missed days pause training without penalty).
    2. Soft-locks the record (is_locked = True) — management must reopen for late submission.
    3. Calls record_trainer_mark() — issues a mark to the trainer if no inherited debt
       was present on the record (ADR-046 §3).
    4. Notifies all active management and admin employees.

    Returns a summary dict for Celery task result inspection.
    """
    yesterday = date.today() - timedelta(days=1)
    flagged = 0
    skipped_not_dispatched = 0
    marks_issued = 0

    db = SessionLocal()
    try:
        unsubmitted = db.query(TrainingRecord).filter(
            TrainingRecord.record_date == yesterday,
            TrainingRecord.submitted_at == None,
            TrainingRecord.is_locked == False,
        ).all()

        for record in unsubmitted:
            # Confirm the trainee was actually dispatched yesterday.
            # Check AssignmentMember for this employee on yesterday's assignments.
            was_dispatched = db.query(AssignmentMember).join(
                TruckAssignment,
                AssignmentMember.assignment_id == TruckAssignment.id,
            ).filter(
                AssignmentMember.employee_id == record.trainee_id,
                TruckAssignment.date == yesterday,
            ).first() is not None

            if not was_dispatched:
                # Missed day — no penalty, training just paused
                skipped_not_dispatched += 1
                continue

            # Soft-lock the record
            record.is_locked = True

            # Issue trainer mark if warranted
            cfg = get_company_config(db, record.company_id)
            mark = record_trainer_mark(
                db, str(record.id), reason="phase_not_closed",
                underperforming_threshold=cfg.underperforming_trainer_threshold,
            )
            if mark:
                marks_issued += 1

            # Notify management
            trainee = db.query(Employee).filter(Employee.id == record.trainee_id).first()
            trainer = db.query(Employee).filter(Employee.id == record.trainer_id).first()
            trainee_name = trainee.name if trainee else "Unknown trainee"
            trainer_name = trainer.name if trainer else "Unknown trainer"

            message = (
                f"Training record not submitted: Phase {record.current_day_number} "
                f"for {trainee_name} (trainer: {trainer_name}) was not submitted by midnight. "
                f"The record has been locked. Reopen it from the training management view."
            )
            recipients = db.query(Employee).filter(
                Employee.role.in_(["management", "admin"]),
                Employee.is_active == True,
            ).all()
            for recipient in recipients:
                db.add(Notification(
                    employee_id=recipient.id,
                    type="training_record_unsubmitted",
                    message=message,
                ))

            flagged += 1

        db.commit()

    finally:
        db.close()

    return {
        "date_checked": str(yesterday),
        "flagged": flagged,
        "skipped_not_dispatched": skipped_not_dispatched,
        "marks_issued": marks_issued,
    }
