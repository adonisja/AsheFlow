from sqlalchemy import Column, Integer, String, Float, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.models.base import Base


class StreetSegment(Base):
    """NYC LION street topology — the routing graph's substrate (ADR-236).

    GLOBAL, not tenant-scoped (no company_id) — deliberately, like
    BuildingProfileLibrary. Street topology is a public fact about the city, not
    about a customer, so every company benefits from the next one's lookups. A
    tenant column would force redundant re-fetching per company and buy nothing.
    Tenant scoping happens at query time via the company's boundary polygon.

    Nothing tenant-derived is stored here: street name and LION ids only. No house
    numbers, no normalised_address, no package/TBA data — which is precisely what
    makes a global table safe (PII dim 7).

    Why this table exists: route adjacency is derived from segments sharing a LION
    node (ADR-196). But we only ever resolved segments for PACKAGE addresses, so
    the connecting streets were missing and the graph shattered — measured 47
    disconnected components, largest holding 6% of segments. The fix is to persist
    what each sort already resolves and additionally walk the connectors, so the
    map densifies as a write-through cache instead of a one-time batch build.
    """
    __tablename__ = "street_segments"
    __table_args__ = (
        UniqueConstraint("segment_id", name="uq_street_segments_segment_id"),
        # Bounding-box prefilter for the per-company zone fragment. PostGIS is not
        # available (postgres:15-alpine), so the fragment query filters on this
        # index then refines in Python with Shapely — the same mechanism ADR-214
        # already uses for the company boundary.
        Index("ix_street_segments_lat_lng", "lat", "lng"),
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # LION identity + topology. Two segments are adjacent iff they share a node.
    segment_id        = Column(String(32), nullable=False)
    from_lion_node_id = Column(String(32), nullable=True)
    to_lion_node_id   = Column(String(32), nullable=True)

    # Display aids (block_key is the user-facing label; never the routing key).
    street_name       = Column(String(120), nullable=True)
    borough           = Column(String(30),  nullable=True)
    block_key         = Column(String(60),  nullable=True)

    # Segment midpoint — indexed for the zone-fragment bbox prefilter.
    lat               = Column(Float, nullable=True)
    lng               = Column(Float, nullable=True)

    # How we learned about it: 'package_address' (a package resolved here) or
    # 'connector_walk' (fetched to close a gap between two cross streets).

    # ── Blockface span (ADR-314 D3 / ADR-303 D4) ─────────────────────────────
    # "this segment runs from 400 to 448 W 36th St". A property of the SEGMENT:
    # verified that three addresses on segment 0297696 all return the same
    # 000002000AA..000098000AA, so per-address storage would duplicate one fact
    # ~18 times (the measured mean addresses per block).
    low_house_number    = Column(String(20),  nullable=True)
    high_house_number   = Column(String(20),  nullable=True)
    # route_sort rebuilds cross-street adjacency per sort; the only copy today
    # lives on the ephemeral ToteAddress and is nulled each cycle.
    first_cross_street  = Column(String(100), nullable=True)
    second_cross_street = Column(String(100), nullable=True)
    # ADR-316 — the blockface's two endpoints in NY State Plane feet. Segment
    # geometry, not address geometry: three addresses on segment 0297696 all
    # return identical values, so they join from here rather than repeating on
    # every address. Their absence was the last reason a routing caller had to
    # miss the cache and call GeoClient anyway.
    x_low_address_end   = Column(Integer(), nullable=True)
    y_low_address_end   = Column(Integer(), nullable=True)
    x_high_address_end  = Column(Integer(), nullable=True)
    y_high_address_end  = Column(Integer(), nullable=True)

    source            = Column(String(20), nullable=False, server_default="package_address")

    # last_seen_at is the staleness signal: every sort re-touches its segments, so
    # refresh has a real trigger instead of an untriggered cron.
    first_seen_at     = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at      = Column(DateTime(timezone=True), server_default=func.now())
