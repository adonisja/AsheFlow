"""Seat truck-pinned employees on their truck (ADR-358).

Runs immediately before assign_drivers — earlier than crew pins, because a pinned
DRIVER must be on their truck rather than drawn onto one.

That ordering is only safe because assign_drivers now filters out trucks that
already have a driver. It did not: it iterated every truck and appended
unconditionally, so seating any driver beforehand would have produced two drivers
on one truck (ADR-358 D3).
"""
import logging
from datetime import date
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship
from app.models.truck_pin import TruckPin

logger = logging.getLogger(__name__)

_ONE_PER_TRUCK = frozenset({"captain", "driver"})


def seat_truck_pins(
    assigned_crews: dict,
    available_pool: dict,
    db: Session,
    company_id: UUID,
    target_date: date,
) -> list:
    """Place employees pinned to a truck for this weekday.

    Mutates `assigned_crews` and the lists inside `available_pool`.
    """
    warnings: list = []

    # strftime("%A") is what EmployeeOffDay stores and what available_pool
    # compares against; the pin column is normalised to the same form on write.
    day_name = target_date.strftime("%A")

    pins = (
        db.query(TruckPin)
        .filter(
            TruckPin.company_id == company_id,
            TruckPin.day_of_week == day_name,
        )
        .all()
    )
    # A pin that does not name today is INERT and silent (D5). Warning about it
    # would train the reader to ignore pin warnings — the mechanism that matters
    # for the cases below.
    if not pins:
        return warnings

    pool_by_id: dict = {}
    for role_key, employees in available_pool.items():
        for emp in employees:
            pool_by_id[str(emp.id)] = (role_key, emp)

    for pin in pins:
        truck_key = str(pin.truck_id)
        if truck_key not in assigned_crews:
            # Truck not running today. Not a misconfiguration — a pin binds a
            # person to a truck, it does not reserve the truck.
            continue

        entry = pool_by_id.get(str(pin.employee_id))
        if entry is None:
            continue
        role_key, emp = entry

        crew = assigned_crews[truck_key]

        if any(str(m["id"]) == str(emp.id) for m in crew):
            continue

        # ADR-357 D5, carried forward: ban > pin > preference.
        if _banned_from(db, emp.id, crew, company_id):
            warnings.append({
                "type": "truck_pin_ban_conflict",
                "employee_id": str(emp.id),
                "truck_id": truck_key,
                "message": (
                    f"{emp.name} is pinned to this truck on {day_name} but has a ban "
                    f"involving its crew. They were assigned normally."
                ),
            })
            continue

        if emp.role in _ONE_PER_TRUCK and any(m.get("role") == emp.role for m in crew):
            # Two people pinned into one slot is a configuration error the
            # dispatcher must see, not something to resolve arbitrarily.
            warnings.append({
                "type": "truck_pin_slot_taken",
                "employee_id": str(emp.id),
                "truck_id": truck_key,
                "message": (
                    f"{emp.name} is pinned to this truck on {day_name} but it already "
                    f"has a {emp.role}. They were assigned normally."
                ),
            })
            continue

        crew.append({"id": emp.id, "role": emp.role})
        # Remove from the pool, or their own pass places them a SECOND time.
        available_pool[role_key] = [
            e for e in available_pool[role_key] if str(e.id) != str(emp.id)
        ]

    return warnings


def _banned_from(db: Session, employee_id: UUID, crew: list, company_id: UUID) -> bool:
    """Is there a ban in either direction between this employee and the crew?"""
    crew_ids = [m["id"] for m in crew]
    if not crew_ids:
        return False
    return (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.company_id == company_id,
            EmployeeRelationship.relationship_type == "ban",
            or_(
                and_(
                    EmployeeRelationship.employee_id == employee_id,
                    EmployeeRelationship.target_employee_id.in_(crew_ids),
                ),
                and_(
                    EmployeeRelationship.employee_id.in_(crew_ids),
                    EmployeeRelationship.target_employee_id == employee_id,
                ),
            ),
        )
        .first()
        is not None
    )
