import uuid
from sqlalchemy import Column, String, Date, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class TruckTransfer(Base):
    __tablename__ = "truck_transfers"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id         = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    from_assignment_id = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False)
    to_assignment_id   = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False)
    transfer_date      = Column(Date, nullable=False, index=True)
    transferred_by     = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    transferred_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note               = Column(Text, nullable=True)
