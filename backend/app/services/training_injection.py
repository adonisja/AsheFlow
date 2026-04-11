from datetime import date, datetime, timezone
from typing import Dict, List
from sqlalchemy.orm import Session
from app.models.training import TrainingRecord, TrainingTask, TrainingCurriculum
from app.models.employee import Employee
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.services.constants import DEBT_ESCALATION_THRESHOLD

def inject_curriculum(db: Session, target_date: date, assigned_crews: Dict[str, List[Dict]]) -> None:
    """
    Hook to autogenerate daily training records for trainees based on the curriculum.
    Rolls over training debt from previous uncompleted tasks.
    """
    # 1. Identify all trainees that are assigned today
    trainees_in_crews = []
    for truck_id, crew in assigned_crews.items():
        trainer_id = None
        # Find trainer on this truck
        for member in crew:
            if member["role"] == "trainer":
                trainer_id = member["id"]
                break
        
        for member in crew:
            if member["role"] == "trainee":
                trainees_in_crews.append((member["id"], trainer_id))

    if not trainees_in_crews:
        return

    # Lock previous records whose target_date is in the past
    unlocked_past = db.query(TrainingRecord).filter(
        TrainingRecord.record_date < target_date,
        TrainingRecord.is_locked == False
    ).all()
    for rec in unlocked_past:
        rec.is_locked = True
    if unlocked_past:
        db.flush()

    # Fetch curriculum
    curriculum = db.query(TrainingCurriculum).order_by(TrainingCurriculum.day_number).all()
    curriculum_by_day = {}
    for item in curriculum:
        curriculum_by_day.setdefault(item.day_number, []).append(item)

    for trainee_id, trainer_id in trainees_in_crews:
        # --- Continuation request resolution ---
        # Check if this trainee has an accepted continuation request.
        # This must happen before creating the record so we can override trainer_id.
        active_request = db.query(TrainerContinuationRequest).filter(
            TrainerContinuationRequest.trainee_id == trainee_id,
            TrainerContinuationRequest.status == "accepted",
        ).first()

        if active_request:
            # Check if the requested trainer is available today (in the assigned crews).
            requested_trainer_id = active_request.trainer_id
            trainer_available = any(
                any(m["id"] == requested_trainer_id and m["role"] == "trainer" for m in crew)
                for crew in assigned_crews.values()
            )
            if trainer_available:
                # Honour the request — override the dispatch-assigned trainer.
                trainer_id = requested_trainer_id
            # Whether honoured or not, nullify the request — it has served its purpose.
            active_request.status = "nullified"
            active_request.resolved_at = datetime.now(timezone.utc)

        # Auto-expire any still-pending request for this trainee on their next
        # assigned day — trainer neither accepted nor rejected in time.
        pending_request = db.query(TrainerContinuationRequest).filter(
            TrainerContinuationRequest.trainee_id == trainee_id,
            TrainerContinuationRequest.status == "pending",
        ).first()
        if pending_request:
            pending_request.status = "nullified"
            pending_request.resolved_at = datetime.now(timezone.utc)

        db.flush()

        # Check if record already exists for today
        existing_record = db.query(TrainingRecord).filter(
            TrainingRecord.trainee_id == trainee_id,
            TrainingRecord.record_date == target_date
        ).first()

        if existing_record:
            existing_record.trainer_id = trainer_id
            continue

        # Find previous records
        prev_records = db.query(TrainingRecord).filter(
            TrainingRecord.trainee_id == trainee_id,
            TrainingRecord.record_date < target_date
        ).order_by(TrainingRecord.record_date.desc()).all()

        if not prev_records:
            current_day = 1
        else:
            last_record = prev_records[0]
            current_day = last_record.current_day_number + 1
        
        if current_day > 5:
            current_day = 5 # Or cap at max day available? Assuming 5 days.
            
        # Create new record
        new_record = TrainingRecord(
            trainee_id=trainee_id,
            trainer_id=trainer_id,
            record_date=target_date,
            current_day_number=current_day
        )
        db.add(new_record)
        db.flush()

        # Find incomplete mandatory tasks from past records (Training Debt)
        debt_tasks = []
        if prev_records:
            prev_record_ids = [r.id for r in prev_records]
            # Tasks that were mandatory but not completed
            uncompleted_mandatory = db.query(TrainingTask).filter(
                TrainingTask.training_record_id.in_(prev_record_ids),
                TrainingTask.is_mandatory == True,
                TrainingTask.is_completed == False
            ).all()

            # Map by topic title to avoid duplicate debts
            for task in uncompleted_mandatory:
                if not any(d.topic_title == task.topic_title for d in debt_tasks):
                    debt_tasks.append(task)

        for dt in debt_tasks:
            new_debt_age = (dt.debt_age or 0) + 1
            debt_task = TrainingTask(
                training_record_id=new_record.id,
                topic_title=dt.topic_title,
                description=dt.description,
                is_mandatory=True,
                is_training_debt=True,
                debt_age=new_debt_age,
                is_escalated=new_debt_age >= DEBT_ESCALATION_THRESHOLD,
            )
            db.add(debt_task)

        # Add tasks for current day
        day_tasks = curriculum_by_day.get(current_day, [])
        for ct in day_tasks:
            # Avoid adding if it's already in debt (rare, but just in case)
            if any(d.topic_title == ct.topic_title for d in debt_tasks):
                continue
            
            new_task = TrainingTask(
                training_record_id=new_record.id,
                topic_title=ct.topic_title,
                description=ct.description,
                is_mandatory=ct.is_mandatory,
                is_training_debt=False
            )
            db.add(new_task)

    db.commit()
