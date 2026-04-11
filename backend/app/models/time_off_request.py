import uuid
from sqlalchemy import Column, Date, String, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base

class TimeOffRequest(Base):
    __tablename__ = "time_off_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending, approved, rejected, expired

    __table_args__ = (
        CheckConstraint(status.in_(['pending', 'approved', 'rejected', 'expired']), name='valid_time_off_status'),
    )

    employee = relationship("Employee")
