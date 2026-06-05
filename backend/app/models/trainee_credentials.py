import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class TraineeCredentials(Base):
    __tablename__ = "trainee_credentials"
    __table_args__ = (
        UniqueConstraint("employee_id", name="uq_trainee_credentials_employee"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    # Fernet-encrypted values stored as text (base64url ciphertext).
    flex_email    = Column(String, nullable=False)
    clock_in_code = Column(String, nullable=False)

    sent_by    = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    sent_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
