from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.employee_relationship import EmployeeRelationship


def perform_tridirectional_check(driver_id: UUID, captain_id: UUID, walker_id: UUID, db: Session) -> bool:
    """Check whether a driver, captain, and walker all mutually favour each other.

    The trio is driver + captain + walker (ADR-353 D2). It used to be driver +
    TRAINER + walker, which made this function permanently unreachable: ADR-256
    set both `trainer→walker` and `walker→trainer` to 0, so two of the six
    required rows could never exist and `count() == 6` could never be true. The
    bonus was configurable, defaulted to 0.20, and did nothing.

    Driver, captain and walker are the three who now share a truck — the captain
    is the route lead (ADR-256 D5), while a trainer supervises their own trainee
    rather than the crew.

    All SIX directions are required. A weaker rule (four of six, say) would be
    easier to earn and much harder to reason about; six is a rare, unambiguous
    signal, which is what justifies paying double the bidirectional bonus.

    Args:
        driver_id: UUID of the driver.
        captain_id: UUID of the captain.
        walker_id: UUID of the walker.
        db: Database session.

    Returns:
        True if all six directional fav relationships exist among the three
        employees, False otherwise.
    """
    return (
        db.query(EmployeeRelationship)
        .filter(EmployeeRelationship.relationship_type == "fav",
            or_(
                and_(EmployeeRelationship.employee_id == driver_id, EmployeeRelationship.target_employee_id == captain_id),
                and_(EmployeeRelationship.employee_id == driver_id, EmployeeRelationship.target_employee_id == walker_id),
                and_(EmployeeRelationship.employee_id == captain_id, EmployeeRelationship.target_employee_id == driver_id),
                and_(EmployeeRelationship.employee_id == captain_id, EmployeeRelationship.target_employee_id == walker_id),
                and_(EmployeeRelationship.employee_id == walker_id, EmployeeRelationship.target_employee_id == driver_id),
                and_(EmployeeRelationship.employee_id == walker_id, EmployeeRelationship.target_employee_id == captain_id)
            )
        )
    ).count() == 6
