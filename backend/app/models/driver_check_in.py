import uuid
from sqlalchemy import Column, Integer, Boolean, Date, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class DriverCheckIn(Base):
    """Structured mid-shift check-in submitted by the driver during the route.

    Drivers submit 4 check-ins per shift at rough intervals:
      1 — ~11:15 AM
      2 — ~2:00 PM
      3 — ~4:00 PM
      4 — ~5:30 PM

    Each check-in captures current route status and crew status so dispatch
    can monitor progress and identify trucks that need support.
    """
    __tablename__ = "driver_check_ins"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", "check_in_number", name="uq_driver_check_ins_driver_date_num"),
        CheckConstraint("check_in_number BETWEEN 1 AND 4", name="ck_driver_check_ins_number"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date                = Column(Date, nullable=False, index=True)
    check_in_number     = Column(Integer, nullable=False)          # 1, 2, 3, or 4
    routes_remaining    = Column(Integer, nullable=False)          # packages/stops still to complete
    help_requested      = Column(Boolean, nullable=False, default=False)
    working_crew_count  = Column(Integer, nullable=False)          # how many crew are still working
    ncns_count          = Column(Integer, nullable=False, default=0)  # no-call no-show count
    submitted_at        = Column(DateTime(timezone=True), server_default=func.now())
