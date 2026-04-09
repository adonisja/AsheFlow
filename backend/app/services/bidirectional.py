from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.employee_relationship import EmployeeRelationship

def perform_bidirectional_check(employee_id: UUID, target_employee_id: UUID, db: Session)->bool:
    """Check whether two employees mutually favour each other.

    Args:
        employee_id: UUID of the first employee.
        target_employee_id: UUID of the second employee.
        db: Database session.

    Returns:
        True if both employees have each other in their fav list, False otherwise.
    """
    return (
        db.query(EmployeeRelationship)
        .filter(EmployeeRelationship.relationship_type == "fav",
            or_(
                and_(EmployeeRelationship.employee_id == employee_id, EmployeeRelationship.target_employee_id == target_employee_id),
                and_(EmployeeRelationship.employee_id == target_employee_id, EmployeeRelationship.target_employee_id == employee_id)
            )
        )
    ).count() == 2