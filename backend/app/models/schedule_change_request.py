import uuid
from sqlalchemy import Column, String, Text, ForeignKey, DateTime, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class ScheduleChangeRequest(Base):
    """An employee's request to permanently restructure their recurring weekly schedule.

    Three modes:
    - add_day:      add one or more currently-off days back into their working week
    - drop_day:     drop one or more currently-working days (adds to employee_off_days on approval)
    - full_rework:  replace the entire recurring schedule — days_to_drop is cleared,
                    days_to_add replaces the current pattern

    On approval, the system automatically:
    - Deletes existing approved EmployeeOffDay rows that conflict with proposed changes
    - Inserts new EmployeeOffDay rows for days_to_drop / full_rework drops
    - No EmployeeOffDay row = eligible for dispatch on that day

    Attributes:
        id: Primary key UUID.
        employee_id: FK to the requesting employee.
        request_type: 'add_day' | 'drop_day' | 'full_rework'
        days_to_add: Days to remove from off-day list (make workable again).
        days_to_drop: Days to add to off-day list (stop being dispatched).
        proposed_schedule: For full_rework — the complete new working-day list.
        reason: Optional employee-provided reason.
        status: 'pending' | 'approved' | 'rejected'
        reviewed_by: FK to the reviewer (management/admin).
        created_at: Submission timestamp.
        resolved_at: Approval/rejection timestamp.
    """
    __tablename__ = "schedule_change_requests"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    request_type    = Column(String(20), nullable=False)           # add_day | drop_day | full_rework
    days_to_add     = Column(ARRAY(String), nullable=False, default=list, server_default="{}")
    days_to_drop    = Column(ARRAY(String), nullable=False, default=list, server_default="{}")
    proposed_schedule = Column(ARRAY(String), nullable=True)       # full_rework only
    reason          = Column(Text, nullable=True)
    status          = Column(String(20), nullable=False, default="pending")  # pending | approved | rejected
    reviewed_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_name = Column(String(100), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at     = Column(DateTime(timezone=True), nullable=True)
