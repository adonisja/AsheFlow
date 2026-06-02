from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_db, get_caller_employee
from app.models.employee import Employee
from app.models.trainer_coverage import TrainerCoverage

router = APIRouter(prefix="/trainer-coverage", tags=["trainer-coverage"])

allow_mgmt_trainer = RoleChecker(["management", "admin", "trainer"])


@router.get("/record/{record_id}", response_model=List[dict])
def get_coverage_for_record(
    record_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt_trainer),
):
    """Full topic-by-topic coverage log for a training record, ordered by time.

    Shows which trainer covered each topic and when — the handoff trail.
    Useful for investigating mid-shift trainer changes and verifying coverage
    completeness.
    """
    rows = (
        db.query(TrainerCoverage)
        .filter(
            TrainerCoverage.training_record_id == record_id,
            TrainerCoverage.company_id == caller.company_id,
        )
        .order_by(TrainerCoverage.covered_at)
        .all()
    )

    trainer_ids = {r.trainer_id for r in rows}
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(trainer_ids), Employee.company_id == caller.company_id).all()}

    return [
        {
            "id": str(row.id),
            "topic_title": row.topic_title,
            "trainer": {
                "id": str(row.trainer_id),
                "name": emp_map[row.trainer_id].name if row.trainer_id in emp_map else "Unknown",
            },
            "covered_at": row.covered_at.isoformat(),
        }
        for row in rows
    ]
