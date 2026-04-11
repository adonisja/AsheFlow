from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.employee_relationship import EmployeeRelationship
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.truck import Truck


def _fav_connection_strength(member_id: UUID, truck_id, assigned_crews: dict, db: Session) -> int:
    """Count fav relationships between member_id and their current crewmates on truck_id.

    Unidirectional and bidirectional favs both count. Bidirectional counts as 2
    (one row per direction). Higher score = more preference ties = safer to keep.
    Lower score = weakest link = safest to move.
    """
    crewmate_ids = [c["id"] for c in assigned_crews[truck_id] if c["id"] != member_id]
    if not crewmate_ids:
        return 0

    rels = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "fav",
            or_(
                and_(
                    EmployeeRelationship.employee_id == member_id,
                    EmployeeRelationship.target_employee_id.in_(crewmate_ids),
                ),
                and_(
                    EmployeeRelationship.employee_id.in_(crewmate_ids),
                    EmployeeRelationship.target_employee_id == member_id,
                ),
            ),
        )
        .all()
    )

    return len(rels)


def _move_violates_ban(member_id: UUID, target_truck_id, assigned_crews: dict, db: Session) -> bool:
    """Return True if moving member_id to target_truck_id creates a ban conflict."""
    target_crew_ids = [c["id"] for c in assigned_crews[target_truck_id]]
    if not target_crew_ids:
        return False

    ban_exists = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "ban",
            or_(
                and_(
                    EmployeeRelationship.employee_id == member_id,
                    EmployeeRelationship.target_employee_id.in_(target_crew_ids),
                ),
                and_(
                    EmployeeRelationship.employee_id.in_(target_crew_ids),
                    EmployeeRelationship.target_employee_id == member_id,
                ),
            ),
        )
        .first()
    )

    return ban_exists is not None


def _notify_dispatch(over_truck_id, under_truck_id, over_total: int, under_total: int, db: Session) -> None:
    """Send a notification to all active dispatch/management/admin employees
    when the rebalancer cannot close the crew spread due to ban constraints.

    Includes truck names so dispatchers know exactly where to intervene manually.
    """
    over_truck = db.query(Truck).filter(Truck.id == over_truck_id).first()
    under_truck = db.query(Truck).filter(Truck.id == under_truck_id).first()

    over_name = over_truck.name if over_truck and hasattr(over_truck, "name") else str(over_truck_id)
    under_name = under_truck.name if under_truck and hasattr(under_truck, "name") else str(under_truck_id)

    message = (
        f"Crew rebalancing could not close the staffing gap between "
        f"Truck {over_name} ({over_total} members) and Truck {under_name} "
        f"({under_total} members). All movable crew members are ban-blocked from "
        f"the under-staffed truck. Manual reassignment required."
    )

    dispatch_employees = (
        db.query(Employee)
        .filter(
            Employee.role.in_(["dispatch", "management", "admin"]),
            Employee.is_active == True,
        )
        .all()
    )

    for emp in dispatch_employees:
        db.add(Notification(
            employee_id=emp.id,
            type="rebalance_intervention_required",
            message=message,
        ))

    db.flush()


def rebalance_crews(assigned_crews: dict, db: Session, tolerance: int = 2) -> list:
    """Post-assignment rebalancing to enforce a max total-crew spread across trucks.

    Candidates eligible for relocation:
    - Walkers
    - Trainers with NO paired trainee (trainer:trainee bonds are never broken)

    Excluded from relocation:
    - Drivers (define truck identity)
    - Trainees (always follow their paired trainer; never moved independently)
    - Trainers who have a paired trainee on the same truck

    If no safe move is possible (all candidates ban-blocked), a notification is
    sent to all active dispatch/management/admin employees with truck names and
    the size delta, then the imbalance is accepted.

    Args:
        assigned_crews: Dict mapping truck_id to list of crew dicts
            ``{"id": UUID, "role": str, "paired_trainer_id": UUID (trainees only)}``.
            Modified in place.
        db: Database session.
        tolerance: Maximum allowed spread between most- and least-staffed trucks.
            Defaults to 2.

    Returns:
        A list of move dicts for logging:
        ``{"employee_id": ..., "role": ..., "from_truck": ..., "to_truck": ...}``
    """
    moves = []
    max_iterations = len(assigned_crews) * 10
    iterations = 0

    while iterations < max_iterations:
        iterations += 1

        totals = {truck_id: len(crew) for truck_id, crew in assigned_crews.items()}
        max_total = max(totals.values())
        min_total = min(totals.values())

        if max_total - min_total <= tolerance:
            break

        over_truck = max(totals, key=lambda t: totals[t])
        under_truck = min(totals, key=lambda t: totals[t])

        # Build set of trainer IDs on the over-staffed truck that have a paired trainee.
        bonded_trainer_ids = {
            m["paired_trainer_id"]
            for m in assigned_crews[over_truck]
            if m["role"] == "trainee" and m.get("paired_trainer_id")
        }

        # Eligible candidates: not driver, not trainee, not a bonded trainer.
        candidates = [
            c for c in assigned_crews[over_truck]
            if c["role"] not in ("driver", "trainee")
            and not (c["role"] == "trainer" and c["id"] in bonded_trainer_ids)
        ]
        candidates.sort(
            key=lambda c: _fav_connection_strength(c["id"], over_truck, assigned_crews, db)
        )

        moved = False
        for candidate in candidates:
            if _move_violates_ban(candidate["id"], under_truck, assigned_crews, db):
                continue

            assigned_crews[over_truck].remove(candidate)
            assigned_crews[under_truck].append(candidate)

            moves.append({
                "employee_id": candidate["id"],
                "role": candidate["role"],
                "from_truck": over_truck,
                "to_truck": under_truck,
            })
            moved = True
            break

        if not moved:
            # No safe move — notify dispatch and accept the imbalance.
            _notify_dispatch(over_truck, under_truck, totals[over_truck], totals[under_truck], db)
            break

    return moves
