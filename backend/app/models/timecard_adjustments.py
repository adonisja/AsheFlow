from sqlalchemy import Column, String, Date, DateTime, Boolean, CheckConstraint, UniqueConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import Base
import uuid


class TimeCardAdjustment(Base):
    __tablename__ = "timecard_adjustments"
    __table_args__ = (
        CheckConstraint("status IN ('pending_employee', 'pending_manager', 'approved', 'applied', 'rejected')", name="ck_timecard_adjustment_status"),
        CheckConstraint("urgency IN ('routine', 'urgent', 'mandatory')", name="ck_timecard_adjustment_urgency"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    pay_period_id = Column(UUID(as_uuid=True), ForeignKey("adp_pay_periods.id", ondelete="RESTRICT"), nullable=False)
    flex_timesheet_id = Column(UUID(as_uuid=True), ForeignKey("flex_timesheets.id", ondelete="RESTRICT"), nullable=False)
    adp_timecard_id = Column(UUID(as_uuid=True), ForeignKey("adp_timecards.id", ondelete="RESTRICT"), nullable=False)
    work_date = Column(Date, nullable=False)
    mismatch_description = Column(String(500), nullable=False)
    proposed_break_start_at = Column(DateTime(timezone=True), nullable=False)
    proposed_break_end_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="pending_employee")
    urgency = Column(String(20), nullable=False, default="routine")
    is_post_close = Column(Boolean, nullable=False)
    employee_signed_off_at = Column(DateTime(timezone=True), nullable=True)
    manager_approved_at = Column(DateTime(timezone=True), nullable=True)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    adp_applied_at = Column(DateTime(timezone=True), nullable=True)
    adp_response_payload = Column(JSONB, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())