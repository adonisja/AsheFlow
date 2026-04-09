from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.employee_relationship import EmployeeRelationship

def perform_tridirectional_check(driver_id: UUID, trainer_id: UUID, walker_id: UUID, db: Session)->bool:
    """Check whether a driver, trainer, and walker all mutually favour each other.

    Args:
        driver_id: UUID of the driver.
        trainer_id: UUID of the trainer.
        walker_id: UUID of the walker.
        db: Database session.

    Returns:
        True if all six directional fav relationships exist among the three employees,
        False otherwise.
    """
    return (
        db.query(EmployeeRelationship)
        .filter(EmployeeRelationship.relationship_type == "fav",
            or_(
                and_(EmployeeRelationship.employee_id == driver_id, EmployeeRelationship.target_employee_id == trainer_id),
                and_(EmployeeRelationship.employee_id == driver_id, EmployeeRelationship.target_employee_id == walker_id),
                and_(EmployeeRelationship.employee_id == trainer_id, EmployeeRelationship.target_employee_id == driver_id),
                and_(EmployeeRelationship.employee_id == trainer_id, EmployeeRelationship.target_employee_id == walker_id),
                and_(EmployeeRelationship.employee_id == walker_id, EmployeeRelationship.target_employee_id == driver_id),
                and_(EmployeeRelationship.employee_id == walker_id, EmployeeRelationship.target_employee_id == trainer_id)
            )
        )
    ).count() == 6