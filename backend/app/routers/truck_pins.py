"""Truck pin management (ADR-358)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.crew_pin import CrewPin, CrewPinMember
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_pin import TruckPin
from app.schemas.truck_pin import TruckPinCreate, TruckPinResponse
from app.services.audit import write_audit

router = APIRouter(prefix="/truck-pins", tags=["truck-pins"])

allow_dispatch = RoleChecker(["dispatch", "management", "admin"])


def holds_crew_pin(db: Session, company_id: UUID, employee_id: UUID) -> CrewPin | None:
    """Is this employee already on the OTHER pin axis? (ADR-358 D2)

    Shared with the crew-pin router so the exclusivity is enforced at both doors.
    An invariant guarded on one endpoint only is as strong as its weaker door.
    """
    as_driver = (
        db.query(CrewPin)
        .filter(
            CrewPin.company_id == company_id,
            CrewPin.driver_id == employee_id,
            CrewPin.is_active.is_(True),
        )
        .first()
    )
    if as_driver:
        return as_driver

    return (
        db.query(CrewPin)
        .join(CrewPinMember, CrewPinMember.pin_id == CrewPin.id)
        .filter(
            CrewPin.company_id == company_id,
            CrewPin.is_active.is_(True),
            CrewPinMember.employee_id == employee_id,
        )
        .first()
    )


def _to_response(pin: TruckPin, emp: Employee | None, truck: Truck | None) -> TruckPinResponse:
    return TruckPinResponse(
        id=pin.id,
        employee_id=pin.employee_id,
        employee_name=emp.name if emp else None,
        employee_role=emp.role if emp else None,
        truck_id=pin.truck_id,
        truck_name=truck.name if truck else None,
        day_of_week=pin.day_of_week,
        created_at=pin.created_at,
    )


@router.get("", response_model=list[TruckPinResponse])
def list_truck_pins(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    pins = (
        db.query(TruckPin)
        .filter(TruckPin.company_id == caller.company_id)
        .order_by(TruckPin.day_of_week, TruckPin.created_at)
        .all()
    )
    if not pins:
        return []

    people = {
        e.id: e
        for e in db.query(Employee)
        .filter(
            Employee.id.in_([p.employee_id for p in pins]),
            Employee.company_id == caller.company_id,
        )
        .all()
    }
    trucks = {
        t.id: t
        for t in db.query(Truck)
        .filter(
            Truck.id.in_([p.truck_id for p in pins]),
            Truck.company_id == caller.company_id,
        )
        .all()
    }
    return [_to_response(p, people.get(p.employee_id), trucks.get(p.truck_id)) for p in pins]


@router.post("", response_model=list[TruckPinResponse], status_code=status.HTTP_201_CREATED)
def create_truck_pins(
    body: TruckPinCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    emp = (
        db.query(Employee)
        .filter(Employee.id == body.employee_id, Employee.company_id == caller.company_id)
        .first()
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found.")

    truck = (
        db.query(Truck)
        .filter(Truck.id == body.truck_id, Truck.company_id == caller.company_id)
        .first()
    )
    if not truck:
        raise HTTPException(status_code=404, detail="Truck not found.")

    # ADR-358 D2 — the two pin axes are mutually exclusive per person. "Follow
    # this driver" and "be on this truck" cannot both hold once the driver is
    # drawn elsewhere, and choosing a winner at dispatch time would hide a
    # contradiction the dispatcher should be told about now.
    clash = holds_crew_pin(db, caller.company_id, body.employee_id)
    if clash:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{emp.name} is already in the crew pin '{clash.name}'. A person "
                f"can be pinned to a driver or to a truck, not both."
            ),
        )

    existing_days = {
        p.day_of_week
        for p in db.query(TruckPin)
        .filter(
            TruckPin.company_id == caller.company_id,
            TruckPin.employee_id == body.employee_id,
        )
        .all()
    }
    conflict = existing_days & set(body.days)
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{emp.name} is already pinned to a truck on "
                f"{', '.join(sorted(conflict))}."
            ),
        )

    created = []
    for day in sorted(set(body.days)):
        pin = TruckPin(
            company_id=caller.company_id,
            employee_id=body.employee_id,
            truck_id=body.truck_id,
            day_of_week=day,
            created_by=caller.id,
        )
        db.add(pin)
        created.append(pin)
    db.flush()

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="truck_pin.created",
        target_table="truck_pins",
        target_id=str(created[0].id),
        detail={
            "employee_id": str(body.employee_id),
            "truck_id": str(body.truck_id),
            "days": sorted(set(body.days)),
        },
    )
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_response(p, emp, truck) for p in created]


@router.delete("/{pin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_truck_pin(
    pin_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    pin = (
        db.query(TruckPin)
        .filter(TruckPin.id == pin_id, TruckPin.company_id == caller.company_id)
        .first()
    )
    if not pin:
        raise HTTPException(status_code=404, detail="Truck pin not found.")

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="truck_pin.deleted",
        target_table="truck_pins",
        target_id=str(pin.id),
        detail={"employee_id": str(pin.employee_id), "day_of_week": pin.day_of_week},
    )
    db.delete(pin)
    db.commit()
    return None
