from sqlalchemy import Column, String, Boolean, BigInteger, Float, DateTime, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base
import uuid


class Truck(Base):
    """ORM model for a delivery truck.

    Attributes:
        id: Primary key UUID.
        name: Unique truck name within a company (not globally).
        is_active: Whether the truck is currently in service and eligible for dispatch.
        discord_channel_id: Snowflake ID of the truck's Discord channel. Used by the
            bot to post finalized crew assignments and manage per-day channel access.
        initial_anchor_address: Human-readable address dispatch entered (e.g. "34 St & 9 Ave").
        initial_anchor_lat/lng: GeoClient-resolved coordinates from initial_anchor_address.
            Feeds run_sort._get_anchor_hints() on cold start (no historical zones).
        initial_anchor_set_by/at: Audit trail for who last set the anchor.
    """
    __tablename__ = "trucks"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id         = Column(UUID(as_uuid=True), nullable=False, index=True)
    name               = Column(String(100),        nullable=False, index=True)
    is_active          = Column(Boolean,            nullable=False, default=True, index=True)
    discord_channel_id = Column(BigInteger,         nullable=True)

    # Initial anchor point — dispatch-configured home territory seed for this truck.
    # Entered as a street address; backend geocodes to lat/lng via GeoClient.
    # initial_anchor_address: GeoClient-normalised canonical form (stored, used by sort).
    # initial_anchor_display_address: raw user input, preserved for display only.
    # Feeds assign_clusters cold-start centroid synthesis when no TruckZone history exists.
    initial_anchor_address          = Column(String(300), nullable=True)
    initial_anchor_display_address  = Column(String(300), nullable=True)
    initial_anchor_lat              = Column(Float,       nullable=True)
    initial_anchor_lng              = Column(Float,       nullable=True)
    initial_anchor_set_by           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    initial_anchor_set_at           = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_trucks_company_name"),
    )
