import uuid

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, Integer, String,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base


class RouteSortRun(Base):
    """One immutable record of a commit-sort decision (ADR-273).

    WHY THIS EXISTS
    `Route` records what the algorithm PRODUCED. Nothing recorded what it was
    given or why it chose. The tuning inputs (crew_size, the seed weights, the
    capacity table) lived only as arguments inside one function call, so a
    question like "were Tuesday's routes bad because of the algorithm, the crew
    size, or an odd manifest?" could not be answered from the database at all.

    NEVER DELETED ON RE-SORT
    commit-sort deletes prior Route rows for the truck assignment before writing
    new ones (idempotent re-sort). That is correct operationally and fatal
    analytically — the morning's decision is overwritten by the afternoon's. This
    table is append-only instead: a re-sort writes run_seq=2 alongside run_seq=1,
    which also makes re-sort frequency itself a metric.

    RETENTION
    Holds block_keys, counts, and histograms — no address, no TBA, no employee
    name. Deliberately outside the ADR-219 48h address nulling and the 3-year
    FLSA operational purge, because annual and seasonal baselines are the point.
    See ADR-273 "Retention".
    """
    __tablename__ = "route_sort_runs"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    # NO FOREIGN KEY, deliberately. `clear_daily_dispatch` (ADR-182/231) deletes
    # the TruckAssignment for a date, and an ondelete=CASCADE here would take the
    # decision history with it — destroying precisely the append-only record this
    # table exists to keep. The id is retained as a plain reference for joins.
    #
    # This is the same reasoning as Route.sort_run_id pointing the other way: the
    # telemetry outlives every operational row it describes.
    truck_assignment_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_date          = Column(Date(), nullable=False, index=True)
    # 1 for the first sort of this truck-day, 2+ for each re-sort.
    run_seq             = Column(Integer(), nullable=False, default=1)

    # ── what code ran ────────────────────────────────────────────────────────
    # The column that makes "did the change help?" a GROUP BY instead of a
    # recollection. Bump on every algorithm change worth comparing across.
    algorithm_version   = Column(String(40), nullable=False)

    # ── tuning inputs, AS ACTUALLY PASSED ────────────────────────────────────
    # Not as configured — the two diverge via defaults, fallbacks, and the
    # try/except paths that silently degrade (segment_adjacency, stop_cutoffs).
    crew_size           = Column(Integer(), nullable=True)
    paired_route_count  = Column(Integer(), nullable=False, default=0)
    t_factor            = Column(Float(), nullable=False)
    p_factor            = Column(Float(), nullable=False)
    # Seed-priority weights (ADR-186 W_*), resolved from CompanyConfig or default.
    w_dense             = Column(Float(), nullable=True)
    w_time              = Column(Float(), nullable=True)
    w_diff              = Column(Float(), nullable=True)
    w_doorman           = Column(Float(), nullable=True)
    # Traversal guards (ADR-235) in force for this run.
    walk_budget_m       = Column(Float(), nullable=True)
    span_cap_m          = Column(Float(), nullable=True)
    # Sizes of the reference dicts, NOT their contents — a zero here explains a
    # cold-start run where W_TIME/W_DIFF were structurally dead.
    urgency_blocks      = Column(Integer(), nullable=False, default=0)
    workload_blocks     = Column(Integer(), nullable=False, default=0)
    boundary_present    = Column(Boolean(), nullable=False, default=False)

    # ── shape of the input ───────────────────────────────────────────────────
    totes_in            = Column(Integer(), nullable=False, default=0)
    blocks_in           = Column(Integer(), nullable=False, default=0)
    packages_in         = Column(Integer(), nullable=False, default=0)
    # {"1": 3, "2": 14, "3": 16, ...} — totes per block. Explains why a route
    # could not fill: 6 tote-slots against blocks of 3-4 rarely divides evenly.
    block_group_sizes   = Column(JSONB(), nullable=True)

    # ── shape of the output (the ADR-272 metrics) ────────────────────────────
    routes_out          = Column(Integer(), nullable=False, default=0)
    # A block LISTED on more than one route. NOTE: this is block PRESENCE,
    # not tote dominance — see sort_telemetry's 'TWO DEFINITIONS OF SPLIT'.
    blocks_split        = Column(Integer(), nullable=False, default=0)
    # A block on a route with no adjacency to any sibling block on that route.
    orphan_blocks       = Column(Integer(), nullable=False, default=0)
    runt_routes         = Column(Integer(), nullable=False, default=0)
    capacity_util_pct   = Column(Float(), nullable=True)
    # {"1": 22, "2": 11, "3": 1} — the acceptance criterion of ADR-272.
    blocks_per_route_hist = Column(JSONB(), nullable=True)
    # {"group_complete": 18, "no_adjacent_fit": 9, ...} — which constraint binds.
    closed_reason_hist  = Column(JSONB(), nullable=True)

    created_at          = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "truck_assignment_id", "route_date", "run_seq",
            name="uq_route_sort_runs_assignment_date_seq",
        ),
        # The rollup scans one company-day at a time.
        Index("ix_route_sort_runs_company_date", "company_id", "route_date"),
    )


class RouteSortDaily(Base):
    """One rolled-up row per company per truck per COMPLETED day (ADR-273).

    Follows the stats_series (ADR-271) pattern deliberately: slim immutable
    daily rows, with weekly / monthly / annual computed as GROUPINGS on read
    rather than as three more tables. Three pre-aggregated tables would need
    three invalidation paths and would disagree with each other within a
    quarter.

    COMPLETED DAYS ONLY
    Today's numbers are in flight, so a row written for today is wrong within
    minutes. Excluding it makes each row immutable once written, which is what
    makes it safe to cache with no staleness policy.

    Plan-vs-actual lives here: the algorithm's PREDICTION (effort_class,
    capacity_limit) sits beside what actually happened (route duration, RTS,
    help requests), which is the join that lets a constant be tuned from
    evidence.
    """
    __tablename__ = "route_sort_daily"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    # No FK for the same reason as RouteSortRun.truck_assignment_id: retiring a
    # truck must not erase the months of tuning history recorded against it.
    # truck_name is denormalised so a retired truck's rows stay readable.
    truck_id            = Column(UUID(as_uuid=True), nullable=True)
    truck_name          = Column(String(50), nullable=True)
    route_date          = Column(Date(), nullable=False, index=True)

    # Which algorithm produced this day (from the LAST run of the day — the one
    # the crew actually worked). Null when no sort run was recorded.
    algorithm_version   = Column(String(40), nullable=True)
    sort_runs           = Column(Integer(), nullable=False, default=0)   # re-sort count

    # ── composition (from the final RouteSortRun) ────────────────────────────
    routes              = Column(Integer(), nullable=False, default=0)
    blocks_split        = Column(Integer(), nullable=False, default=0)
    orphan_blocks       = Column(Integer(), nullable=False, default=0)
    runt_routes         = Column(Integer(), nullable=False, default=0)
    blocks_per_route_avg = Column(Float(), nullable=True)
    blocks_per_route_hist = Column(JSONB(), nullable=True)
    capacity_util_pct   = Column(Float(), nullable=True)

    # ── plan vs actual (joined from Route / DeliveryStop) ────────────────────
    packages            = Column(Integer(), nullable=False, default=0)
    stops               = Column(Integer(), nullable=False, default=0)
    # departed_at -> returned_at, averaged over routes that recorded both.
    route_minutes_avg   = Column(Float(), nullable=True)
    route_minutes_p90   = Column(Float(), nullable=True)
    routes_timed        = Column(Integer(), nullable=False, default=0)
    # Per effort class: {"easy": {"routes": 4, "minutes_avg": 180.0,
    #                             "rts": 3, "packages": 210}, ...}
    # Every rate MUST be read per class — outcome_signals measured RTS at 2.10%
    # easy against 10.81% heavy, so an unnormalised comparison ranks whoever drew
    # the hard work as worst.
    by_effort_class     = Column(JSONB(), nullable=True)

    rts_total           = Column(Integer(), nullable=False, default=0)
    missing_total       = Column(Integer(), nullable=False, default=0)
    help_requests       = Column(Integer(), nullable=False, default=0)

    created_at          = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "truck_id", "route_date",
            name="uq_route_sort_daily_company_truck_date",
        ),
        Index("ix_route_sort_daily_company_date", "company_id", "route_date"),
    )
