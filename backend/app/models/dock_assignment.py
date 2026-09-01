import uuid
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class DockAssignment(Base):
    """Dispatch assigns a dock zone to a driver before the pre-trip inspection.

    One record per driver per date. Dispatch can update the zone by patching.
    The driver sees this on their FieldOps page so they know where to collect
    THE VEHICLE at the station.

    NOT where the totes are staged. That is `BTRSheet.btr_loading_zone`
    ("BTR31"), a different place in the same warehouse, denormalised onto
    TruckAssignment beside this one (ADR-290 D4). An earlier version of this
    docstring said "truck/packages", which read as though this one field covered
    both — it does not, and that phrasing is what made a three-way distinction
    (dock_zone / btr_loading_zone / TruckZone.zone_label) look like a two-way
    one. See ADR-307's context section for the full table.
    """
    __tablename__ = "dock_assignments"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", name="uq_dock_assignments_driver_date"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    driver_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date        = Column(Date, nullable=False, index=True)
    dock_zone   = Column(String(50), nullable=False)   # e.g. "A3", "Dock 7", "West Bay"
    assigned_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    assigned_by_name = Column(String(100), nullable=True)
    assigned_at      = Column(DateTime(timezone=True), server_default=func.now())
