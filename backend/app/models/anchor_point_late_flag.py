import uuid
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class AnchorPointLateFlag(Base):
    """One row per late-arrival event on an anchor point.

    Written the first time a preliminary AP's ETA + 15 minutes passes with
    no arrival confirmation. The unique constraint on anchor_point_id ensures
    we only flag each AP once regardless of how many times the check runs.
    """
    __tablename__ = "anchor_point_late_flags"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id      = Column(UUID(as_uuid=True), nullable=False, index=True)
    anchor_point_id = Column(UUID(as_uuid=True), ForeignKey("anchor_points.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id        = Column(UUID(as_uuid=True), ForeignKey("trucks.id",        ondelete="CASCADE"), nullable=False, index=True)
    driver_id       = Column(UUID(as_uuid=True), ForeignKey("employees.id",     ondelete="CASCADE"), nullable=False, index=True)
    date            = Column(Date,               nullable=False, index=True)
    eta             = Column(String(20),         nullable=True)
    minutes_late    = Column(Integer,            nullable=False)
    flagged_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("anchor_point_id", name="uq_anchor_point_late_flag"),
    )
