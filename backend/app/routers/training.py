import logging
from typing import List, Optional
from uuid import UUID
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.database import get_db
from app.api.deps import RoleChecker, get_current_user, get_caller_employee_optional, get_caller_employee
from app.models.training import TrainingRecord, TrainingTask
from app.models.employee import Employee
from app.schemas.training import TrainingRecordResponse, ManagerCommentCreate, TrainerCommentCreate, TrainingTaskResponse, TraineeReviewCreate, TraineeReassignRequest, TaskUpdate
from app.models.notification import Notification

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/training",
    tags=["training"],
    responses={404: {"description": "Not found"}},
)

@router.get("/daily/active", response_model=List[dict])
def get_daily_active_trainings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["management", "admin"]))
):
    """
    Managers/Admins view all today's active training records, including trainee and trainer explicitly.
    """
    today = date.today()
    records = db.query(TrainingRecord).filter(TrainingRecord.record_date == today).all()

    # Bulk-fetch all referenced employees
    emp_ids = {r.trainee_id for r in records} | {r.trainer_id for r in records if r.trainer_id}
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}

    # Bulk-fetch all tasks for today's records in one query
    record_ids = [r.id for r in records]
    all_tasks  = db.query(TrainingTask).filter(TrainingTask.training_record_id.in_(record_ids)).all()
    tasks_by_record: dict = {}
    for t in all_tasks:
        tasks_by_record.setdefault(t.training_record_id, []).append(t)

    result = []
    for record in records:
        trainee = emp_map.get(record.trainee_id)
        trainer = emp_map.get(record.trainer_id) if record.trainer_id else None
        tasks   = tasks_by_record.get(record.id, [])
        result.append({
            "record": TrainingRecordResponse.model_validate(record).model_dump(),
            "trainee": {"id": str(trainee.id), "name": trainee.name} if trainee else None,
            "trainer": {"id": str(trainer.id), "name": trainer.name} if trainer else None,
            "progress": {"total": len(tasks), "completed": sum(1 for t in tasks if t.is_completed)},
        })
    return result

@router.get("/trainee/{trainee_id}", response_model=List[TrainingRecordResponse])
def get_trainee_history(
    trainee_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["management", "trainer", "trainee", "admin"]))
):
    """
    Fetch all training records for a specific trainee.
    Managers/Admins can see all records. Trainers see assigned records. Trainees can see their own.
    """
    records = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.trainee_id == trainee_id)
        .order_by(desc(TrainingRecord.record_date))
        .all()
    )
    
    caller_groups = current_user.get("cognito_groups", [])
    is_privileged = any(r in caller_groups for r in ["trainer", "management", "admin"])

    result = []
    for record in records:
        tasks = db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()
        record_resp = TrainingRecordResponse.model_validate(record)
        record_resp.tasks = tasks
        # trainer_comments are internal — hide from trainees
        if not is_privileged:
            record_resp.trainer_comments = None
        result.append(record_resp)

    return result

@router.post("/trainee/{trainee_id}/trainer-comments", response_model=TrainingRecordResponse)
def add_trainer_comment(
    trainee_id: UUID,
    comment_data: TrainerCommentCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["trainer", "admin"]))
):
    """Trainer leaves a comment on the trainee's most recent training record.

    Viewable by trainer, management, and admin only — trainee cannot see this.
    Appends to any existing comment rather than overwriting.
    Blocked if the record is locked.
    """
    record = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.trainee_id == trainee_id)
        .order_by(desc(TrainingRecord.record_date))
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No training history found for this trainee.",
        )

    if record.is_locked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot comment on a locked training record.",
        )

    if record.trainer_comments:
        record.trainer_comments += f"\n\n[Added later] {comment_data.comments}"
    else:
        record.trainer_comments = comment_data.comments

    db.commit()
    db.refresh(record)

    tasks = db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()
    record_resp = TrainingRecordResponse.model_validate(record)
    record_resp.tasks = tasks
    return record_resp


@router.post("/trainee/{trainee_id}/manager-comments", response_model=TrainingRecordResponse)
def add_manager_comment(
    trainee_id: UUID,
    comment_data: ManagerCommentCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["management", "admin"]))
):
    record = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.trainee_id == trainee_id)
        .order_by(desc(TrainingRecord.record_date))
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No training history found."
        )

    if record.manager_comments:
        record.manager_comments += f"\n\n[Added later] {comment_data.comments}"
    else:
        record.manager_comments = comment_data.comments
        
    db.commit()
    db.refresh(record)

    tasks = db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()
    record_resp = TrainingRecordResponse.model_validate(record)
    record_resp.tasks = tasks

    return record_resp


@router.post("/record/{record_id}/review", response_model=TrainingRecordResponse)
def submit_trainee_review(
    record_id: UUID,
    review_data: TraineeReviewCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["trainee", "admin"]))
):
    """
    Trainee submits rating/comments on a specific shift.
    Locked after the NEXT day.
    """
    record = db.query(TrainingRecord).filter(TrainingRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    # Ownership: trainees can only review their own record; admin bypass
    if caller.role != "admin" and record.trainee_id != caller.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only review your own training records.")

    # Check lock (next day rule)
    if datetime.now(timezone.utc).date() > record.record_date + timedelta(days=1):
        raise HTTPException(status_code=400, detail="Review period has closed for this record.")
        
    record.trainee_comments = review_data.trainee_comments
    record.trainer_rating = review_data.trainer_rating
    db.commit()
    db.refresh(record)
    
    tasks = db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()
    record_resp = TrainingRecordResponse.model_validate(record)
    record_resp.tasks = tasks
    return record_resp


@router.get("/escalated", response_model=List[dict])
def get_escalated_trainees(
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["management", "admin"]))
):
    """Return all trainees who have at least one escalated debt task.

    An escalated task is a mandatory task that has been carried as unresolved
    debt for >= DEBT_ESCALATION_THRESHOLD dispatch days. This endpoint surfaces
    chronic training gaps that require manager intervention.

    Each entry includes the trainee, their most recent training record, and
    all escalated tasks on that record.
    """
    escalated_tasks = (
        db.query(TrainingTask)
        .filter(
            TrainingTask.is_escalated == True,
            TrainingTask.is_completed == False,
        )
        .all()
    )

    # Bulk-fetch all referenced records and employees in one query each
    record_ids = list({t.training_record_id for t in escalated_tasks})
    records    = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.id.in_(record_ids))
        .all()
    )

    emp_ids = {r.trainee_id for r in records} | {r.trainer_id for r in records if r.trainer_id}
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}

    # Group escalated tasks by record_id for O(1) lookup in the loop below
    tasks_by_record: dict = {}
    for t in escalated_tasks:
        tasks_by_record.setdefault(t.training_record_id, []).append(t)

    # Deduplicate by trainee — only surface their most recent escalated record.
    latest_by_trainee: dict = {}
    for record in records:
        existing = latest_by_trainee.get(record.trainee_id)
        if existing is None or record.record_date > existing.record_date:
            latest_by_trainee[record.trainee_id] = record

    result = []
    for trainee_id, record in latest_by_trainee.items():
        trainee  = emp_map.get(trainee_id)
        trainer  = emp_map.get(record.trainer_id) if record.trainer_id else None
        escalated = tasks_by_record.get(record.id, [])
        result.append({
            "trainee": {"id": str(trainee.id), "name": trainee.name} if trainee else None,
            "trainer": {"id": str(trainer.id), "name": trainer.name} if trainer else None,
            "record": TrainingRecordResponse.model_validate(record).model_dump(),
            "escalated_tasks": [
                {
                    "id": str(t.id),
                    "topic_title": t.topic_title,
                    "description": t.description,
                    "debt_age": t.debt_age,
                }
                for t in sorted(escalated, key=lambda t: t.debt_age, reverse=True)
            ],
        })

    # Sort by worst offender first (most escalated tasks).
    result.sort(key=lambda r: len(r["escalated_tasks"]), reverse=True)
    return result


@router.get("/trainer/today", response_model=dict)
def get_trainer_today(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["trainer", "admin"])),
):
    """Return the calling trainer's today record with trainee details, tasks,
    manager_comments, and previous trainer_comments from the prior session.

    Declared before /trainer/{trainer_id}/history so the literal segment 'today'
    is matched first and not consumed as a UUID path parameter.
    """
    today = date.today()
    record = (
        db.query(TrainingRecord)
        .filter(
            TrainingRecord.trainer_id == caller.id,
            TrainingRecord.record_date == today,
        )
        .first()
    )

    if not record:
        return {"record": None, "trainee": None, "tasks": [], "previous_trainer_comments": None, "manager_comments": None}

    trainee = db.query(Employee).filter(Employee.id == record.trainee_id).first()
    tasks = db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()

    # Find the previous session's trainer_comments (the most recent record before today)
    previous_record = (
        db.query(TrainingRecord)
        .filter(
            TrainingRecord.trainee_id == record.trainee_id,
            TrainingRecord.record_date < today,
            TrainingRecord.trainer_comments.isnot(None),
        )
        .order_by(desc(TrainingRecord.record_date))
        .first()
    )

    return {
        "record": TrainingRecordResponse.model_validate(record).model_dump(),
        "trainee": {"id": str(trainee.id), "name": trainee.name} if trainee else None,
        "tasks": [
            {
                "id": str(t.id),
                "topic_title": t.topic_title,
                "description": t.description,
                "is_completed": t.is_completed,
                "is_training_debt": t.is_training_debt,
                "is_escalated": t.is_escalated,
            }
            for t in tasks
        ],
        "previous_trainer_comments": {
            "comments": previous_record.trainer_comments,
            "record_date": str(previous_record.record_date),
            "day_number": previous_record.current_day_number,
        } if previous_record else None,
        "manager_comments": record.manager_comments,
    }


@router.get("/trainer/{trainer_id}/history", response_model=List[dict])
def get_trainer_history(
    trainer_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["trainer", "management", "admin"])),
):
    """Return all training records where this trainer was assigned.

    Groups by trainee so the caller gets one entry per trainee with a list of
    session records.  Each record includes tasks, trainer_comments, and
    manager_comments so the trainer can review handoff notes.
    """
    records = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.trainer_id == trainer_id)
        .order_by(desc(TrainingRecord.record_date))
        .all()
    )

    # Bulk-fetch employees and tasks
    trainee_ids = list({r.trainee_id for r in records})
    emp_map = {
        e.id: e
        for e in db.query(Employee).filter(Employee.id.in_(trainee_ids)).all()
    }

    record_ids = [r.id for r in records]
    all_tasks = db.query(TrainingTask).filter(TrainingTask.training_record_id.in_(record_ids)).all()
    tasks_by_record: dict = {}
    for t in all_tasks:
        tasks_by_record.setdefault(t.training_record_id, []).append(t)

    # Group by trainee
    by_trainee: dict = {}
    for record in records:
        entry = by_trainee.setdefault(record.trainee_id, {
            "trainee": None,
            "sessions": [],
        })
        trainee = emp_map.get(record.trainee_id)
        entry["trainee"] = {"id": str(trainee.id), "name": trainee.name} if trainee else None

        tasks = tasks_by_record.get(record.id, [])
        entry["sessions"].append({
            "record": TrainingRecordResponse.model_validate(record).model_dump(),
            "tasks": [
                {
                    "id": str(t.id),
                    "topic_title": t.topic_title,
                    "is_completed": t.is_completed,
                    "is_training_debt": t.is_training_debt,
                    "is_escalated": t.is_escalated,
                }
                for t in tasks
            ],
        })

    result = list(by_trainee.values())
    # Sort by most recently trained first
    result.sort(key=lambda x: x["sessions"][0]["record"]["record_date"], reverse=True)
    return result


@router.patch("/trainee/reassign", response_model=dict)
def reassign_trainee(
    payload: TraineeReassignRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(RoleChecker(["management", "dispatch", "admin"])),
    actor: Employee = Depends(get_caller_employee_optional),
):
    """Reassign a trainee to a different trainer for a given date.

    Workflow:
    1. Verify the trainee has a TrainingRecord for target_date.
    2. Verify the new trainer exists and has the trainer role.
    3. Check if the new trainer already owns a TrainingRecord for that date
       (i.e. already has an assigned trainee).
       - If yes: send a notification to the dispatcher, bump the displaced trainee
         to a randomly selected available trainer who has no trainee today, then
         update the displaced trainee's record accordingly.
    4. Update the target trainee's TrainingRecord.trainer_id to new_trainer_id.

    Raises:
        404: Trainee has no training record for target_date.
        404: New trainer not found or not a trainer role.
        409: No available trainer exists to absorb the displaced trainee.
    """
    import random

    # 1 — Fetch the trainee's record for target_date
    trainee_record = (
        db.query(TrainingRecord)
        .filter(
            TrainingRecord.trainee_id == payload.trainee_id,
            TrainingRecord.record_date == payload.target_date,
        )
        .first()
    )
    if not trainee_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No training record found for trainee on {payload.target_date}.",
        )

    # 2 — Verify new trainer exists and holds the trainer role
    new_trainer = (
        db.query(Employee)
        .filter(Employee.id == payload.new_trainer_id, Employee.role == "trainer")
        .first()
    )
    if not new_trainer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="New trainer not found or employee is not a trainer.",
        )

    warnings = []

    # 3 — Check if new trainer already has a trainee today
    existing_trainer_record = (
        db.query(TrainingRecord)
        .filter(
            TrainingRecord.trainer_id == payload.new_trainer_id,
            TrainingRecord.record_date == payload.target_date,
            TrainingRecord.trainee_id != payload.trainee_id,
        )
        .first()
    )

    if existing_trainer_record:
        # Find all trainers who have NO training record today (no assigned trainee)
        trainers_with_records_today = (
            db.query(TrainingRecord.trainer_id)
            .filter(
                TrainingRecord.record_date == payload.target_date,
                TrainingRecord.trainer_id.isnot(None),
            )
            .subquery()
        )
        available_trainers = (
            db.query(Employee)
            .filter(
                Employee.role == "trainer",
                Employee.is_active == True,
                Employee.id.notin_(trainers_with_records_today),
                Employee.id != payload.new_trainer_id,
            )
            .all()
        )

        if not available_trainers:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Trainer {new_trainer.name} already has a trainee today and no "
                    "other trainers are available to absorb the displaced trainee."
                ),
            )

        # Randomly pick an available trainer for the displaced trainee
        fallback_trainer = random.choice(available_trainers)
        existing_trainer_record.trainer_id = fallback_trainer.id

        warning_msg = (
            f"Trainer {new_trainer.name} already had an assigned trainee on "
            f"{payload.target_date}. That trainee was reassigned to "
            f"{fallback_trainer.name}."
        )
        warnings.append(warning_msg)

        # Notify the acting dispatcher/manager via the notification system
        if actor:
            db.add(Notification(
                employee_id=actor.id,
                type="trainee_reassign_warning",
                message=warning_msg,
            ))

    # 4 — Update the target trainee's record
    trainee_record.trainer_id = payload.new_trainer_id

    db.commit()

    trainee = db.query(Employee).filter(Employee.id == payload.trainee_id).first()
    return {
        "message": "Trainee successfully reassigned.",
        "trainee": {"id": str(trainee.id), "name": trainee.name} if trainee else None,
        "new_trainer": {"id": str(new_trainer.id), "name": new_trainer.name},
        "date": str(payload.target_date),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Training Pipeline Summary — management reporting
# ---------------------------------------------------------------------------

@router.get("/pipeline-summary")
def get_training_pipeline_summary(
    db: Session = Depends(get_db),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
):
    """Return a snapshot of the training pipeline for the management dashboard.

    Includes:
    - Total active trainees
    - Active training records today
    - Escalated trainee count (has at least one escalated task)
    - Per-trainer load (trainee count assigned today)
    """
    from app.models.training import TrainingRecord, TrainingTask

    today = date.today()

    active_trainees = (
        db.query(Employee)
        .filter(Employee.role == "trainee", Employee.is_active == True)
        .count()
    )

    today_records = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.record_date == today)
        .all()
    )

    escalated_trainee_ids = set(
        r.trainee_id for r in
        db.query(TrainingRecord)
        .join(TrainingTask, TrainingTask.training_record_id == TrainingRecord.id)
        .filter(TrainingTask.is_escalated == True, TrainingTask.is_completed == False)
        .all()
    )

    trainer_loads = {}
    for record in today_records:
        if record.trainer_id:
            tid = str(record.trainer_id)
            if tid not in trainer_loads:
                trainer = db.query(Employee).filter(Employee.id == record.trainer_id).first()
                trainer_loads[tid] = {
                    "trainer_id": tid,
                    "trainer_name": trainer.name if trainer else "Unknown",
                    "trainee_count": 0,
                }
            trainer_loads[tid]["trainee_count"] += 1

    return {
        "active_trainees": active_trainees,
        "training_sessions_today": len(today_records),
        "escalated_count": len(escalated_trainee_ids),
        "trainer_loads": sorted(trainer_loads.values(), key=lambda x: x["trainee_count"], reverse=True),
    }


@router.patch("/task/{task_id}", response_model=TrainingTaskResponse)
def update_task(
    task_id: UUID,
    task_update: TaskUpdate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["trainer", "management", "admin"]))
):
    task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    record = db.query(TrainingRecord).filter(TrainingRecord.id == task.training_record_id).first()
    if record and record.is_locked:
        raise HTTPException(status_code=400, detail="Cannot edit a locked training record")

    # Trainers can only update tasks on their own trainees; management/admin bypass
    if caller.role == "trainer" and record and record.trainer_id != caller.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update tasks for your own trainees.")
        
    task.is_completed = task_update.is_completed
    db.commit()
    db.refresh(task)
    return task
