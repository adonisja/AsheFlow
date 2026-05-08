import uuid
from sqlalchemy import Column, String, Date, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class AssignmentChangeRequest(Base):
    """A walker or trainer's request to be reassigned to a different truck on a given date.

    Submitted by the employee, reviewed by dispatch/management/admin.
    Approved requests trigger a manual swap via the existing dispatch swap endpoint.
    Rejected requests are silent to the employee beyond status visibility.

    Attributes:
        id: Primary key UUID.
        employee_id: FK to the requesting employee (walker or trainer).
        requested_date: The dispatch date for which the reassignment is requested.
        reason: Optional free-text reason provided by the employee.
        status: One of 'pending', 'approved', 'rejected'.
        reviewed_by: FK to the employee (dispatch/mgmt/admin) who reviewed it.
        created_at: When the request was submitted.
        resolved_at: When the request was approved or rejected.
    """
    __tablename__ = "assignment_change_requests"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_date = Column(Date, nullable=False, index=True)
    reason        = Column(Text, nullable=True)
    status        = Column(String(20), nullable=False, default="pending")  # pending | approved | rejected
    reviewed_by   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at   = Column(DateTime(timezone=True), nullable=True)
