import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.graduation_quiz import GraduationQuiz
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.models.training import TrainingRecord, TrainingTask
from app.services.notify import write_notification
from app.tasks.discord_delivery import send_discord

logger = logging.getLogger(__name__)


def graduate_eligible_trainees(db: Session, target_date, company_id, cfg=None):
    """
    Check all active trainees for a passed graduation quiz (status='passed').

    Graduation gate: the trainee's most recent GraduationQuiz has passed=True.
    Assignment count threshold is removed — Phase 4 observation already implies
    sufficient dispatch days; the quiz is the explicit sign-off.

    Graduates eligible trainees to walker.

    (ADR-487 D11c removed `reset_on_graduation`: it existed for one named
    simulation account, and ADR-047 D2 — which added it — says so three times.
    Graduation is now unconditional: pass the quiz, become a walker.)

    Nullifies open continuation requests and fires Notifications to
    management/admin/dispatch on any outcome.

    Returns a list of warning dicts for the dispatch run summary.
    """
    warnings = []
    _graduation_dms: list[tuple[str, str]] = []

    # Walker track only: trainee -> walker. ADR-264 makes driver_trainee -> driver a
    # PARALLEL track with its own promotion target, not a case to fold in here; that
    # ADR is proposed and unimplemented, so driver trainees are counted and warned
    # about below rather than silently passed over.
    trainees = db.query(Employee).filter(
        Employee.role == "trainee",
        Employee.is_active == True,
        Employee.company_id == company_id,
    ).all()

    # ADR-264 D10 (revised 2026-08-22) — driver trainees are NOT promoted here.
    # There is no driver quiz, and promotion is an explicit dispatch/management
    # approval rather than an automatic consequence of a score. This surfaces
    # who is waiting on that decision; the role change happens on the employee
    # page.
    #
    # Repeated every dispatch run until someone acts, which is the "repeated on
    # the next assignment if it is not settled" rule.
    from app.services.driver_promotion import (
        driver_trainees_awaiting_promotion, promotion_warning,
    )

    for entry in driver_trainees_awaiting_promotion(db, target_date, company_id, cfg=cfg):
        warnings.append(promotion_warning(entry))
        logger.info(
            "graduate_trainees: driver_trainee=%s awaiting promotion verdict=%s date=%s",
            entry["employee_id"], entry["verdict"], target_date,
        )

    recipients = db.query(Employee).filter(
        Employee.role.in_(["management", "admin", "dispatch"]),
        Employee.is_active == True,
        Employee.company_id == company_id,
    ).all()

    for trainee in trainees:
        # Check for a passed graduation quiz — most recent attempt wins.
        latest_quiz = (
            db.query(GraduationQuiz)
            .filter(
                GraduationQuiz.trainee_id == trainee.id,
                GraduationQuiz.company_id == trainee.company_id,
                GraduationQuiz.passed == True,
            )
            .order_by(GraduationQuiz.manager_reviewed_at.desc())
            .first()
        )

        if latest_quiz is None:
            continue

        trainee.role = "walker"
        message_mgmt = (
            f"{trainee.name} passed the graduation quiz "
            f"and was automatically promoted from Trainee to Walker on {target_date}."
        )
        message_self = (
            f"Congratulations! You passed the graduation quiz "
            f"and have been promoted to Walker effective {target_date}."
        )
        outcome_type = "trainee_graduated"

        for recipient in recipients:
            write_notification(
                db,
                company_id=trainee.company_id,
                employee_id=recipient.id,
                type=outcome_type,
                message=message_mgmt,
            )

        write_notification(
            db,
            company_id=trainee.company_id,
            employee_id=trainee.id,
            type=outcome_type,
            message=message_self,
        )

        open_requests = db.query(TrainerContinuationRequest).filter(
            TrainerContinuationRequest.trainee_id == trainee.id,
            TrainerContinuationRequest.status.in_(["pending", "accepted"]),
        ).all()
        for req in open_requests:
            req.status = "nullified"
            req.resolved_at = datetime.now(timezone.utc)

        warnings.append({
            "type": outcome_type,
            "message": (
                f"Trainee {trainee.name} passed the graduation quiz "
                f"— automatically promoted to Walker."
            ),
        })

        if trainee.discord_id:
            dm_message = (
                f"Congratulations **{trainee.name}**! You passed the graduation quiz "
                f"and have been **promoted to Walker** effective {target_date}.\n\n"
                f"As a Walker you can now:\n"
                f"• Set favorite crew members (trainers & other walkers)\n"
                f"• Block crew members you'd prefer not to work with\n"
                f"• Submit truck reassignment requests\n\n"
                f"Welcome to the team!"
            )
            _graduation_dms.append((trainee.discord_id, dm_message))

    if warnings:
        db.commit()
        for discord_id, dm_msg in _graduation_dms:
            _send_graduation_dm(discord_id, dm_msg)

    return warnings


def _send_graduation_dm(discord_id: str, message: str) -> None:
    # ADR-487 D7: a Celery task, not a daemon thread. This one ran inside a
    # nightly task, where a dropped thread at container stop was invisible.
    send_discord.delay("dm", {"discord_id": discord_id, "message": message})
