from sqlalchemy.orm import Session

from app.models.training import TrainingRecord, TrainingTask


def check_phase_gate(
    db: Session,
    training_record_id: str,
) -> tuple[bool, list[str]]:
    """
    Check whether all mandatory coverage tasks on a training record are complete.

    Called before a trainer can mark any topic complete on the NEXT phase's record.
    The gate enforces: all mandatory Phase N tasks must be done before Phase N+1
    topics can be started. Under normal operation this prevents debt entirely —
    debt only arises if management force-unlocks a phase.

    Also called when a trainer attempts to submit/close a record, to determine
    whether phase_closed can be set to True.

    Args:
        db: Database session.
        training_record_id: The TrainingRecord whose gate is being checked.

    Returns:
        (True, [])                    — gate is open, all mandatory tasks complete
        (False, [list of titles])     — gate is blocked, returns blocking topic titles
    """
    blocking = db.query(TrainingTask).filter(
        TrainingTask.training_record_id == training_record_id,
        TrainingTask.is_mandatory == True,
        TrainingTask.is_completed == False,
        TrainingTask.record_type == "coverage",  # only coverage tasks gate the phase
    ).all()

    if blocking:
        return False, [t.topic_title for t in blocking]
    return True, []


def get_open_record_for_trainee(db: Session, trainee_id: str) -> TrainingRecord | None:
    """
    Return the current open (not locked, not phase_closed) TrainingRecord
    for the given trainee, if one exists.

    Used by routers to find the active record without requiring the caller
    to supply a record ID.
    """
    return db.query(TrainingRecord).filter(
        TrainingRecord.trainee_id == trainee_id,
        TrainingRecord.is_locked == False,
    ).order_by(TrainingRecord.record_date.desc()).first()
