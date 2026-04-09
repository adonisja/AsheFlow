from uuid import UUID

from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship

from sqlalchemy import and_

def get_fav_list(employee_id: UUID, db: Session)->dict:
    """Fetch all employees that a given employee has marked as a favourite, grouped by role.

    Args:
        employee_id: UUID of the employee whose fav list to retrieve.
        db: Database session.

    Returns:
        A dict with keys ``"drivers"``, ``"trainers"``, and ``"walkers"``, each
        containing a list of target employee UUIDs.
    """
    employee_list = (
        db.query(EmployeeRelationship, Employee.role)
        .join(Employee, Employee.id == EmployeeRelationship.target_employee_id)
        .filter(and_(EmployeeRelationship.employee_id == employee_id, EmployeeRelationship.relationship_type == "fav", Employee.role.in_(["driver", "trainer", "walker"])))
        .all()
    )

    fav_list = {
        "drivers": [],
        "trainers": [],
        "walkers": []
    }
    for relationship, role in employee_list:
        if role == "driver":
            fav_list["drivers"].append(relationship.target_employee_id)
        elif role == "trainer":
            fav_list["trainers"].append(relationship.target_employee_id)
        elif role == "walker":
            fav_list["walkers"].append(relationship.target_employee_id)

    return fav_list