from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid
from datetime import datetime, timezone


class InviteToken(Base):
    __tablename__ = "invite_tokens"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token        = Column(String(64), nullable=False, unique=True, index=True)
    company_id   = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id  = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    used         = Column(Boolean, nullable=False, default=False)
