from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base
import uuid

class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    type = Column(String(50), nullable=False) # 'bug', 'feature_request', 'general'
    message = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default='new') # 'new', 'in_progress', 'resolved'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
