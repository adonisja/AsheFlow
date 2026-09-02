"""Dispatch separations (ADR-361).

Keeping two people apart is a dispatcher's decision about other people, so it
lives here rather than on /employee-relationships, which is the employees' own
fav/ban surface. Two consequences that matter:

  * A separation must never come back through an employee-facing read. The rows
    share a table with bans and sit in the same two columns (ADR-361 D1), so the
    exclusion is explicit and tested, not a property of the schema.
  * Only dispatch, management and admin can see or touch one. A field role gets
    a 403 on the route, not a filtered empty list.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship
from app.schemas.separation import SeparationCreate, SeparationResponse
from app.services.audit import write_audit
from app.services.seat_crew_pins import nullify_pins_for_ban

router = APIRouter(prefix="/separations", tags=["separations"])

allow_dispatch = RoleChecker(["dispatch", "management", "admin"])


def _load_employee(db: Session, company_id: UUID, employee_id: UUID) -> Employee:
    """Fetch an employee inside the caller's company, or 404."""
    emp = (
        db.query(Employee)
        .filter(
            Employee.id == employee_id,
            Employee.company_id == company_id,
        )
        .first()
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return emp


@router.get("/", response_model=list[SeparationResponse])
def list_separations(
    db: Session = Depends(get_db),
    _: dict = Depends(allow_dispatch),
    caller: Employee = Depends(get_caller_employee),
):
    """Every separation in the caller's company, with both names resolved."""
    rows = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.company_id == caller.company_id,
            EmployeeRelationship.relationship_type == "sep",
        )
        .all()
    )
    if not rows:
        return []

    ids = {r.employee_id for r in rows} | {r.target_employee_id for r in rows}
    names = {
        e.id: e.name
        for e in db.query(Employee)
        .filter(Employee.id.in_(ids), Employee.company_id == caller.company_id)
        .all()
    }
    return [
        SeparationResponse(
            id=r.id,
            employee_id=r.employee_id,
            target_employee_id=r.target_employee_id,
            employee_name=names.get(r.employee_id),
            target_employee_name=names.get(r.target_employee_id),
        )
        for r in rows
    ]


@router.post("/", response_model=SeparationResponse, status_code=status.HTTP_201_CREATED)
def create_separation(
    payload: SeparationCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_dispatch),
    caller: Employee = Depends(get_caller_employee),
):
    """Separate two employees.

    Deliberately NOT capped. The 2-ban limit bounds what an employee may assert
    about others; a separation is not theirs, and counting it against them would
    refuse an employee their own second ban for a reason they cannot see
    (ADR-361 D3).
    """
    emp = _load_employee(db, caller.company_id, payload.employee_id)
    target = _load_employee(db, caller.company_id, payload.target_employee_id)

    # Either ordering of the pair is the same separation. The unique constraint
    # only catches one direction, so check both before inserting.
    existing = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.company_id == caller.company_id,
            EmployeeRelationship.relationship_type == "sep",
            or_(
                and_(
                    EmployeeRelationship.employee_id == emp.id,
                    EmployeeRelationship.target_employee_id == target.id,
                ),
                and_(
                    EmployeeRelationship.employee_id == target.id,
                    EmployeeRelationship.target_employee_id == emp.id,
                ),
            ),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"{emp.name} and {target.name} are already separated.",
        )

    row = EmployeeRelationship(
        company_id=caller.company_id,
        employee_id=emp.id,
        target_employee_id=target.id,
        relationship_type="sep",
    )
    db.add(row)
    db.flush()

    # ADR-361 D4, mirroring ADR-357 D4. Dispatch saying both "these people ride
    # together" and "these two must not be paired" is a contradiction, and the
    # dispatcher should learn now rather than at 4am.
    for pin in nullify_pins_for_ban(db, caller.company_id, emp.id, target.id):
        write_audit(
            db=db,
            company_id=caller.company_id,
            actor_id=caller.id,
            action_type="crew_pin.auto_deactivated",
            target_table="crew_pins",
            target_id=str(pin.id),
            detail={
                "reason": "separation_between_members",
                "employee_id": str(emp.id),
                "target_employee_id": str(target.id),
            },
        )

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="separation.create",
        target_table="employee_relationships",
        target_id=str(row.id),
        detail={
            "employee_id": str(emp.id),
            "target_employee_id": str(target.id),
            # The only home for the reason: the row has no column for it, and
            # the audit log is where "who decided this, and why" belongs.
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(row)

    return SeparationResponse(
        id=row.id,
        employee_id=row.employee_id,
        target_employee_id=row.target_employee_id,
        employee_name=emp.name,
        target_employee_name=target.name,
    )


@router.delete("/{separation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_separation(
    separation_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_dispatch),
    caller: Employee = Depends(get_caller_employee),
):
    """Lift a separation.

    Scoped to relationship_type == 'sep' as well as company: this route must not
    become a way to delete somebody's ban by passing its id.
    """
    row = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.id == separation_id,
            EmployeeRelationship.company_id == caller.company_id,
            EmployeeRelationship.relationship_type == "sep",
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Separation not found.")

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="separation.delete",
        target_table="employee_relationships",
        target_id=str(row.id),
        detail={
            "employee_id": str(row.employee_id),
            "target_employee_id": str(row.target_employee_id),
        },
    )
    db.delete(row)
    db.commit()
    return None
