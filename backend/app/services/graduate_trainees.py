import os
import logging
import requests
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.graduation_quiz import GraduationQuiz
from app.models.notification import Notification
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.models.training import TrainingRecord, TrainingTask

logger = logging.getLogger(__name__)


def graduate_eligible_trainees(db: Session, target_date, company_id, cfg=None):
    """
    Check all active trainees for a passed graduation quiz (status='passed').

    Graduation gate: the trainee's most recent GraduationQuiz has passed=True.
    Assignment count threshold is removed — Phase 4 observation already implies
    sufficient dispatch days; the quiz is the explicit sign-off.

    Graduates eligible trainees to walker. If reset_on_graduation is True,
    the training cycle is reset to Phase 1 instead (simulation accounts).

    Nullifies open continuation requests and fires Notifications to
    management/admin/dispatch on any outcome.

    Returns a list of warning dicts for the dispatch run summary.
    """
    warnings = []
    _graduation_dms: list[tuple[str, str]] = []

    trainees = db.query(Employee).filter(
        Employee.role == "trainee",
        Employee.is_active == True,
        Employee.company_id == company_id,
    ).all()

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

        if trainee.reset_on_graduation:
            # Simulation / demo reset path — wipe training records and restart
            training_records = db.query(TrainingRecord).filter(
                TrainingRecord.trainee_id == trainee.id,
            ).all()
            for rec in training_records:
                db.query(TrainingTask).filter(
                    TrainingTask.training_record_id == rec.id,
                ).delete(synchronize_session=False)
                db.delete(rec)

            # Also reset graduation quiz rows so the cycle can repeat cleanly
            db.query(GraduationQuiz).filter(
                GraduationQuiz.trainee_id == trainee.id,
            ).delete(synchronize_session=False)

            message_mgmt = (
                f"{trainee.name} passed the graduation quiz. "
                f"reset_on_graduation=True — training cycle reset to Phase 1 (not promoted to walker)."
            )
            message_self = (
                f"You passed the graduation quiz! "
                f"Your training cycle has been reset to Phase 1 for the next round."
            )
            outcome_type = "trainee_reset"
        else:
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
            db.add(Notification(
                company_id=trainee.company_id,
                employee_id=recipient.id,
                type=outcome_type,
                message=message_mgmt,
            ))

        db.add(Notification(
            company_id=trainee.company_id,
            employee_id=trainee.id,
            type=outcome_type,
            message=message_self,
        ))

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
                + ("— training cycle reset to Phase 1."
                   if trainee.reset_on_graduation
                   else "— automatically promoted to Walker.")
            ),
        })

        if trainee.discord_id:
            if trainee.reset_on_graduation:
                dm_message = (
                    f"Hi **{trainee.name}**! You passed the graduation quiz. "
                    f"Your training cycle has been reset to Phase 1 — a trainer will be assigned for your next round."
                )
            else:
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
    import threading

    def _fire():
        bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
        secret = os.environ.get("INTERNAL_SECRET", "")
        try:
            requests.post(
                f"{bot_url}/internal/dm",
                json={"discord_id": discord_id, "message": message},
                headers={"X-Internal-Secret": secret},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Graduation DM failed for discord_id=%s: %s", discord_id, exc)

    threading.Thread(target=_fire, daemon=True).start()
