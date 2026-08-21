import uuid
from sqlalchemy import Column, String, Boolean, Date, DateTime, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base


class TruckZone(Base):
    __tablename__ = "truck_zones"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id      = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id        = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_polygon   = Column(JSONB, nullable=False)
    package_tbas    = Column(JSONB, nullable=True)   # list[str] of TBA numbers in this cluster
    tote_count      = Column(Integer, nullable=True)  # distinct totes (bag_ids) in this zone; loose packages count as 1 each
    # ADR-174: durable per-tote roster [{bag_id, tba_numbers, package_count,
    # ov_count, ov_sizes, dock_tags, ov_dock_tags}] — powers station check-off,
    # driver load lists, and printable load sheets beyond the Redis manifest TTL
    tote_roster     = Column(JSONB, nullable=True)
    zone_label      = Column(String(50), nullable=False)
    zone_date       = Column(Date, nullable=False, index=True)
    is_active       = Column(Boolean, nullable=False, default=True)
    centroid_lat    = Column(Float, nullable=True)   # mean lat of all packages in cluster
    centroid_lng    = Column(Float, nullable=True)   # mean lng of all packages in cluster
    created_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_name = Column(String(100), nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
