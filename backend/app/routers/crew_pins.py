"""Crew pin management (ADR-357).

Creating and clearing a pin is a DISPATCH action, not something a crew member
does to themselves — a pin binds other people to a truck.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.crew_pin import CrewPin, CrewPinMember
from app.models.employee import Employee
from app.schemas.crew_pin import CrewPinCreate, CrewPinResponse, CrewPinUpdate
from app.services.audit import write_audit

router = APIRouter(prefix="/crew-pins", tags=["crew-pins"])

allow_dispatch = RoleChecker(["dispatch", "management", "admin"])


def _reject_if_truck_pinned(db: Session, company_id, employee_id, name: str | None) -> None:
    """409 if this employee is pinned to a truck (ADR-358 D2)."""
    from app.models.truck_pin import TruckPin

    pin = (
        db.query(TruckPin)
        .filter(
            TruckPin.company_id == company_id,
            TruckPin.employee_id == employee_id,
        )
        .first()
    )
    if pin:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{name or 'That employee'} is pinned to a truck on {pin.day_of_week}. "
                f"A person can be pinned to a driver or to a truck, not both."
            ),
        )


def _to_response(db: Session, pin: CrewPin, company_id: UUID) -> CrewPinResponse:
    """Attach names so the UI never has to resolve ids itself."""
    ids = [pin.driver_id] + [m.employee_id for m in pin.members]
    people = {
        e.id: e
        for e in db.query(Employee)
        .filter(Employee.id.in_(ids), Employee.company_id == company_id)
        .all()
    }
    driver = people.get(pin.driver_id)
    return CrewPinResponse(
        id=pin.id,
        name=pin.name,
        driver_id=pin.driver_id,
        driver_name=driver.name if driver else None,
        is_active=pin.is_active,
        inactive_reason=pin.inactive_reason,
        created_at=pin.created_at,
        members=[
            {
                "employee_id": m.employee_id,
                "name": people[m.employee_id].name if m.employee_id in people else None,
                "role": people[m.employee_id].role if m.employee_id in people else None,
            }
            for m in pin.members
        ],
    )


@router.get("", response_model=list[CrewPinResponse])
def list_crew_pins(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    pins = (
        db.query(CrewPin)
        .filter(CrewPin.company_id == caller.company_id)
        .order_by(CrewPin.created_at.desc())
        .all()
    )
    return [_to_response(db, p, caller.company_id) for p in pins]


@router.post("", response_model=CrewPinResponse, status_code=status.HTTP_201_CREATED)
def create_crew_pin(
    body: CrewPinCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    driver = (
        db.query(Employee)
        .filter(Employee.id == body.driver_id, Employee.company_id == caller.company_id)
        .first()
    )
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    if driver.role != "driver":
        raise HTTPException(
            status_code=400,
            detail=f"A crew pin's anchor must be a driver; {driver.name} is a {driver.role}.",
        )

    # ADR-358 D2 — the two pin axes are mutually exclusive per person. Checked
    # on BOTH endpoints: an invariant guarded at one door only is as strong as
    # its weaker door.
    _reject_if_truck_pinned(db, caller.company_id, driver.id, driver.name)

    # ADR-357 D6 — one active pin per driver. Two cannot both be honoured.
    existing = (
        db.query(CrewPin)
        .filter(
            CrewPin.company_id == caller.company_id,
            CrewPin.driver_id == body.driver_id,
            CrewPin.is_active.is_(True),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"{driver.name} already anchors the active crew pin '{existing.name}'.",
        )

    member_ids = [m for m in body.member_ids if m != body.driver_id]
    if member_ids:
        found = (
            db.query(Employee.id)
            .filter(Employee.id.in_(member_ids), Employee.company_id == caller.company_id)
            .all()
        )
        if len(found) != len(set(member_ids)):
            raise HTTPException(
                status_code=404, detail="One or more members were not found."
            )

        for mid in set(member_ids):
            who = (
                db.query(Employee)
                .filter(Employee.id == mid, Employee.company_id == caller.company_id)
                .first()
            )
            _reject_if_truck_pinned(db, caller.company_id, mid, who.name if who else None)

        # An employee in two active pins is the same unresolvable conflict as two
        # pins on one driver, one layer down.
        clash = (
            db.query(CrewPinMember)
            .join(CrewPin, CrewPin.id == CrewPinMember.pin_id)
            .filter(
                CrewPinMember.company_id == caller.company_id,
                CrewPinMember.employee_id.in_(member_ids),
                CrewPin.is_active.is_(True),
            )
            .first()
        )
        if clash:
            who = (
                db.query(Employee.name)
                .filter(
                    Employee.id == clash.employee_id,
                    Employee.company_id == caller.company_id,
                )
                .scalar()
            )
            raise HTTPException(
                status_code=409,
                detail=f"{who or 'That employee'} is already in another active crew pin.",
            )

    pin = CrewPin(
        company_id=caller.company_id,
        name=body.name,
        driver_id=body.driver_id,
        created_by=caller.id,
    )
    db.add(pin)
    db.flush()

    for mid in set(member_ids):
        db.add(
            CrewPinMember(
                company_id=caller.company_id, pin_id=pin.id, employee_id=mid
            )
        )
    db.flush()

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="crew_pin.created",
        target_table="crew_pins",
        target_id=str(pin.id),
        detail={"name": pin.name, "driver_id": str(pin.driver_id), "members": len(member_ids)},
    )
    db.commit()
    db.refresh(pin)
    return _to_response(db, pin, caller.company_id)


@router.patch("/{pin_id}", response_model=CrewPinResponse)
def update_crew_pin(
    pin_id: UUID,
    body: CrewPinUpdate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    pin = (
        db.query(CrewPin)
        .filter(CrewPin.id == pin_id, CrewPin.company_id == caller.company_id)
        .first()
    )
    if not pin:
        raise HTTPException(status_code=404, detail="Crew pin not found.")

    if body.name is not None:
        pin.name = body.name

    if body.is_active is not None:
        pin.is_active = body.is_active
        # Reactivating clears the reason; leaving a stale "deactivated because…"
        # on an active pin would read as a live warning.
        pin.inactive_reason = None if body.is_active else pin.inactive_reason

    if body.member_ids is not None:
        wanted = {m for m in body.member_ids if m != pin.driver_id}

        # Validate before deleting: an unchecked id would silently pin a
        # nonexistent employee, or one from another tenant, and the old roster
        # would already be gone.
        if wanted:
            found = (
                db.query(Employee.id)
                .filter(
                    Employee.id.in_(wanted), Employee.company_id == caller.company_id
                )
                .all()
            )
            if len(found) != len(wanted):
                raise HTTPException(
                    status_code=404, detail="One or more members were not found."
                )

        # company_id is redundant here — `pin` was already company-scoped above —
        # but it keeps the delete safe if that coupling is ever refactored away.
        db.query(CrewPinMember).filter(
            CrewPinMember.pin_id == pin.id,
            CrewPinMember.company_id == caller.company_id,
        ).delete(synchronize_session=False)
        for mid in wanted:
            db.add(
                CrewPinMember(
                    company_id=caller.company_id, pin_id=pin.id, employee_id=mid
                )
            )

    db.flush()
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="crew_pin.updated",
        target_table="crew_pins",
        target_id=str(pin.id),
        detail={"is_active": pin.is_active},
    )
    db.commit()
    db.refresh(pin)
    return _to_response(db, pin, caller.company_id)


@router.delete("/{pin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_crew_pin(
    pin_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    pin = (
        db.query(CrewPin)
        .filter(CrewPin.id == pin_id, CrewPin.company_id == caller.company_id)
        .first()
    )
    if not pin:
        raise HTTPException(status_code=404, detail="Crew pin not found.")

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="crew_pin.deleted",
        target_table="crew_pins",
        target_id=str(pin.id),
        detail={"name": pin.name},
    )
    db.delete(pin)
    db.commit()
    return None
