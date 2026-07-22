import uuid
from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class CheckInDeadline(Base):
    """One configured driver check-in with its deadline (ADR-228).

    Replaces the flat CompanyConfig.driver_checkin_count. `sequence` is the
    check-in number (1..N, contiguous). `offset_minutes` is the deadline expressed
    as minutes past the attendance reference max(shift_start, AP-established) —
    the SAME anchor as CompanyConfig.ncns_cutoff_minutes (ADR-198), so:
      - Check-In #1 auto-shifts later on an Amazon/station-fault late-AP day
        (the reference rises), inheriting the same allowance NCNS already has.
      - the setup guard is a direct offset comparison (seq-1 offset >= NCNS;
        each offset strictly greater than the previous).
    The admin UI shows the resulting clock time (shift_start + offset) as a helper
    label but the stored value is the offset.
    """
    __tablename__ = "check_in_deadlines"
    __table_args__ = (
        UniqueConstraint("company_id", "sequence", name="uq_check_in_deadline_company_sequence"),
    )

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id     = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence       = Column(Integer, nullable=False)   # 1..N, contiguous
    offset_minutes = Column(Integer, nullable=False)   # minutes past max(shift_start, AP-established)
    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
