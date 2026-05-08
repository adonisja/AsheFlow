from sqlalchemy import Column, String, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class EmployeeOffDay(Base):
    """ORM model for a recurring weekly off day for an employee.

    Used by the dispatch pool query to exclude employees who are off on the
    target dispatch date.

    Constraints & Safety:
    - ``employee_id`` and ``day_of_week`` combination MUST be unique (an employee 
      can only request "Monday" off once).
    - Cascading deletes are enforced; deleting the employee deletes their off days.

    Attributes:
        id: Primary key UUID.
        employee_id: Foreign key to the employee.
        day_of_week: The day this employee is off — one of ``Monday`` through
            ``Sunday``.
    """
    __tablename__ = "employee_off_days"
    __table_args__ = (
        UniqueConstraint("employee_id", "day_of_week", name="uq_emp_off_day"),
        CheckConstraint(
            "day_of_week IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')",
            name="ck_employee_off_days_day_of_week"
        ),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_employee_off_days_status"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = Column(String(10),         nullable=False, index=True)
    status      = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
