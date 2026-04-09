from uuid import UUID

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

    fan_list = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.employee_id.in_(crew_to_truck.keys()),
            EmployeeRelationship.target_employee_id == candidate_id,
            EmployeeRelationship.relationship_type == "fav"
        ).all()
    )

    fans_by_truck = {}

    for rel in fan_list:
        truck_id = crew_to_truck[rel.employee_id]
        fans_by_truck.setdefault(truck_id, []).append(rel.employee_id)

    return fans_by_truck