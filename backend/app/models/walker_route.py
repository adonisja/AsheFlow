import uuid
from sqlalchemy import Column, Integer, Date, DateTime, String, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from app.models.base import Base


class WalkerRoute(Base):
    __tablename__ = "walker_routes"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id           = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_assignment_id  = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    route_date           = Column(Date, nullable=False, index=True)
    walker_id            = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    total_packages       = Column(Integer, nullable=False, default=0)
    total_bags           = Column(Integer, nullable=False, default=0)
    total_ovs            = Column(Integer, nullable=False, default=0)
    planned_trips        = Column(Integer, nullable=False, default=1)
    actual_trips         = Column(Integer, nullable=True)
    completed_at         = Column(DateTime(timezone=True), nullable=True)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())


class WalkerTrip(Base):
    __tablename__ = "walker_trips"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    walker_route_id  = Column(UUID(as_uuid=True), ForeignKey("walker_routes.id", ondelete="CASCADE"), nullable=False, index=True)
    trip_number      = Column(Integer, nullable=False)
    bag_ids          = Column(ARRAY(Text), nullable=False, default=list)   # e.g. ["Green 5270", "Blue 1134"]
    tba_numbers      = Column(ARRAY(Text), nullable=False, default=list)   # Amazon package identifiers
    tag_numbers      = Column(ARRAY(Text), nullable=False, default=list)   # physical yellow tag numbers
    status           = Column(String(20), nullable=False, default="pending")  # pending | in_progress | completed
    departed_at      = Column(DateTime(timezone=True), nullable=True)
    returned_at      = Column(DateTime(timezone=True), nullable=True)


class LocationDifficultyFlag(Base):
    """In-field difficulty flag raised by a walker during a route.

    Captures unexpected difficulty encountered at a block mid-delivery.
    This is ephemeral operational feedback — distinct from LocationProfile,
    which is the verified, persistent building intelligence database.

    block_key format: "W_38_St_400s_odd" (10-number range + odds/evens side)
    difficulty_tier: standard | moderate | heavy
    """
    __tablename__ = "location_difficulty_flags"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id      = Column(UUID(as_uuid=True), nullable=False, index=True)
    block_key       = Column(String(100), nullable=False, index=True)   # e.g. "W_38_St_400s_odd"
    difficulty_tier = Column(String(20), nullable=False, default="standard")  # standard | moderate | heavy
    flagged_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    flagged_by_name = Column(String(100), nullable=True)
    flagged_at      = Column(DateTime(timezone=True), server_default=func.now())
    notes           = Column(Text, nullable=True)


class MisroutedPackageFlag(Base):
    """Records a package whose address didn't match its tote's cluster at sort time."""
    __tablename__ = "misrouted_package_flags"

    id                        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id                = Column(UUID(as_uuid=True), nullable=False, index=True)
    walker_route_id           = Column(UUID(as_uuid=True), ForeignKey("walker_routes.id", ondelete="CASCADE"), nullable=False, index=True)
    tba_number                = Column(String(50), nullable=False)
    tag_number                = Column(String(50), nullable=True)
    current_bag_id            = Column(String(50), nullable=False)
    suggested_walker_route_id = Column(UUID(as_uuid=True), nullable=True)  # null = needs captain review
    resolved                  = Column(Boolean, nullable=False, default=False)
    resolved_by               = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_by_name          = Column(String(100), nullable=True)
    resolved_at               = Column(DateTime(timezone=True), nullable=True)
