"""Amazon (NYCD) weekly scorecards (ADR-204 Phase B).

POST   /scorecards                 — mgmt creates/updates a week's scorecard (structured entry)
GET    /scorecards/me              — the caller's own scorecards (latest first)
GET    /scorecards/{week}          — mgmt: all scorecards for a week (individual + company)
DELETE /scorecards/{scorecard_id}  — mgmt removes one

Amazon-computed values are stored/displayed as-is. The cross-check (Phase D) compares a subset
against our DeliveryStop/RTS data. This router is public — no proprietary algorithm.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.scorecard import Scorecard, ScorecardMetric
from app.schemas.scorecard import ScorecardCreate, ScorecardOut
from app.services.audit import write_audit

router = APIRouter(prefix="/scorecards", tags=["scorecards"])

_allow_mgmt = RoleChecker(["dispatch", "management", "admin"])


def _serialize(sc: Scorecard, emp_name: Optional[str]) -> dict:
    return {
        "id": sc.id, "week": sc.week, "scope": sc.scope,
        "employee_id": sc.employee_id, "employee_name": emp_name,
        "overall_standing": sc.overall_standing, "source_file_url": sc.source_file_url,
        "created_at": sc.created_at, "metrics": sc.metrics,
    }


@router.post("", response_model=ScorecardOut, status_code=status.HTTP_201_CREATED)
def upsert_scorecard(
    payload: ScorecardCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
    db: Session = Depends(get_db),
):
    """Create or replace the scorecard for (week, scope, employee). Upsert on the
    unique key so re-uploading a corrected scorecard overwrites cleanly."""
    cid = caller.company_id

    if payload.scope == "individual" and payload.employee_id is None:
        raise HTTPException(status_code=400, detail="employee_id is required for an individual scorecard.")
    if payload.scope == "company" and payload.employee_id is not None:
        raise HTTPException(status_code=400, detail="A company scorecard must not name an employee.")

    emp_name = None
    if payload.employee_id is not None:
        emp = db.query(Employee).filter(
            Employee.id == payload.employee_id, Employee.company_id == cid,
        ).first()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found.")
        emp_name = emp.name

    existing = db.query(Scorecard).filter(
        Scorecard.company_id == cid,
        Scorecard.week == payload.week,
        Scorecard.scope == payload.scope,
        Scorecard.employee_id == payload.employee_id,
    ).first()

    if existing:
        existing.overall_standing = payload.overall_standing
        existing.source_file_url = payload.source_file_url
        existing.entered_by = caller.id
        # Replace metric rows wholesale (cascade delete-orphan handles removal).
        existing.metrics.clear()
        db.flush()
        sc = existing
    else:
        sc = Scorecard(
            company_id=cid, week=payload.week, scope=payload.scope,
            employee_id=payload.employee_id, overall_standing=payload.overall_standing,
            source_file_url=payload.source_file_url, entered_by=caller.id,
        )
        db.add(sc)
        db.flush()

    for m in payload.metrics:
        sc.metrics.append(ScorecardMetric(
            key=m.key, label=m.label, value=m.value, unit=m.unit,
            tier=m.tier, flag=m.flag, sort_order=m.sort_order,
        ))

    write_audit(
        db=db, company_id=cid, actor_id=caller.id,
        action_type="scorecard.upsert", target_table="scorecards", target_id=str(sc.id),
        detail={"week": sc.week, "scope": sc.scope, "employee_id": str(sc.employee_id) if sc.employee_id else None,
                "metrics": len(payload.metrics)},
    )
    db.commit()
    db.refresh(sc)
    return _serialize(sc, emp_name)


@router.get("/me", response_model=List[ScorecardOut])
def get_my_scorecards(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """The caller's own individual scorecards, latest week first."""
    rows = db.query(Scorecard).filter(
        Scorecard.company_id == caller.company_id,
        Scorecard.scope == "individual",
        Scorecard.employee_id == caller.id,
    ).order_by(Scorecard.week.desc()).all()
    return [_serialize(sc, caller.name) for sc in rows]


@router.get("/{week}", response_model=List[ScorecardOut])
def get_week_scorecards(
    week: str,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
    db: Session = Depends(get_db),
):
    """All scorecards for a week (individual + company) — management view."""
    cid = caller.company_id
    rows = db.query(Scorecard).filter(
        Scorecard.company_id == cid, Scorecard.week == week,
    ).all()
    emp_ids = {sc.employee_id for sc in rows if sc.employee_id}
    names = {
        e.id: e.name for e in db.query(Employee).filter(
            Employee.id.in_(emp_ids), Employee.company_id == cid,
        ).all()
    } if emp_ids else {}
    return [_serialize(sc, names.get(sc.employee_id)) for sc in rows]


@router.delete("/{scorecard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scorecard(
    scorecard_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
    db: Session = Depends(get_db),
):
    sc = db.query(Scorecard).filter(
        Scorecard.id == scorecard_id, Scorecard.company_id == caller.company_id,
    ).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    db.delete(sc)
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="scorecard.delete", target_table="scorecards", target_id=str(scorecard_id),
        detail={"week": sc.week, "scope": sc.scope},
    )
    db.commit()
