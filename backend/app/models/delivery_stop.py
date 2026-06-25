import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func
from app.models.base import Base


class DeliveryStop(Base):
    """One completed address stop recorded by the walker mid-route.

    The stop identity is (route_id, normalised_address) — one row per building
    entrance per route. tba_numbers lists every package at that address.

    Outcome counts (rts_count, missing_count, packages_delivered) are computed
    server-side at creation time by joining RTSPackage and MissingPackage rows
    for the same (route_id, normalised_address). A reconcile endpoint re-runs
    this computation when RTS is recorded after the stop tap.

    effort_class and workload_class are snapshotted at completion time so
    analytics queries are not affected by subsequent profile changes.
    """
    __tablename__ = "delivery_stops"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id           = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_id             = Column(UUID(as_uuid=True), ForeignKey("routes.id",            ondelete="CASCADE"), nullable=False, index=True)
    truck_assignment_id  = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False)
    walker_id            = Column(UUID(as_uuid=True), ForeignKey("employees.id",         ondelete="SET NULL"), nullable=True)
    walker_name          = Column(String(100), nullable=True)

    normalised_address   = Column(String(200), nullable=False)
    block_key            = Column(String(100), nullable=False)
    tba_numbers          = Column(ARRAY(String(50)), nullable=False, default=list)

    completed_at         = Column(DateTime(timezone=True), nullable=False)
    stop_sequence        = Column(Integer(), nullable=False)

    packages_total       = Column(Integer(), nullable=False)
    packages_delivered   = Column(Integer(), nullable=False)
    rts_count            = Column(Integer(), nullable=False, server_default="0")
    missing_count        = Column(Integer(), nullable=False, server_default="0")

    effort_class         = Column(String(20), nullable=False)
    workload_class       = Column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("route_id", "normalised_address", name="uq_delivery_stops_route_address"),
    )
