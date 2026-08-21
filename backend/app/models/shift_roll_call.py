import uuid
from sqlalchemy import Column, String, Boolean, Date, DateTime, Text, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class ShiftRollCall(Base):
    """Single canonical attendance record per crew member per day.

    Written by a driver or trainer at station before departure. Status is
    derived from wall-clock time vs CompanyConfig.shift_start at write time
    and is immutable after that — dispatch overrides update the row in place
    via updated_by_id.

    status values:
      "early"   — submitted before shift_start
      "present" — submitted within the late window after shift_start
      "late"    — submitted after the late window
      "ncns"    — explicitly marked no-call no-show; triggers training record
                  lock, pairing void, capacity revert, and Discord revocation

    confirmed: requires a deliberate second tap from driver/trainer/dispatch
    before the record is considered finalised for reporting.
    """
    __tablename__ = "shift_roll_calls"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_shift_roll_calls_employee_date"),
        CheckConstraint("status IN ('early', 'present', 'late', 'ncns')", name="ck_shift_roll_calls_status"),
    )

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    submitted_by_id  = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_id      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date             = Column(Date, nullable=False, index=True)
    status           = Column(String(10), nullable=False)
    notes            = Column(Text, nullable=True)
    submitted_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())
    updated_by_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    confirmed        = Column(Boolean, nullable=False, default=False)
    confirmed_at     = Column(DateTime(timezone=True), nullable=True)
