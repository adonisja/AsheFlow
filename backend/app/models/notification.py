import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type        = Column(String(50), nullable=False)
    message     = Column(Text, nullable=False)
    is_read     = Column(Boolean, nullable=False, default=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    # Populated only for type='dispatch_assignment' — tells the frontend
    # which date to POST /dispatch/{date}/confirmations against.
    dispatch_date = Column(Date, nullable=True)
