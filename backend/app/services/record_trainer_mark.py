from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.notification import Notification
from app.models.trainer_mark import TrainerMark
from app.models.training import TrainingRecord, TrainingTask

# How many distinct trainees a trainer must have marks against before
# the underperforming trainer notification fires to management.
UNDERPERFORMING_MARK_THRESHOLD = 3


def record_trainer_mark(
    db: Session,
    training_record_id: str,
    reason: str,
) -> TrainerMark | None:
    """
    Issue a TrainerMark when a phase fails to close by midnight.

    Attribution rules (ADR-046 §3):
    - If the record has ANY inherited debt tasks (is_training_debt = True),
      the failure is not this trainer's fault — return None (no mark issued).
    - Otherwise: issue a mark against the trainer on the record, flagged as
      debt_originated = True (this trainer started a new debt chain).
    - After issuing, check if this trainer now has marks across 3+ distinct
      trainees. If so, fire an underperforming trainer notification to all
      active management and admin employees.

    Args:
        db: Database session. Caller is responsible for commit.
        training_record_id: The record that failed to close.
        reason: "phase_not_closed" or "submitted_late".

    Returns:
        The created TrainerMark, or None if no mark was warranted.
    """
    record = db.query(TrainingRecord).filter(
        TrainingRecord.id == training_record_id
    ).first()

    if not record or not record.trainer_id:
        return None

    # If any inherited debt tasks exist, this trainer is not at fault.
    has_inherited_debt = db.query(TrainingTask).filter(
        TrainingTask.training_record_id == training_record_id,
        TrainingTask.is_training_debt == True,
    ).first() is not None

    if has_inherited_debt:
        return None

    mark = TrainerMark(
        trainer_id=record.trainer_id,
        training_record_id=record.id,
        trainee_id=record.trainee_id,
        reason=reason,
        debt_originated=True,
    )
    db.add(mark)
    db.flush()  # get mark.id without full commit

    # Check underperforming threshold: distinct trainees this trainer has marks for.
    distinct_trainees = (
        db.query(TrainerMark.trainee_id)
        .filter(TrainerMark.trainer_id == record.trainer_id)
        .distinct()
        .count()
    )

    if distinct_trainees >= UNDERPERFORMING_MARK_THRESHOLD:
        trainer = db.query(Employee).filter(Employee.id == record.trainer_id).first()
        trainer_name = trainer.name if trainer else "Unknown trainer"

        notif_message = (
            f"Underperforming trainer alert: {trainer_name} has failed to close "
            f"training phases for {distinct_trainees} different trainees. "
            f"Review their training records for patterns."
        )
        _notify_management(db, notif_message, notification_type="underperforming_trainer")

    return mark


def record_exemplary_note(
    db: Session,
    training_record_id: str,
) -> None:
    """
    Fire a management notification when a trainer clears inherited debt AND
    closes their own phase in the same session.

    Called by the task completion endpoint after phase_closed is set to True,
    when the record had inherited debt tasks that are now all complete.

    Args:
        db: Database session. Caller is responsible for commit.
        training_record_id: The record being closed.
    """
    record = db.query(TrainingRecord).filter(
        TrainingRecord.id == training_record_id
    ).first()
    if not record or not record.trainer_id:
        return

    trainer = db.query(Employee).filter(Employee.id == record.trainer_id).first()
    trainer_name = trainer.name if trainer else "Unknown trainer"

    trainee = db.query(Employee).filter(Employee.id == record.trainee_id).first()
    trainee_name = trainee.name if trainee else "Unknown trainee"

    notif_message = (
        f"Exemplary trainer: {trainer_name} cleared inherited training debt and "
        f"completed Phase {record.current_day_number} for {trainee_name} in a single session."
    )
    _notify_management(db, notif_message, notification_type="exemplary_trainer")


def _notify_management(db: Session, message: str, notification_type: str) -> None:
    """Fan out a notification to all active management and admin employees."""
    recipients = db.query(Employee).filter(
        Employee.role.in_(["management", "admin"]),
        Employee.is_active == True,
    ).all()
    for recipient in recipients:
        db.add(Notification(
            employee_id=recipient.id,
            type=notification_type,
            message=message,
        ))
