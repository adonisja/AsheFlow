from sqlalchemy import Column, String, Integer, Date, DateTime, Boolean, CheckConstraint, UniqueConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import Base
import uuid


class TimeCardAdjustment(Base):
    __tablename__ = "timecard_adjustments"
    __table_args__ = (
        CheckConstraint("status IN ('pending_employee', 'pending_manager', 'approved', 'applied', 'write_failed', 'rejected' )", name="ck_timecard_adjustment_status"),
        CheckConstraint("urgency IN ('routine', 'urgent', 'mandatory')", name="ck_timecard_adjustment_urgency"),
        CheckConstraint(
            "finding_type IS NULL OR finding_type IN ("
            "'break_time_mismatch', 'break_missing_in_adp', "
            "'break_short_in_adp', 'entry_missing_in_adp')",
            name="ck_timecard_adjustment_finding_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    pay_period_id = Column(UUID(as_uuid=True), ForeignKey("adp_pay_periods.id", ondelete="RESTRICT"), nullable=False)
    flex_timesheet_id = Column(UUID(as_uuid=True), ForeignKey("flex_timesheets.id", ondelete="RESTRICT"), nullable=False)
    adp_timecard_id = Column(UUID(as_uuid=True), ForeignKey("adp_timecards.id", ondelete="RESTRICT"), nullable=False)
    work_date = Column(Date, nullable=False)
    # timeEntries[].entryID captured at detection — the write payload addresses
    # the correction by it, and the read is the only place it can be obtained.
    # Opaque ADP string ("8672975228284578|1"), never parsed. Nullable: a finding
    # for a day where ADP has no entry at all (entry_missing_in_adp) has no
    # entryID to correct (ADR-233).
    adp_entry_id = Column(String(64), nullable=True)
    # What kind of ADP/Flex disagreement this is. Drives operational routing —
    # what a manager does about a missing break differs from a shifted one — not
    # compliance reporting, which is ADP's (ADR-233).
    #   break_time_mismatch  both have a break, windows differ >5 min
    #   break_missing_in_adp Flex has a qualifying break, ADP's breaks[] is empty
    #   break_short_in_adp   Flex >=30 min, ADP's break is shorter
    #   entry_missing_in_adp Flex working day, ADP has no timeEntries at all
    # Nullable: rows predating this column carry no type.
    finding_type = Column(String(40), nullable=True, index=True)
    mismatch_description = Column(String(500), nullable=False)
    proposed_break_start_at = Column(DateTime(timezone=True), nullable=False)
    proposed_break_end_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="pending_employee")
    write_attempt_count = Column(Integer, nullable=False, default=0)
    is_retryable = Column(Boolean, nullable=False, default=True)
    urgency = Column(String(20), nullable=False, default="routine")
    is_post_close = Column(Boolean, nullable=False, default=False)
    employee_signed_off_at = Column(DateTime(timezone=True), nullable=True)
    manager_approved_at = Column(DateTime(timezone=True), nullable=True)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    adp_applied_at = Column(DateTime(timezone=True), nullable=True)
    adp_response_payload = Column(JSONB, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())