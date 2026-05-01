from sqlalchemy import Column, String, Boolean, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class AssignmentMember(Base):
    """ORM model for a single crew member on a truck assignment.

    Each row links one employee to one ``TruckAssignment`` with their role
    for that day.

    Constraints & Safety:
    - ``assignment_id`` and ``employee_id`` combination must be unique (an employee
      cannot be assigned to the same truck twice on the same day).
    - Cascading deletes are enforced; deleting an employee or an assignment deletes this row.

    Attributes:
        id: Primary key UUID.
        assignment_id: Foreign key to the parent ``TruckAssignment``.
        employee_id: Foreign key to the assigned employee.
        role: The employee's role for this assignment — one of ``driver``,
            ``trainer``, or ``walker``.
    """
    __tablename__ = "assignment_members"
    __table_args__ = (
        UniqueConstraint("assignment_id", "employee_id", name="uq_assignment_member"),
        CheckConstraint("role IN ('driver', 'trainer', 'trainee', 'walker')", name="ck_assignment_members_role"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),          nullable=False, index=True)
    role          = Column(String(50),         nullable=False)
    # True when a dispatch coordinator placed this member manually after the algorithm ran.
    # False (default) = algorithm-placed. Used for fill-rate analytics.
    is_manual     = Column(Boolean,            nullable=False, default=False)
