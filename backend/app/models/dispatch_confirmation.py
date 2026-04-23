from sqlalchemy import Column, String, Date, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class DispatchConfirmation(Base):
    """Persistent record of an employee's confirmation response for a dispatch date.

    Redis stores ephemeral state (fast reads, 48h TTL).
    This table is the durable audit trail — used for analytics and history.

    Constraints:
    - One record per employee per date (upserted on status change).
    - status must be one of: pending, confirmed, declined.
    - source tracks how the confirmation was recorded (discord_bot or manual).

    Attributes:
        id:           Primary key UUID.
        employee_id:  FK to employees. Cascades on delete.
        date:         The dispatch date this confirmation applies to.
        status:       Current status — pending / confirmed / declined.
        confirmed_at: Timestamp of the last status change (NULL while pending).
        source:       Who/what recorded the confirmation.
        created_at:   Row creation timestamp (when seeded as pending).
    """
    __tablename__ = "dispatch_confirmations"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_dispatch_confirmation_employee_date"),
        CheckConstraint("status IN ('pending', 'confirmed', 'declined')", name="ck_dispatch_confirmations_status"),
        CheckConstraint("source IN ('discord_bot', 'manual')", name="ck_dispatch_confirmations_source"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id  = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date         = Column(Date,               nullable=False, index=True)
    status       = Column(String(20),         nullable=False, default="pending")
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    source       = Column(String(20),         nullable=False, default="discord_bot")
    created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
