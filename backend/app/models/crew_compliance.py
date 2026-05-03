import uuid
from sqlalchemy import Column, Boolean, Date, DateTime, Time, ForeignKey, UniqueConstraint
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
    driver_id       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date            = Column(Date, nullable=False, index=True)
    arrival_time    = Column(Time, nullable=True)        # local time the crew member arrived at AP
    uniform_pass    = Column(Boolean, nullable=False, default=True)
    cart_cover_pass = Column(Boolean, nullable=False, default=True)
    submitted_at    = Column(DateTime(timezone=True), server_default=func.now())
