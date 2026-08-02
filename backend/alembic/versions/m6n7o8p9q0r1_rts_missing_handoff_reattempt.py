"""RTS packages, missing packages, route handoff, reattempt assignment, operating hours

Revision ID: m6n7o8p9q0r1
Revises: f8g9h0i1j2k3
Create Date: 2026-06-25

ADR-141 — per-package field recording, missing package lifecycle, walker→driver
handoff event, reattempt assignment, and operating hours on building profiles.

New tables:
  rts_packages               — one row per undeliverable package (walker records mid-route)
  missing_packages           — packages not found in tote (separate from RTS)
  route_handoffs             — per-route walker→driver confirmation event (back-at-truck side effect)
  reattempt_assignments      — first-class same-day reattempt lifecycle

Altered tables:
  station_handoffs           — add missing_count
  building_profiles          — add operating hours fields
  building_profile_library   — add operating hours fields
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = 'm6n7o8p9q0r1'
down_revision = 'f8g9h0i1j2k3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── rts_packages ─────────────────────────────────────────────────────────
    op.create_table(
        "rts_packages",
        sa.Column("id",                   UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",           UUID(as_uuid=True), nullable=False),
        sa.Column("route_id",             UUID(as_uuid=True), sa.ForeignKey("routes.id",             ondelete="CASCADE"), nullable=False),
        sa.Column("truck_assignment_id",  UUID(as_uuid=True), sa.ForeignKey("truck_assignments.id",  ondelete="CASCADE"), nullable=False),
        sa.Column("tba_number",           sa.String(50),  nullable=False),
        sa.Column("normalised_address",   sa.String(200), nullable=True),   # resolved from Redis at record time
        sa.Column("rts_type",             sa.String(50),  nullable=False),  # enum enforced at app layer
        sa.Column("rts_explanation",      sa.Text,        nullable=False),
        sa.Column("is_reattemptable",     sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("walker_id",            UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("walker_name",          sa.String(100), nullable=True),
        sa.Column("recorded_at",          sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rts_packages_company_id",          "rts_packages", ["company_id"])
    op.create_index("ix_rts_packages_route_id",            "rts_packages", ["route_id"])
    op.create_index("ix_rts_packages_truck_assignment_id", "rts_packages", ["truck_assignment_id"])
    op.create_index("ix_rts_packages_normalised_address",  "rts_packages", ["normalised_address"])

    # ── missing_packages ──────────────────────────────────────────────────────
    op.create_table(
        "missing_packages",
        sa.Column("id",                   UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",           UUID(as_uuid=True), nullable=False),
        sa.Column("route_id",             UUID(as_uuid=True), sa.ForeignKey("routes.id",             ondelete="CASCADE"), nullable=False),
        sa.Column("truck_assignment_id",  UUID(as_uuid=True), sa.ForeignKey("truck_assignments.id",  ondelete="CASCADE"), nullable=False),
        sa.Column("tba_number",           sa.String(50),  nullable=False),
        sa.Column("normalised_address",   sa.String(200), nullable=True),
        sa.Column("walker_id",            UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("walker_name",          sa.String(100), nullable=True),
        sa.Column("reported_at",          sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Resolution lifecycle
        sa.Column("resolution_status",    sa.String(30),  nullable=False, server_default="unresolved"),
        sa.Column("misroute_flag_id",     UUID(as_uuid=True), sa.ForeignKey("misrouted_package_flags.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution_notes",     sa.Text,        nullable=True),
        sa.Column("resolved_by",          UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by_name",     sa.String(100), nullable=True),
        sa.Column("resolved_at",          sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_missing_packages_company_id",          "missing_packages", ["company_id"])
    op.create_index("ix_missing_packages_route_id",            "missing_packages", ["route_id"])
    op.create_index("ix_missing_packages_truck_assignment_id", "missing_packages", ["truck_assignment_id"])
    op.create_index("ix_missing_packages_resolution_status",   "missing_packages", ["resolution_status"])
    op.create_index("ix_missing_packages_normalised_address",  "missing_packages", ["normalised_address"])

    # ── route_handoffs ────────────────────────────────────────────────────────
    op.create_table(
        "route_handoffs",
        sa.Column("id",                   UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",           UUID(as_uuid=True), nullable=False),
        sa.Column("route_id",             UUID(as_uuid=True), sa.ForeignKey("routes.id",             ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("truck_assignment_id",  UUID(as_uuid=True), sa.ForeignKey("truck_assignments.id",  ondelete="CASCADE"), nullable=False),
        sa.Column("walker_id",            UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("walker_name",          sa.String(100), nullable=True),
        sa.Column("driver_id",            UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("driver_name",          sa.String(100), nullable=True),
        sa.Column("rts_count",            sa.Integer, nullable=False, server_default="0"),
        sa.Column("missing_count",        sa.Integer, nullable=False, server_default="0"),
        sa.Column("rts_package_ids",      ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("driver_confirmed_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("discrepancy_flagged",  sa.Boolean, nullable=False, server_default="false"),
        sa.Column("discrepancy_notes",    sa.Text,    nullable=True),
        sa.Column("discrepancy_resolved_by",   UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("discrepancy_resolved_by_name", sa.String(100), nullable=True),
        sa.Column("discrepancy_resolved_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",           sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_route_handoffs_company_id",          "route_handoffs", ["company_id"])
    op.create_index("ix_route_handoffs_truck_assignment_id", "route_handoffs", ["truck_assignment_id"])

    # ── reattempt_assignments ─────────────────────────────────────────────────
    op.create_table(
        "reattempt_assignments",
        sa.Column("id",                   UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",           UUID(as_uuid=True), nullable=False),
        sa.Column("rts_package_id",       UUID(as_uuid=True), sa.ForeignKey("rts_packages.id",       ondelete="CASCADE"), nullable=False),
        sa.Column("truck_assignment_id",  UUID(as_uuid=True), sa.ForeignKey("truck_assignments.id",  ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_by",          UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_by_name",     sa.String(100), nullable=True),
        sa.Column("original_walker_id",   UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_walker_name", sa.String(100), nullable=True),
        sa.Column("assigned_to",          UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_to_name",     sa.String(100), nullable=True),
        sa.Column("route_id",             UUID(as_uuid=True), sa.ForeignKey("routes.id",             ondelete="SET NULL"), nullable=True),
        sa.Column("status",               sa.String(20),  nullable=False, server_default="pending"),
        sa.Column("bundle_suggested_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("cutoff_at",            sa.DateTime(timezone=True), nullable=False),  # server sets to 18:30 route_date
        sa.Column("outcome_notes",        sa.Text,        nullable=True),
        sa.Column("created_at",           sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reattempt_assignments_company_id",          "reattempt_assignments", ["company_id"])
    op.create_index("ix_reattempt_assignments_truck_assignment_id", "reattempt_assignments", ["truck_assignment_id"])
    op.create_index("ix_reattempt_assignments_status",              "reattempt_assignments", ["status"])
    op.create_index("ix_reattempt_assignments_rts_package_id",      "reattempt_assignments", ["rts_package_id"])

    # ── station_handoffs: add missing_count ───────────────────────────────────
    op.add_column("station_handoffs",
        sa.Column("missing_count", sa.Integer, nullable=False, server_default="0"))

    # ── building_profiles / library: operating hours ──────────────────────────
    #
    # Both tables are created at chain position 97 by b2c3d4e5f6a7 — FOURTEEN
    # revisions AFTER this one. On staging and prod they already existed, so
    # these ALTERs found their target; on a fresh database they do not, and
    # this failed with UndefinedTable. The guards make a from-scratch run skip
    # them, and b2c3d4e5f6a7 declares the hours columns itself, so both paths
    # converge on the same schema. See alembic/_shared/routes_ddl.py for the
    # same ordering problem on `routes`.
    _insp = sa.inspect(op.get_bind())

    if _insp.has_table("building_profiles"):
        op.add_column("building_profiles", sa.Column("opens_at",         sa.Time, nullable=True))
        op.add_column("building_profiles", sa.Column("closes_at",        sa.Time, nullable=True))
        op.add_column("building_profiles", sa.Column("break_start",      sa.Time, nullable=True))
        op.add_column("building_profiles", sa.Column("break_end",        sa.Time, nullable=True))
        op.add_column("building_profiles", sa.Column("days_open",        ARRAY(sa.String(10)), nullable=True))
        op.add_column("building_profiles", sa.Column("hours_timezone",   sa.String(50), nullable=True))
        op.add_column("building_profiles", sa.Column("hours_verified",   sa.Boolean, nullable=False, server_default="false"))
        op.add_column("building_profiles", sa.Column("hours_verified_by",   UUID(as_uuid=True),
                      sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True))
        op.add_column("building_profiles", sa.Column("hours_verified_by_name", sa.String(100), nullable=True))
        op.add_column("building_profiles", sa.Column("hours_verified_at",      sa.DateTime(timezone=True), nullable=True))

    if _insp.has_table("building_profile_library"):
        op.add_column("building_profile_library", sa.Column("opens_at",       sa.Time, nullable=True))
        op.add_column("building_profile_library", sa.Column("closes_at",      sa.Time, nullable=True))
        op.add_column("building_profile_library", sa.Column("break_start",    sa.Time, nullable=True))
        op.add_column("building_profile_library", sa.Column("break_end",      sa.Time, nullable=True))
        op.add_column("building_profile_library", sa.Column("days_open",      ARRAY(sa.String(10)), nullable=True))
        op.add_column("building_profile_library", sa.Column("hours_timezone", sa.String(50), nullable=True))
        op.add_column("building_profile_library", sa.Column("hours_verified", sa.Boolean, nullable=False, server_default="false"))
        op.add_column("building_profile_library", sa.Column("hours_verified_by",      UUID(as_uuid=True), nullable=True))
        op.add_column("building_profile_library", sa.Column("hours_verified_by_name", sa.String(100), nullable=True))
        op.add_column("building_profile_library", sa.Column("hours_verified_at",      sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Guarded for the same reason as upgrade(): on a fresh database these
    # tables are not created until fourteen revisions later.
    _insp = sa.inspect(op.get_bind())

    # building_profile_library hours
    if _insp.has_table("building_profile_library"):
        for col in ("hours_verified_at", "hours_verified_by_name", "hours_verified_by",
                    "hours_verified", "hours_timezone", "days_open",
                    "break_end", "break_start", "closes_at", "opens_at"):
            op.drop_column("building_profile_library", col)

    # building_profiles hours
    if _insp.has_table("building_profiles"):
        op.drop_column("building_profiles", "hours_verified_at")
        op.drop_column("building_profiles", "hours_verified_by_name")
        op.drop_column("building_profiles", "hours_verified_by")
        op.drop_column("building_profiles", "hours_verified")
        op.drop_column("building_profiles", "hours_timezone")
        op.drop_column("building_profiles", "days_open")
        op.drop_column("building_profiles", "break_end")
        op.drop_column("building_profiles", "break_start")
        op.drop_column("building_profiles", "closes_at")
    op.drop_column("building_profiles", "opens_at")

    # station_handoffs
    op.drop_column("station_handoffs", "missing_count")

    # new tables
    op.drop_table("reattempt_assignments")
    op.drop_table("route_handoffs")
    op.drop_table("missing_packages")
    op.drop_table("rts_packages")
