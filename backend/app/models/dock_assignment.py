import uuid
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class DockAssignment(Base):
    """Dispatch assigns a dock zone to a driver before the pre-trip inspection.

    One record per driver per date. Dispatch can update the zone by patching.
    The driver sees this on their FieldOps page so they know where to pick up
    their truck/packages at the station.
    """
    __tablename__ = "dock_assignments"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", name="uq_dock_assignments_driver_date"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date        = Column(Date, nullable=False, index=True)
    dock_zone   = Column(String(50), nullable=False)   # e.g. "A3", "Dock 7", "West Bay"
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
