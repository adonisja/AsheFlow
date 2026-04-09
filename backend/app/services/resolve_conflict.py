from uuid import UUID

from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship

from sqlalchemy import and_

def resolve_conflict(employee_id: UUID, conflict_ids: tuple, db: Session)-> UUID:
    """Resolve a tie-break when a candidate has fans on multiple eligible trucks.

    Picks the truck whose driver or trainer is already in the candidate's fav
    list, giving priority by iteration order.

    Args:
        employee_id: UUID of the candidate employee being assigned.
        conflict_ids: Sequence of ``(truck_id, driver_or_trainer_id)`` tuples
            representing the competing trucks and their key crew member.
        db: Database session.

    Returns:
        The truck_id of the preferred truck, or None if no preference is found.
    """
    fav_list = (
        db.query(EmployeeRelationship, Employee.role)
        .join(Employee, Employee.id == EmployeeRelationship.target_employee_id)
        .filter(
            and_(EmployeeRelationship.employee_id == employee_id, EmployeeRelationship.relationship_type == "fav", Employee.role.in_(["driver", "trainer"]))
        ).all()
    )

    fav_ids = {rel.target_employee_id for rel, role in fav_list}

    for truck_id, driver_id in conflict_ids:
        if driver_id in fav_ids:
            return truck_id
        
    return None