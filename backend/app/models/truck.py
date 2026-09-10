from sqlalchemy import Column, String, Boolean, BigInteger, Float, DateTime, UniqueConstraint, ForeignKey, Index, text
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
            Feeds run_sort._resolve_anchors() — authoritative territory seed (ADR-169).
        initial_anchor_set_by/at: Audit trail for who last set the anchor.
        amazon_anchor_lat/lng: Amazon's printed reference anchor for this truck — the
            IDENTIFIER used to resolve a BTR sheet to a truck (ADR-410 D1). Static per
            truck, unlike the per-day BTRSheet.amazon_anchor_*. NOT a territory seed:
            run_sort never reads it (ADR-410 D2).
    """
    __tablename__ = "trucks"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id         = Column(UUID(as_uuid=True), nullable=False, index=True)
    name               = Column(String(100),        nullable=False, index=True)
    is_active          = Column(Boolean,            nullable=False, default=True, index=True)
    # ADR-274: a hub is a KIND of truck, not a status a truck is in. Hubs are
    # excluded from run_dispatch — crew is placed on them by hand for intra-day
    # assembly. INDEPENDENT of is_active: a hub is an active truck that is simply
    # not auto-assignable.
    #
    # This replaces the ADR-125 inference (`status == 'planned'`), which matched
    # EVERY truck before publish and put a "Publish Hub" button on all of them.
    is_hub             = Column(Boolean,            nullable=False,
                                default=False, server_default="false", index=True)
    discord_channel_id = Column(BigInteger,         nullable=True)

    # Anchor point 1 — primary dispatch-configured territory seed.
    # GeoClient-normalised address stored; display_address preserves raw user input.
    # Feeds K-Means cold-start when no TruckZone history exists.
    initial_anchor_address          = Column(String(300), nullable=True)
    initial_anchor_display_address  = Column(String(300), nullable=True)
    initial_anchor_lat              = Column(Float,       nullable=True)
    initial_anchor_lng              = Column(Float,       nullable=True)
    initial_anchor_set_by           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    initial_anchor_set_at           = Column(DateTime(timezone=True), nullable=True)

    # Anchor point 2 — optional secondary territory seed for trucks that split
    # across two geographically distinct sub-zones. When set, K-Means receives
    # two seeds for this truck (K increments by 1), so both sub-zones can be
    # assigned to this truck if the package distribution supports it.
    initial_anchor2_address         = Column(String(300), nullable=True)
    initial_anchor2_display_address = Column(String(300), nullable=True)
    initial_anchor2_lat             = Column(Float,       nullable=True)
    initial_anchor2_lng             = Column(Float,       nullable=True)
    initial_anchor2_set_by          = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    initial_anchor2_set_at          = Column(DateTime(timezone=True), nullable=True)

    # Amazon's printed anchor — an IDENTIFIER, not a territory seed (ADR-410).
    #
    # Distinct from initial_anchor_* in kind, not just in value: that one is OUR
    # chosen anchor, entered as an address and geocoded, and it seeds sort
    # territory as priority 1 of run_sort._resolve_anchors(). This one is a
    # constant Amazon prints on the BTR sheet, entered as raw coordinates, read
    # only by the BTR ingest resolver. Writing Amazon's value into the other
    # column would silently repoint every truck's territory.
    #
    # Matched on a 5dp-rounded key, never by raw float equality (ADR-410 D3).
    amazon_anchor_lat     = Column(Float, nullable=True)
    amazon_anchor_lng     = Column(Float, nullable=True)
    amazon_anchor_set_by  = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    amazon_anchor_set_at  = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_trucks_company_name"),
        # PARTIAL: most trucks never register an Amazon anchor, and many NULL rows
        # must coexist. Uniqueness is what makes a resolver match unambiguous —
        # without it two trucks could claim one anchor (ADR-410 D3).
        Index(
            "uq_trucks_company_amazon_anchor",
            "company_id", "amazon_anchor_lat", "amazon_anchor_lng",
            unique=True,
            postgresql_where=text("amazon_anchor_lat IS NOT NULL"),
        ),
    )
