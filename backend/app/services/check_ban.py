"""Hard co-assignment blocks: employee bans and dispatch separations (ADR-361).

Two kinds of block, identical in effect and different in authorship:

  ``ban``  an employee's own statement: I will not work with this person.
  ``sep``  a dispatcher's decision to keep two people apart, invisible to both.

They are enforced together everywhere. ``BLOCKING_TYPES`` is the single place
that says so — a site filtering on the literal ``"ban"`` silently pairs a
separated pair, which is the one failure this feature exists to prevent, so
every enforcement site imports this rather than spelling the strings out.
"""
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.employee_relationship import EmployeeRelationship

# Relationship types that hard-block co-assignment. Import this; do not inline.
BLOCKING_TYPES: tuple[str, ...] = ("ban", "sep")


def check_ban_relationship(
    employee1_id: UUID,
    employee2_id: UUID,
    db: Session,
    company_id: UUID | None = None,
) -> bool:
    """True if these two must not be co-assigned, in either direction.

    Covers both a ban and a dispatch separation (ADR-361): the caller wants to
    know whether the pairing is allowed, not who forbade it.

    Args:
        employee1_id: UUID of the first employee.
        employee2_id: UUID of the second employee.
        db: Database session.
        company_id: Caller's company. Optional only so existing callers keep
            working; always pass it. Without it this reads across tenants, which
            is how it shipped originally (ADR-361 fixes it here).

    Returns:
        True if either employee has banned the other, or dispatch has separated
        them.
    """
    filters = [
        EmployeeRelationship.relationship_type.in_(BLOCKING_TYPES),
        or_(
            and_(
                EmployeeRelationship.employee_id == employee1_id,
                EmployeeRelationship.target_employee_id == employee2_id,
            ),
            and_(
                EmployeeRelationship.employee_id == employee2_id,
                EmployeeRelationship.target_employee_id == employee1_id,
            ),
        ),
    ]
    if company_id is not None:
        filters.append(EmployeeRelationship.company_id == company_id)

    ban_exists = db.query(EmployeeRelationship).filter(*filters).exists()

    return db.query(ban_exists).scalar()
