import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func
from app.models.base import Base


STOP_STATUSES = ("planned", "in_progress", "completed")


class DeliveryStop(Base):
    """One address stop on a route, tracked through its lifecycle (ADR-197).

    The stop identity is (route_id, normalised_address) — one row per building
    entrance per route. tba_numbers lists every package at that address.

    Lifecycle (ADR-197): rows are PRE-SEEDED as ``planned`` at route creation
    from Route.stops (ADR-194), transition to ``in_progress`` when the walker
    starts the stop (powers live walker-location tracking + per-stop duration
    telemetry), and ``completed`` when they finish. A stop delivered that was
    never planned (a mid-day misroute resolution, a late add) is created
    directly as ``completed`` with ``is_unplanned=True`` — a walker is never
    blocked from recording a real delivery.

    Completion-time fields (completed_at, packages_delivered, counts, snapshots)
    are nullable because a planned/in_progress row has not been delivered yet;
    they are populated on the completion transition. Outcome counts are computed
    server-side from RTS/missing rows; effort/workload are snapshotted at
    completion so analytics are unaffected by later profile changes.
    """
    __tablename__ = "delivery_stops"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id           = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_id             = Column(UUID(as_uuid=True), ForeignKey("routes.id",            ondelete="CASCADE"), nullable=False, index=True)
    truck_assignment_id  = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False)
    walker_id            = Column(UUID(as_uuid=True), ForeignKey("employees.id",         ondelete="SET NULL"), nullable=True)
    walker_name          = Column(String(100), nullable=True)

    # ADR-244 amendment: walker_id is the route's EXECUTOR — the walker the stop
    # belongs to, which is what get_my_performance, cross_check_scorecard and the
    # management dashboard all mean by it. recorded_by is whoever actually
    # completed it, which differs during trainer supervision and during peer
    # coverage (one walker finishing another's stop in an emergency).
    recorded_by          = Column(UUID(as_uuid=True), ForeignKey("employees.id",         ondelete="SET NULL"), nullable=True)
    recorded_by_name     = Column(String(100), nullable=True)

    normalised_address   = Column(String(200), nullable=True)   # ADR-219: nulled 48h post-route (block_key kept)
    block_key            = Column(String(100), nullable=False)
    # ADR-279: the LION segment this building sits on — the purge-durable join
    # key. NOT nulled by ADR-219: a segment id is public street topology (see
    # StreetSegment: "no house numbers, no normalised_address, no package/TBA
    # data"), the same class of fact as block_key, just more precise. It cannot
    # reconstruct a house number, which is what makes retaining it safe.
    # Null is a real answer, never "no match": GeoClient may return a street
    # with no segment topology (grc 42), and the three ad-hoc creation paths
    # (rts.py x2, package_intake.py) have no enriched package to read it from.
    segment_id           = Column(String(32), nullable=True, index=True)
    tba_numbers          = Column(ARRAY(String(50)), nullable=False, default=list)

    # Lifecycle (ADR-197)
    status               = Column(String(20), nullable=False, server_default="completed")  # planned|in_progress|completed
    is_unplanned         = Column(Boolean(), nullable=False, server_default="false")        # true = not in the seeded plan
    started_at           = Column(DateTime(timezone=True), nullable=True)                   # planned→in_progress stamp (duration telemetry)

    completed_at         = Column(DateTime(timezone=True), nullable=True)   # set on completion
    stop_sequence        = Column(Integer(), nullable=False)

    packages_total       = Column(Integer(), nullable=True)                 # known at completion
    packages_delivered   = Column(Integer(), nullable=True)
    rts_count            = Column(Integer(), nullable=False, server_default="0")
    missing_count        = Column(Integer(), nullable=False, server_default="0")

    effort_class         = Column(String(20), nullable=True)                # snapshot at completion
    workload_class       = Column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("route_id", "normalised_address", name="uq_delivery_stops_route_address"),
    )
