from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.notification import Notification
from app.models.training import TrainingCurriculum, TrainingRecord, TrainingTask

PASS_THRESHOLD = 90.0  # minimum score percentage to pass Phase 4


def score_phase4(db: Session, training_record_id: str) -> dict:
    """
    Compute the Phase 4 observation score from completed demonstration tasks.

    Scoring rules (ADR-046 §6):
    - Score = (mandatory observation items passed / total mandatory observation items) × 100
    - Pass = score >= 90.0 AND every mandatory item individually passed
    - A 90% score with even one mandatory item failed does NOT pass

    Args:
        db: Database session.
        training_record_id: The Phase 4 TrainingRecord to score.

    Returns:
        {
            "score": float (0.0–100.0),
            "passed": bool,
            "failed_mandatory_topics": [str],   # titles of failed mandatory items
            "total_mandatory": int,
            "passed_mandatory": int,
        }
    """
    tasks = db.query(TrainingTask).filter(
        TrainingTask.training_record_id == training_record_id,
        TrainingTask.record_type == "demonstration",
    ).all()

    mandatory = [t for t in tasks if t.is_mandatory]
    passed_mandatory = [t for t in mandatory if t.is_completed]
    failed_mandatory = [t for t in mandatory if not t.is_completed]

    total = len(mandatory)
    n_passed = len(passed_mandatory)

    score = (n_passed / total * 100.0) if total > 0 else 0.0
    all_mandatory_passed = len(failed_mandatory) == 0
    passed = score >= PASS_THRESHOLD and all_mandatory_passed

    return {
        "score": round(score, 2),
        "passed": passed,
        "failed_mandatory_topics": [t.topic_title for t in failed_mandatory],
        "total_mandatory": total,
        "passed_mandatory": n_passed,
    }


def apply_phase4_result(
    db: Session,
    record: TrainingRecord,
    score_result: dict,
    observation_notes: str | None = None,
) -> TrainingRecord:
    """
    Write the Phase 4 score result back to the TrainingRecord and, on fail,
    generate a Phase 5 remediation record containing only the failed topics.

    Args:
        db: Database session. Caller is responsible for commit.
        record: The Phase 4 TrainingRecord ORM object.
        score_result: Dict returned by score_phase4().
        observation_notes: Optional free-form trainer commentary.

    Returns:
        The updated TrainingRecord.
    """
    record.passed = score_result["passed"]
    record.score = score_result["score"]
    record.observation_notes = observation_notes
    record.phase_closed = True
    record.phase_closed_at = datetime.now(timezone.utc)

    if not score_result["passed"]:
        record.extended = True
        _generate_remediation_record(db, record, score_result["failed_mandatory_topics"])
        _notify_management_phase4_fail(db, record, score_result)

    db.flush()
    return record


def _generate_remediation_record(
    db: Session,
    original_record: TrainingRecord,
    failed_topics: list[str],
) -> TrainingRecord:
    """
    Create a Phase 5 remediation TrainingRecord containing only the topics
    that failed in the Phase 4 observation. This is targeted remediation —
    not a full restart.
    """
    remediation = TrainingRecord(
        trainee_id=original_record.trainee_id,
        trainer_id=original_record.trainer_id,  # same trainer if available; dispatch may override
        record_date=original_record.record_date,  # same date placeholder; updated at next dispatch
        current_day_number=5,  # Phase 5 = remediation only
        phase_closed=False,
        extended=False,
    )
    db.add(remediation)
    db.flush()

    # Pull curriculum items for failed topics to get full descriptions
    curriculum_map = {}
    curriculum_items = db.query(TrainingCurriculum).filter(
        TrainingCurriculum.topic_title.in_(failed_topics)
    ).all()
    for item in curriculum_items:
        curriculum_map[item.topic_title] = item

    for topic_title in failed_topics:
        curriculum_item = curriculum_map.get(topic_title)
        task = TrainingTask(
            training_record_id=remediation.id,
            topic_title=topic_title,
            description=curriculum_item.description if curriculum_item else None,
            record_type="coverage",   # remediation = re-teach, not observe
            is_mandatory=True,
            is_training_debt=False,   # remediation is a fresh session, not debt
        )
        db.add(task)

    return remediation


def _notify_management_phase4_fail(
    db: Session,
    record: TrainingRecord,
    score_result: dict,
) -> None:
    """Notify management when a DA fails Phase 4."""
    trainee = db.query(Employee).filter(Employee.id == record.trainee_id).first()
    trainee_name = trainee.name if trainee else "Unknown trainee"

    failed_list = ", ".join(score_result["failed_mandatory_topics"][:5])
    if len(score_result["failed_mandatory_topics"]) > 5:
        failed_list += f" (+{len(score_result['failed_mandatory_topics']) - 5} more)"

    message = (
        f"Phase 4 observation failed for {trainee_name}. "
        f"Score: {score_result['score']:.1f}% "
        f"({score_result['passed_mandatory']}/{score_result['total_mandatory']} mandatory items passed). "
        f"Failed topics: {failed_list}. "
        f"A remediation session (Phase 5) has been generated."
    )

    recipients = db.query(Employee).filter(
        Employee.role.in_(["management", "admin"]),
        Employee.is_active == True,
    ).all()
    for recipient in recipients:
        db.add(Notification(
            employee_id=recipient.id,
            type="phase4_failed",
            message=message,
        ))
