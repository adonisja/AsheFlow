from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.graduation_quiz import GraduationQuiz
from app.models.notification import Notification
from app.models.training import TrainingCurriculum, TrainingRecord, TrainingTask


def generate_quiz_remediation(
    db: Session,
    quiz: GraduationQuiz,
    company_id,
) -> TrainingRecord:
    """
    Create a Phase 6 remediation TrainingRecord after a failed graduation quiz.

    Only covers the weak_topics from the failed quiz — targeted remediation,
    not a full restart. The next dispatch day after this record is closed will
    inject a new Phase 5 quiz day (training_injection handles this via the
    current_day_number >= 6 and phase_closed branch).

    Caller is responsible for commit.
    """
    weak_topics: list[str] = quiz.weak_topics or []

    # Determine attempt number for the new remediation record (Phase 6 base + attempts)
    # First quiz fail → Phase 6, second → Phase 7, etc. This keeps day_number meaningful
    # for internal records while never surfacing the number publicly.
    existing_remediation_count = db.query(TrainingRecord).filter(
        TrainingRecord.trainee_id == quiz.trainee_id,
        TrainingRecord.current_day_number >= 6,
        TrainingRecord.company_id == company_id,
    ).count()
    remediation_phase = 6 + existing_remediation_count

    remediation = TrainingRecord(
        company_id=company_id,
        trainee_id=quiz.trainee_id,
        trainer_id=None,           # dispatch assigns trainer at next dispatch run
        record_date=datetime.now(timezone.utc).date(),
        current_day_number=remediation_phase,
        phase_closed=False,
        extended=False,
    )
    db.add(remediation)
    db.flush()

    # Pull curriculum descriptions for weak topics
    curriculum_map = {
        item.topic_title: item
        for item in db.query(TrainingCurriculum).filter(
            TrainingCurriculum.topic_title.in_(weak_topics),
            TrainingCurriculum.company_id == company_id,
        ).all()
    }

    for topic_title in weak_topics:
        curriculum_item = curriculum_map.get(topic_title)
        task = TrainingTask(
            company_id=company_id,
            training_record_id=remediation.id,
            topic_title=topic_title,
            description=curriculum_item.description if curriculum_item else None,
            record_type="coverage",
            is_mandatory=True,
            is_training_debt=False,
        )
        db.add(task)

    # Notify management/admin so they can plan the next training day
    trainee = db.query(Employee).filter(Employee.id == quiz.trainee_id).first()
    trainee_name = trainee.name if trainee else str(quiz.trainee_id)

    topic_preview = ", ".join(weak_topics[:5])
    if len(weak_topics) > 5:
        topic_preview += f" (+{len(weak_topics) - 5} more)"

    message = (
        f"Graduation quiz failed for {trainee_name} "
        f"(attempt {quiz.attempt_number}). "
        f"A targeted remediation session has been scheduled covering: {topic_preview}. "
        f"They will be assigned a trainer on their next dispatch day."
    )

    recipients = db.query(Employee).filter(
        Employee.role.in_(["management", "admin"]),
        Employee.is_active == True,
        Employee.company_id == company_id,
    ).all()
    for recipient in recipients:
        db.add(Notification(
            company_id=company_id,
            employee_id=recipient.id,
            type="quiz_remediation_scheduled",
            message=message,
        ))

    db.flush()
    return remediation
