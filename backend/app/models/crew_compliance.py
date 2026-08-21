import uuid
from sqlalchemy import Column, Boolean, Date, DateTime, Time, String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class CrewCompliance(Base):
    """AP compliance check recorded by the driver for each crew member at anchor point arrival.

    Captures: arrival time, uniform pass/fail, cart cover pass/fail.
    One record per (driver_id, employee_id, date) — the driver submits one record
    per crew member. Self-reporting for their own crew.
    """
    __tablename__ = "crew_compliance"
    __table_args__ = (
        UniqueConstraint("driver_id", "employee_id", "date", name="uq_crew_compliance_driver_emp_date"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    driver_id       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date            = Column(Date, nullable=False, index=True)
    arrival_time    = Column(Time, nullable=True)        # local time the crew member arrived at AP
    uniform_pass    = Column(Boolean, nullable=False, default=True)
    cart_cover_pass = Column(Boolean, nullable=False, default=True)
    # ADR-228: compliance is captured live on the Crew Roster page as a DRAFT, then
    # Check-In #1 finalizes it (draft → submitted) and notifies Dispatch. The
    # standalone POST /crew-compliance writes 'submitted' directly (corrections).
    status          = Column(String(20), nullable=False, server_default="submitted")  # draft | submitted
    submitted_at    = Column(DateTime(timezone=True), server_default=func.now())
