from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from app.models.employee_relationship import EmployeeRelationship

def get_fans(candidate_id: UUID, assigned_crews: dict, db: Session)->dict:
    """Find already-assigned crew members who have the candidate in their fav list, keyed by truck.

    Args:
        candidate_id: UUID of the employee being considered for assignment.
        assigned_crews: Mapping of truck_id to a list of crew dicts
            ``{"id": employee_id, "role": str}``.
        db: Database session.

    Returns:
        A dict mapping truck_id to a list of employee UUIDs on that truck who
        favour the candidate.
    """
    crew_to_truck = {
        crew["id"]: truck_id 
        for truck_id, crew_list in assigned_crews.items()
        for crew in crew_list
    }

    # BOTH directions count (ADR-355 D1). Previously only the first was read —
    # "who on a truck favs the candidate" — so a candidate's own favourite was
    # inert: no fan meant no boost, no tie to break, and the bidirectional check
    # never ran. Measured before the change: driver->walker placed the pair
    # together 27% of runs, walker->driver 15% against a ~17% baseline.
    fan_list = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "fav",
            or_(
                # a placed crew member favours the candidate
                and_(
                    EmployeeRelationship.employee_id.in_(crew_to_truck.keys()),
                    EmployeeRelationship.target_employee_id == candidate_id,
                ),
                # the candidate favours a placed crew member
                and_(
                    EmployeeRelationship.employee_id == candidate_id,
                    EmployeeRelationship.target_employee_id.in_(crew_to_truck.keys()),
                ),
            ),
        ).all()
    )

    fans_by_truck = {}
    pair_seen: dict = {}

    for rel in fan_list:
        # The returned id is always the one whose ROLE should weight this pull —
        # the person who EXPRESSED the preference (ADR-355 D2). Returning the
        # placed crew member in both cases would weight a walker's pick by the
        # driver's 0.70 and invert the hierarchy the weights exist to encode.
        if rel.employee_id == candidate_id:
            truck_id = crew_to_truck[rel.target_employee_id]
            expressed_by = candidate_id
        else:
            truck_id = crew_to_truck[rel.employee_id]
            expressed_by = rel.employee_id

        # ONE PAIR, ONE ENTRY (ADR-355 D3) — keyed on the PAIR, not the expressor.
        #
        # A mutual fav produces two rows with two DIFFERENT expressors, so
        # deduping by expressor keeps both: the role loop then runs twice and the
        # boosts compound. Measured on staging with a mutual driver+walker pair:
        # 2.170 instead of the intended 1.800, i.e. more pull than the
        # tridirectional bonus that is supposed to be the strongest signal.
        #
        # The placed crew member is the stable half of the pair (the candidate is
        # the other half by definition), so it is the natural key.
        other = rel.target_employee_id if rel.employee_id == candidate_id else rel.employee_id
        seen = pair_seen.setdefault(truck_id, {})
        if other in seen:
            # Already recorded from the other direction. Keep the PLACED crew
            # member's half: their role is what the boost is weighted by, and a
            # driver favouring a walker must not be downgraded to the walker's
            # weight merely because the walker favoured back. Deterministic —
            # never "whichever row the database returned first".
            if seen[other] == candidate_id and expressed_by != candidate_id:
                bucket = fans_by_truck[truck_id]
                bucket[bucket.index(candidate_id)] = expressed_by
                seen[other] = expressed_by
            continue
        seen[other] = expressed_by
        fans_by_truck.setdefault(truck_id, []).append(expressed_by)

    return fans_by_truck