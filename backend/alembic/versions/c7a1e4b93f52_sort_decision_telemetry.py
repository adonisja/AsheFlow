"""sort decision telemetry (ADR-273)

Adds:
  route_sort_runs    — one immutable row per commit-sort, never deleted on re-sort
  route_sort_daily   — nightly rollup, completed days only
  routes.*           — four decision columns (seed_block_key, blocks_walked,
                       closed_reason, sort_run_id)
  company_configs.*  — route-sort tuning knobs, all nullable (null = code default)

Revision ID: c7a1e4b93f52
Revises: 0969fd813b6a
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c7a1e4b93f52"
down_revision = "0969fd813b6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_sort_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        # No FK: clear_daily_dispatch deletes TruckAssignments, and a CASCADE
        # would destroy the append-only decision history (ADR-273 D8 audit).
        sa.Column("truck_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_date", sa.Date(), nullable=False),
        sa.Column("run_seq", sa.Integer(), nullable=False, server_default="1"),

        sa.Column("algorithm_version", sa.String(40), nullable=False),

        sa.Column("crew_size", sa.Integer(), nullable=True),
        sa.Column("paired_route_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("t_factor", sa.Float(), nullable=False),
        sa.Column("p_factor", sa.Float(), nullable=False),
        sa.Column("w_dense", sa.Float(), nullable=True),
        sa.Column("w_time", sa.Float(), nullable=True),
        sa.Column("w_diff", sa.Float(), nullable=True),
        sa.Column("w_doorman", sa.Float(), nullable=True),
        sa.Column("walk_budget_m", sa.Float(), nullable=True),
        sa.Column("span_cap_m", sa.Float(), nullable=True),
        sa.Column("urgency_blocks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("workload_blocks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("boundary_present", sa.Boolean(), nullable=False, server_default="false"),

        sa.Column("totes_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocks_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("packages_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("block_group_sizes", postgresql.JSONB(), nullable=True),

        sa.Column("routes_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocks_split", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orphan_blocks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runt_routes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capacity_util_pct", sa.Float(), nullable=True),
        sa.Column("blocks_per_route_hist", postgresql.JSONB(), nullable=True),
        sa.Column("closed_reason_hist", postgresql.JSONB(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "truck_assignment_id", "route_date", "run_seq",
            name="uq_route_sort_runs_assignment_date_seq",
        ),
    )
    op.create_index("ix_route_sort_runs_company_id", "route_sort_runs", ["company_id"])
    op.create_index("ix_route_sort_runs_truck_assignment_id", "route_sort_runs", ["truck_assignment_id"])
    op.create_index("ix_route_sort_runs_route_date", "route_sort_runs", ["route_date"])
    op.create_index("ix_route_sort_runs_company_date", "route_sort_runs", ["company_id", "route_date"])

    op.create_table(
        "route_sort_daily",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        # No FK: retiring a truck must not erase its tuning history.
        sa.Column("truck_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("truck_name", sa.String(50), nullable=True),
        sa.Column("route_date", sa.Date(), nullable=False),

        sa.Column("algorithm_version", sa.String(40), nullable=True),
        sa.Column("sort_runs", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("routes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocks_split", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orphan_blocks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runt_routes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocks_per_route_avg", sa.Float(), nullable=True),
        sa.Column("blocks_per_route_hist", postgresql.JSONB(), nullable=True),
        sa.Column("capacity_util_pct", sa.Float(), nullable=True),

        sa.Column("packages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("route_minutes_avg", sa.Float(), nullable=True),
        sa.Column("route_minutes_p90", sa.Float(), nullable=True),
        sa.Column("routes_timed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("by_effort_class", postgresql.JSONB(), nullable=True),

        sa.Column("rts_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("help_requests", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "truck_id", "route_date",
            name="uq_route_sort_daily_company_truck_date",
        ),
    )
    op.create_index("ix_route_sort_daily_company_id", "route_sort_daily", ["company_id"])
    op.create_index("ix_route_sort_daily_route_date", "route_sort_daily", ["route_date"])
    op.create_index("ix_route_sort_daily_company_date", "route_sort_daily", ["company_id", "route_date"])

    # ── routes: decision columns (all nullable — rows predating this, and any
    # non-sort Route creation path, leave them null) ─────────────────────────
    op.add_column("routes", sa.Column("seed_block_key", sa.String(100), nullable=True))
    op.add_column("routes", sa.Column("blocks_walked", sa.Integer(), nullable=True))
    op.add_column("routes", sa.Column("closed_reason", sa.String(30), nullable=True))
    op.add_column("routes", sa.Column("sort_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_routes_sort_run_id", "routes", ["sort_run_id"])

    # ── company_configs: route-sort tuning (all nullable, null = code default,
    # deliberately NOT in _REQUIRED_FIELDS) ──────────────────────────────────
    for col, type_ in (
        ("sort_w_dense", sa.Float()),
        ("sort_w_time", sa.Float()),
        ("sort_w_diff", sa.Float()),
        ("sort_w_doorman", sa.Float()),
        ("sort_walk_budget_m", sa.Float()),
        ("sort_span_cap_m", sa.Float()),
        ("sort_max_consecutive_no_fit", sa.Integer()),
        ("sort_f5_load_floor_hs", sa.Integer()),
        ("sort_f5_max_hops", sa.Integer()),
        ("sort_f5_walk_radius_km", sa.Float()),
        ("route_assembly_mode", sa.String(20)),
    ):
        op.add_column("company_configs", sa.Column(col, type_, nullable=True))


def downgrade() -> None:
    for col in (
        "route_assembly_mode",
        "sort_f5_walk_radius_km",
        "sort_f5_max_hops",
        "sort_f5_load_floor_hs",
        "sort_max_consecutive_no_fit",
        "sort_span_cap_m",
        "sort_walk_budget_m",
        "sort_w_doorman",
        "sort_w_diff",
        "sort_w_time",
        "sort_w_dense",
    ):
        op.drop_column("company_configs", col)

    op.drop_index("ix_routes_sort_run_id", table_name="routes")
    for col in ("sort_run_id", "closed_reason", "blocks_walked", "seed_block_key"):
        op.drop_column("routes", col)

    op.drop_index("ix_route_sort_daily_company_date", table_name="route_sort_daily")
    op.drop_index("ix_route_sort_daily_route_date", table_name="route_sort_daily")
    op.drop_index("ix_route_sort_daily_company_id", table_name="route_sort_daily")
    op.drop_table("route_sort_daily")

    op.drop_index("ix_route_sort_runs_company_date", table_name="route_sort_runs")
    op.drop_index("ix_route_sort_runs_route_date", table_name="route_sort_runs")
    op.drop_index("ix_route_sort_runs_truck_assignment_id", table_name="route_sort_runs")
    op.drop_index("ix_route_sort_runs_company_id", table_name="route_sort_runs")
    op.drop_table("route_sort_runs")
