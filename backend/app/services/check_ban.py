from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.employee_relationship import EmployeeRelationship

def check_ban_relationship(employee1_id: UUID, employee2_id: UUID, db: Session) -> bool:
    """Check if a ban relationship exists between two employees.

    Args:
        employee1_id: UUID of the first employee.
        employee2_id: UUID of the second employee.
        db: Database session.

    Returns:
        True if either employee has banned the other, False otherwise.
    """
    ban_exists = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "ban",
            or_(
                and_(EmployeeRelationship.employee_id == employee1_id, EmployeeRelationship.target_employee_id == employee2_id),
                and_(EmployeeRelationship.employee_id == employee2_id, EmployeeRelationship.target_employee_id == employee1_id)
            )
        )
        .exists()
    )
    
    return db.query(ban_exists).scalar()
