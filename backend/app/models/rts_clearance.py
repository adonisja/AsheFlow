import uuid
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base


RTS_REPORT_STATUSES = ["pending", "approved", "rejected"]


class RTSReport(Base):
    """Field RTS report — submitted by the driver before leaving the anchor point area.

    The driver confirms:
      - all crew members have returned to the truck
      - the full list of undelivered packages grouped by reason

    Dispatch reviews and approves or rejects. Driver is gated: they cannot
    leave the field until the status is 'approved'. Once approved, the driver
    heads to the station for physical handoff.

    rts_packages: [{reason: str, count: int}, ...]
    crew_confirmed: True once driver has verified all crew are back on the truck
    """
    __tablename__ = "rts_reports"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", name="uq_rts_reports_driver_date"),
    )

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date             = Column(Date, nullable=False, index=True)
    crew_confirmed   = Column(Integer, nullable=False, default=0)  # number of crew accounted for
    rts_packages     = Column(JSONB, nullable=False, default=list)  # [{reason, count}, ...]
    total_rts        = Column(Integer, nullable=False, default=0)   # denormalized sum
    status           = Column(String(20), nullable=False, default="pending")  # pending | approved | rejected
    dispatch_notes   = Column(Text, nullable=True)
    reviewed_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    submitted_at     = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at      = Column(DateTime(timezone=True), nullable=True)


class StationHandoff(Base):
    """Station handoff — submitted by the driver after physically returning RTS and totes.

    This is the closing record for the return leg. It confirms:
      - how many totes were physically returned
      - how many RTS packages were scanned/handed back in

    Can only be submitted after the driver's RTSReport for the same date
    has status='approved' (dispatch cleared them to head in).
    """
    __tablename__ = "station_handoffs"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", name="uq_station_handoffs_driver_date"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date         = Column(Date, nullable=False, index=True)
    totes_returned = Column(Integer, nullable=False, default=0)
    rts_count    = Column(Integer, nullable=False, default=0)   # physical RTS packages handed back
    notes        = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
