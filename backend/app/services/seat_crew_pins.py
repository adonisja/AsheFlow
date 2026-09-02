"""Seat pinned crews onto their driver's truck (ADR-357).

Runs between assign_drivers and assign_captains. That position is the whole
mechanism: the driver's truck is known by then, and every later pass already
skips trucks whose slots are filled — assign_walkers recomputes walker_counts
after every placement and only considers minimum-count trucks, and the
one-per-truck passes skip a truck that already has a captain or trainer.

So a pinned member simply appears on the truck before their own pass runs, and
the existing distribution logic absorbs them. No capacity handling belongs here.
"""
import logging
from collections import defaultdict
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.crew_pin import CrewPin, CrewPinMember
from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship

logger = logging.getLogger(__name__)

# Roles a truck may hold only one of. A pinned member of these roles cannot be
# seated onto a truck whose slot is already taken by a manual assignment.
_ONE_PER_TRUCK = frozenset({"captain", "driver"})


def seat_crew_pins(
    assigned_crews: dict,
    available_pool: dict,
    db: Session,
    company_id: UUID,
) -> list:
    """Place pinned members on their driver's truck and remove them from the pool.

    Mutates `assigned_crews` and the lists inside `available_pool`.

    Returns:
        Warnings, in the shape the rest of run_dispatch uses.
    """
    warnings: list = []

    pins = (
        db.query(CrewPin)
        .filter(CrewPin.company_id == company_id, CrewPin.is_active.is_(True))
        .all()
    )
    if not pins:
        return warnings

    # Where each driver landed. Drivers run first, so this is complete.
    driver_to_truck = {
        str(m["id"]): truck_id
        for truck_id, crew in assigned_crews.items()
        for m in crew
        if m.get("role") == "driver"
    }

    # Everyone still awaiting placement, by id, so a seated member can be pulled
    # out of the pool their own pass will iterate.
    pool_by_id: dict = {}
    for role_key, employees in available_pool.items():
        for emp in employees:
            pool_by_id[str(emp.id)] = (role_key, emp)

    for pin in pins:
        truck_id = driver_to_truck.get(str(pin.driver_id))

        if truck_id is None:
            # ADR-357 D2 — the anchor is absent, so the pin is inactive TODAY.
            # Not nullified: the driver is off shift, not in conflict with anyone.
            # Promoting another member to anchor would land the crew on a truck
            # nobody chose, which is worse than not honouring the pin.
            warnings.append({
                "type": "crew_pin_driver_absent",
                "pin_id": str(pin.id),
                "message": (
                    f"Crew pin '{pin.name}' was not applied — its driver is not "
                    f"dispatched today. Its members were assigned normally."
                ),
            })
            continue

        crew = assigned_crews[truck_id]
        seated_here = {str(m["id"]) for m in crew}

        for member in pin.members:
            emp_id = str(member.employee_id)

            entry = pool_by_id.get(emp_id)
            if entry is None:
                # Not available today (off shift, inactive, or already placed by
                # hand). Silent: an absent member is ordinary, unlike an absent
                # anchor which disables the whole pin.
                continue
            role_key, emp = entry

            if emp_id in seated_here:
                continue

            # ADR-357 D5 — a ban outranks a pin. A pin is an operational
            # convenience a dispatcher asserted about other people; a ban is a
            # working-relationship signal a person asserted about themselves.
            if _banned_from(db, emp.id, crew, company_id):
                warnings.append({
                    "type": "crew_pin_ban_conflict",
                    "pin_id": str(pin.id),
                    "employee_id": emp_id,
                    "message": (
                        f"{emp.name} is pinned to crew '{pin.name}' but has a ban "
                        f"involving that truck's crew. They were assigned normally."
                    ),
                })
                continue

            if emp.role in _ONE_PER_TRUCK and any(
                m.get("role") == emp.role for m in crew
            ):
                warnings.append({
                    "type": "crew_pin_slot_taken",
                    "pin_id": str(pin.id),
                    "employee_id": emp_id,
                    "message": (
                        f"{emp.name} is pinned to crew '{pin.name}' but that truck "
                        f"already has a {emp.role}. They were assigned normally."
                    ),
                })
                continue

            crew.append({"id": emp.id, "role": emp.role})
            seated_here.add(emp_id)

            # Remove from the pool, or their own pass places them a SECOND time.
            available_pool[role_key] = [
                e for e in available_pool[role_key] if str(e.id) != emp_id
            ]

    return warnings


def _banned_from(db: Session, employee_id: UUID, crew: list, company_id: UUID) -> bool:
    """Is there a ban in either direction between this employee and the crew?"""
    crew_ids = [m["id"] for m in crew]
    if not crew_ids:
        return False
    from sqlalchemy import and_, or_

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


def nullify_pins_for_ban(
    db: Session, company_id: UUID, employee_id: UUID, target_id: UUID
) -> list:
    """Deactivate any pin containing BOTH parties to a new ban (ADR-357 D4).

    Called when a ban is created, not at dispatch time. A pin says "these people
    work well together"; a ban says one of them no longer agrees. The ban is the
    newer, more specific signal, and the one a person actively asserted.

    Doing this at creation means the dispatcher learns immediately, rather than
    discovering at 4am that a crew silently stopped being a crew.

    The pin is marked inactive with a reason, never deleted — the roster is worth
    keeping if the conflict is resolved.

    Returns:
        The pins that were deactivated.
    """
    a, b = str(employee_id), str(target_id)

    # company_id is essential, not incidental: this runs from a relationship
    # endpoint and an unscoped query would reach another tenant's pins (Dim 1).
    pins = (
        db.query(CrewPin)
        .filter(CrewPin.company_id == company_id, CrewPin.is_active.is_(True))
        .all()
    )

    nullified = []
    for pin in pins:
        # The driver is the anchor and is NOT a member row, so both must be
        # checked — a ban between the driver and a member is the common case.
        ids = {str(pin.driver_id)} | {str(m.employee_id) for m in pin.members}
        if a in ids and b in ids:
            pin.is_active = False
            pin.inactive_reason = (
                "Deactivated automatically: a ban was created between two of its "
                "members. Resolve the ban and reactivate, or edit the crew."
            )
            nullified.append(pin)
            logger.info(
                "crew pin %s nullified by ban between %s and %s", pin.id, a, b
            )

    return nullified
