from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from fastapi import HTTPException, status
from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.employee import Employee
from app.models.trainer_mark import TrainerMark
from app.models.training import TrainingRecord
from app.services.record_trainer_mark import UNDERPERFORMING_MARK_THRESHOLD

router = APIRouter(prefix="/trainer-marks", tags=["trainer-marks"])

allow_mgmt         = RoleChecker(["management", "admin"])
allow_trainer_self = RoleChecker(["trainer", "management", "admin"])


@router.get("/", response_model=List[dict])
def list_all_marks(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    """List all trainer marks with trainer name, trainee name, date, and reason.
    Most recent first. Management/admin only.
    """
    marks = (
        db.query(TrainerMark)
        .join(Employee, TrainerMark.trainer_id == Employee.id)
        .filter(Employee.company_id == caller.company_id)
        .order_by(TrainerMark.created_at.desc())
        .all()
    )

    emp_ids = {m.trainer_id for m in marks} | {m.trainee_id for m in marks}
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}

    record_ids = {m.training_record_id for m in marks}
    record_map = {r.id: r for r in db.query(TrainingRecord).filter(TrainingRecord.id.in_(record_ids)).all()}

    return [
        {
            "id": str(m.id),
            "trainer": _emp_stub(emp_map.get(m.trainer_id)),
            "trainee": _emp_stub(emp_map.get(m.trainee_id)),
            "phase": record_map[m.training_record_id].current_day_number if m.training_record_id in record_map else None,
            "record_date": str(record_map[m.training_record_id].record_date) if m.training_record_id in record_map else None,
            "reason": m.reason,
            "debt_originated": m.debt_originated,
            "debt_chain_context": m.debt_chain_context,
            "created_at": m.created_at.isoformat(),
        }
        for m in marks
    ]


@router.get("/mine", response_model=List[dict])
def my_marks(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return the calling trainer's own marks. Trainers, management, and admin only."""
    if caller.role not in ("trainer", "management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return _marks_for(caller.id, db)


@router.get("/trainer/{trainer_id}", response_model=List[dict])
def marks_for_trainer(
    trainer_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """All marks for a specific trainer, most recent first.

    Trainers may fetch their own; management/admin may fetch any.
    """
    if caller.id != trainer_id and caller.role not in ("management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own marks.")
    return _marks_for(trainer_id, db)


def _marks_for(trainer_id: UUID, db: Session) -> List[dict]:
    """Shared query for a single trainer's marks."""
    marks = (
        db.query(TrainerMark)
        .filter(TrainerMark.trainer_id == trainer_id)
        .order_by(TrainerMark.created_at.desc())
        .all()
    )

    trainee_ids = {m.trainee_id for m in marks}
    trainee_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(trainee_ids)).all()}
    record_ids = {m.training_record_id for m in marks}
    record_map = {r.id: r for r in db.query(TrainingRecord).filter(TrainingRecord.id.in_(record_ids)).all()}

    return [
        {
            "id": str(m.id),
            "trainee": _emp_stub(trainee_map.get(m.trainee_id)),
            "phase": record_map[m.training_record_id].current_day_number if m.training_record_id in record_map else None,
            "record_date": str(record_map[m.training_record_id].record_date) if m.training_record_id in record_map else None,
            "reason": m.reason,
            "debt_originated": m.debt_originated,
            "debt_chain_context": m.debt_chain_context,
            "created_at": m.created_at.isoformat(),
        }
        for m in marks
    ]


@router.get("/mine/summary")
def my_marks_summary(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return the calling trainer's own mark count and underperforming flag.
    Trainers, management, and admin only.
    """
    if caller.role not in ("trainer", "management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    marks = db.query(TrainerMark).filter(TrainerMark.trainer_id == caller.id).all()
    distinct_trainees = len({m.trainee_id for m in marks})
    return {
        "total_marks": len(marks),
        "distinct_trainees_with_marks": distinct_trainees,
        "underperforming": distinct_trainees >= UNDERPERFORMING_MARK_THRESHOLD,
    }


@router.get("/summary", response_model=List[dict])
def trainer_mark_summary(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    """Per-trainer mark count and underperforming flag status. Sorted by mark count descending."""
    rows = (
        db.query(
            TrainerMark.trainer_id,
            func.count(TrainerMark.id).label("total_marks"),
            func.count(TrainerMark.trainee_id.distinct()).label("distinct_trainees"),
        )
        .join(Employee, TrainerMark.trainer_id == Employee.id)
        .filter(Employee.company_id == caller.company_id)
        .group_by(TrainerMark.trainer_id)
        .all()
    )

    trainer_ids = [r.trainer_id for r in rows]
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(trainer_ids)).all()}

    result = []
    for row in rows:
        trainer = emp_map.get(row.trainer_id)
        result.append({
            "trainer": _emp_stub(trainer),
            "total_marks": row.total_marks,
            "distinct_trainees_with_marks": row.distinct_trainees,
            "underperforming": row.distinct_trainees >= UNDERPERFORMING_MARK_THRESHOLD,
        })

    result.sort(key=lambda r: r["total_marks"], reverse=True)
    return result


def _emp_stub(emp: Employee | None) -> dict | None:
    if not emp:
        return None
    return {"id": str(emp.id), "name": emp.name}
