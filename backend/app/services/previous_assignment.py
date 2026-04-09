from uuid import UUID

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.models.assignment_member import AssignmentMember
from app.models.truck_assignment import TruckAssignment


def check_consecutive_assignment(employee_id: UUID, truck_id: UUID, db: Session) -> bool:
    """Determine whether an employee's most recent assignment was on the given truck.

    Args:
        employee_id: UUID of the employee to check.
        truck_id: UUID of the truck to compare against.
        db: Database session.

    Returns:
        True if the employee's last recorded assignment was on ``truck_id``,
        False if it was a different truck or the employee has no prior assignments.
    """

    previous_assignment = (
        db.query(TruckAssignment.truck_id)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(AssignmentMember.employee_id == employee_id)
        .order_by(TruckAssignment.date.desc())
        .first()
    )

    return truck_id == previous_assignment.truck_id if previous_assignment else False