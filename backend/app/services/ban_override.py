from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.employee_relationship import EmployeeRelationship

def perform_walker_reassignment(
        walker,
        truck_id: UUID,
        assigned_crews: dict,
        base_weights: dict,
        banned_truck_ids: list,
        db: Session
) -> UUID | None:
    """Remove a walker from a truck and reassign them elsewhere.

    Strips the walker from the given truck's crew list, adds that truck to the
    walker's ban list, then re-runs ``assign_walkers`` so the walker lands on a
    different truck.

    Returns:
        The truck_id the walker was reassigned to, or None if they could not be placed.
    """
    from app.services.assign_walkers import assign_walkers

    # strip the walker from the truck's crew list before re-running assignment
    assigned_crews[truck_id] = [c for c in assigned_crews[truck_id] if c["id"] != walker.id]

    # snapshot crew sizes before reassignment so we can detect where the walker landed
    before = {tid: len(crew) for tid, crew in assigned_crews.items()}

    # add the evicting truck to the ban list so the walker can't be re-placed there
    updated_bans = banned_truck_ids + [truck_id]

    # reuse assign_walkers with a single-element list
    assign_walkers([walker], assigned_crews, base_weights, db, extra_banned_truck_ids=updated_bans)

    # find which truck grew by 1 — that's where the walker landed
    for tid, crew in assigned_crews.items():
        if len(crew) > before.get(tid, 0):
            return tid
    return None

def check_ban_override(
    candidate_id: UUID,
    offending_walker,
    truck_id: UUID,
    assigned_crews: dict,
    base_weights: dict,
    banned_truck_ids: list,
    db: Session
)-> bool:
    """Determine whether a walker ban can be overridden in favour of the candidate.

    The ban is overridden when the truck's driver or trainer favours the
    candidate but not the offending walker.  If overridden, the offending walker
    is reassigned to another truck.

    Args:
        candidate_id: UUID of the walker seeking assignment to the truck.
        offending_walker: Employee ORM object of the walker who banned the candidate.
        truck_id: UUID of the truck in question.
        assigned_crews: Dict mapping truck_id to crew list; may be mutated if
            the offending walker is reassigned.
        base_weights: Dict mapping truck_id to base weight, passed to reassignment.
        banned_truck_ids: Current ban list for the candidate, passed to reassignment.
        db: Database session.

    Returns:
        True if the ban was overridden and the offending walker was reassigned,
        False if the ban stands.
    """
    # pull the senior crew members who have authority to influence walker placement
    driver_id = next((c["id"] for c in assigned_crews[truck_id] if c["role"] == "driver"), None)
    trainer_id = next((c["id"] for c in assigned_crews[truck_id] if c["role"] == "trainer"), None)

    # can't override if neither a driver nor trainer is present to express a preference
    if not driver_id and not trainer_id:
        return False, None

    # build the OR filter dynamically in case one of the roles hasn't been filled yet
    crew_filter = [f for f in [
        EmployeeRelationship.employee_id == driver_id if driver_id else None,
        EmployeeRelationship.employee_id == trainer_id if trainer_id else None
    ] if f is not None]

    # condition 1: the truck's driver or trainer must explicitly fav the candidate
    if not (db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "fav",
            EmployeeRelationship.target_employee_id == candidate_id,
            or_(*crew_filter)
        ).first()
    ):
        return False, None

    # condition 2: the same senior crew must NOT also fav the offending walker —
    # if they like both equally, the ban stands to avoid arbitrarily displacing the existing walker
    if (db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "fav",
            EmployeeRelationship.target_employee_id == offending_walker.id,
            or_(*crew_filter)
        ).first()
    ):
        return False, None

    # both conditions met — bump the offending walker to another truck before returning True
    reassigned_to = perform_walker_reassignment(offending_walker, truck_id, assigned_crews, base_weights, banned_truck_ids, db)

    return True, reassigned_to