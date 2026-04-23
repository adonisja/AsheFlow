"""Anchor point model.

An anchor point (AP) is the location where a truck parks at end-of-day.
Each truck has a configured default AP. After completing their route, the driver
posts the actual AP and their ETA — this feeds into the next morning's dispatch
planning and is confirmable by dispatch.

One record per truck per date (the driver's EOD submission).
Dispatch confirmation is stored on the same row (confirmed_by, confirmed_at).
"""

import uuid
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class AnchorPoint(Base):
    """EOD anchor point submission by driver, confirmable by dispatch.

    Attributes:
        id:             Primary key UUID.
        truck_id:       FK to trucks — which truck this AP belongs to.
        driver_id:      FK to employees — the driver who submitted.
        date:           The dispatch date this AP is for.
        location:       Free-text location description (e.g. "143-17 Guy Brewer Blvd").
        eta:            Driver's estimated time of arrival at the AP (HH:MM, free text).
        notes:          Optional additional context (e.g. "parked in lot B").
        submitted_at:   Timestamp of driver submission.
        confirmed_by:   FK to employees — dispatch/admin who confirmed the AP (nullable).
        confirmed_at:   Timestamp of dispatch confirmation (nullable until confirmed).
    """
    __tablename__ = "anchor_points"
    __table_args__ = (
        UniqueConstraint("truck_id", "date", name="uq_anchor_points_truck_date"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id     = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"),    nullable=False, index=True)
    driver_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date         = Column(Date,               nullable=False, index=True)
    location     = Column(String(255),        nullable=False)
    eta          = Column(String(20),         nullable=True)   # e.g. "4:30 PM"
    notes        = Column(Text,               nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    confirmed_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
