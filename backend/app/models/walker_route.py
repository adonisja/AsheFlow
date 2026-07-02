import uuid
from sqlalchemy import Column, Integer, Date, DateTime, String, Boolean, Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.base import Base


class Route(Base):
    """One cart trip — the atomic unit of the anchor-point sort.

    Geographic identity (block_keys) is preserved here so the walker zone map
    and misroute detection can work without re-querying the Redis manifest.
    Capacity is stored in half-slot units (×2) to avoid floating-point math
    with fractional OV sizes (S=0.5 slots, L=1.5 slots).
    """
    __tablename__ = "routes"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id            = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_assignment_id   = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    route_date            = Column(Date(), nullable=False, index=True)
    route_number          = Column(Integer(), nullable=False)

    # Geographic identity — persisted so zone maps work after Redis TTL expires
    block_keys            = Column(ARRAY(Text()), nullable=False, default=list)

    # Tote and package lists
    tote_ids              = Column(ARRAY(Text()), nullable=False, default=list)
    tba_numbers           = Column(ARRAY(Text()), nullable=False, default=list)
    normalised_addresses  = Column(ARRAY(Text()), nullable=False, default=list)
    package_count         = Column(Integer(), nullable=False, default=0)

    # Capacity in half-slots (scale ×2: standard=12, heavy=8, paired=18/12)
    slot_cost             = Column(Integer(), nullable=False, default=0)
    capacity_limit        = Column(Integer(), nullable=False)
    capacity_limit_paired = Column(Integer(), nullable=True)   # set at arrival confirmation

    # Effort classification resolved at sort time from weighted package-aware score
    effort_score          = Column(Float(), nullable=True)                           # weighted normalized score snapshot
    effort_class          = Column(String(20), nullable=False, default="standard")   # easy|standard|heavy
    workload_source       = Column(String(20), nullable=False, default="default")    # profile|flag|default
    coverage_pct          = Column(Float(), nullable=True)                           # profiled_packages / total_packages

    # Person assignment — nullable until wave distribution
    assigned_to           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_to_name      = Column(String(100), nullable=True)

    # Trainer+trainee pairing
    paired_trainee_id     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    trainee_phase         = Column(Integer(), nullable=True)           # 1–5
    phase4_solo_opted_in  = Column(Boolean(), nullable=False, default=False)

    # Wave tracking — 1 = initial sort assignment; 2+ = post-return reassignment (ADR-139)
    wave_number           = Column(Integer(), nullable=False, default=1)

    # Status lifecycle
    status                = Column(String(20), nullable=False, default="unassigned")  # unassigned|assigned|in_progress|completed
    departed_at           = Column(DateTime(timezone=True), nullable=True)
    # returned_at is set ONLY by POST /back-at-truck, not by status=completed (ADR-139)
    returned_at           = Column(DateTime(timezone=True), nullable=True)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())

    misrouted_packages = relationship(
        "MisroutedPackageFlag", back_populates="route", lazy="joined", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("truck_assignment_id", "route_number", name="uq_routes_assignment_number"),
    )



class RouteClusterCentroid(Base):
    """Cluster centroids computed at sort time for the dispatch density map.

    The truck-zone sort produces per-zone centroids. Previously discarded —
    persisted here so the Deck.gl heatmap layer works without hitting Redis.
    No addresses stored — only lat/lng and package count.
    """
    __tablename__ = "route_cluster_centroids"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id           = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_assignment_id  = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    route_date           = Column(Date(), nullable=False)
    centroid_lat         = Column(Float(), nullable=False)
    centroid_lng         = Column(Float(), nullable=False)
    package_count        = Column(Integer(), nullable=False)
    truck_zone_label     = Column(String(50), nullable=True)


class LocationDifficultyFlag(Base):
    """In-field difficulty flag raised by a walker during a route.

    Ephemeral operational feedback. Flags raised during delivery cannot affect
    the same-day sort (sort runs pre-arrival at the anchor point). They override
    BuildingProfile.workload_class for subsequent sorts via the effort class
    resolution chain — highest priority input for a given block_key.

    block_key format: "W_38_St_400"  (direction_streetnum_type_hundredfloor)
    difficulty_tier: standard | moderate | heavy
    """
    __tablename__ = "location_difficulty_flags"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id      = Column(UUID(as_uuid=True), nullable=False, index=True)
    block_key       = Column(String(100), nullable=False, index=True)
    difficulty_tier = Column(String(20), nullable=False, default="standard")
    flagged_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    flagged_by_name = Column(String(100), nullable=True)
    flagged_at      = Column(DateTime(timezone=True), server_default=func.now())
    notes           = Column(Text(), nullable=True)



class MisroutedPackageFlag(Base):
    """Records a package whose block_key didn't match its tote's dominant block_key at sort time.

    The package is physically extracted from its tote and placed into the
    correct tote at the anchor point. The flag records the source route, the
    destination route (if resolvable), and the resolution status. Both the
    source walker and destination walker are notified.
    """
    __tablename__ = "misrouted_package_flags"

    id                        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id                = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_id                  = Column(UUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    tba_number                = Column(String(50), nullable=False)
    current_bag_id            = Column(String(50), nullable=False)
    destination_block_key     = Column(String(100), nullable=True)    # block_key the package actually belongs to
    suggested_route_id        = Column(UUID(as_uuid=True), nullable=True)   # null = needs captain review
    resolved                  = Column(Boolean(), nullable=False, default=False)
    resolved_by               = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_by_name          = Column(String(100), nullable=True)
    resolved_at               = Column(DateTime(timezone=True), nullable=True)

    route = relationship("Route", back_populates="misrouted_packages")
