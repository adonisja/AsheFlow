"""add ADP integration tables and CompanyConfig escalation thresholds

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2026-06-11

ADR-133: ADP RUN integration — employee import, timecard reconciliation,
mismatch resolution, offboarding.

New tables:
  - adp_integrations         (per-company ADP connection config)
  - adp_pay_periods          (cached ADP pay period schedule)
  - adp_timecards            (cached ADP timecard header per employee/day)
  - adp_timecard_segments    (work segments for each timecard)
  - flex_timesheets          (Amazon Flex break records per employee/day)
  - timecard_adjustments     (mismatch correction audit trail)

CompanyConfig additions:
  - adp_urgent_correction_day     (default 6 = Sunday)
  - adp_mandatory_correction_hour (default 12 = noon)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "g8h9i0j1k2l3"
down_revision = "f7g8h9i0j1k2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── adp_integrations ──────────────────────────────────────────────────────
    op.create_table(
        "adp_integrations",
        sa.Column("id",                    UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",            UUID(as_uuid=True), nullable=False),
        sa.Column("adp_client_id",         sa.String(200),     nullable=False),
        sa.Column("adp_client_secret_arn", sa.String(2048),    nullable=False),
        sa.Column("adp_certificate_arn",   sa.String(2048),    nullable=False),
        sa.Column("adp_environment",       sa.String(20),      nullable=False, server_default="sandbox"),
        sa.Column("last_employee_sync_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_timecard_sync_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pay_period_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_enabled",  sa.Boolean(),               nullable=False, server_default="false"),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",  sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", name="uq_adp_integrations_company"),
        sa.CheckConstraint("adp_environment IN ('sandbox', 'production')", name="ck_adp_integrations_environment"),
    )
    op.create_index("ix_adp_integrations_company_id", "adp_integrations", ["company_id"])

    # ── adp_pay_periods ───────────────────────────────────────────────────────
    op.create_table(
        "adp_pay_periods",
        sa.Column("id",                UUID(as_uuid=True),         primary_key=True),
        sa.Column("company_id",        UUID(as_uuid=True),         nullable=False),
        sa.Column("adp_pay_period_id", sa.String(100),             nullable=False),
        sa.Column("period_start",      sa.Date(),                  nullable=False),
        sa.Column("period_end",        sa.Date(),                  nullable=False),
        sa.Column("close_deadline",    sa.DateTime(timezone=True), nullable=False),
        sa.Column("pay_date",          sa.Date(),                  nullable=False),
        sa.Column("fetched_at",        sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at",        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "period_start", name="uq_adp_pay_periods_company_start"),
    )
    op.create_index("ix_adp_pay_periods_company_id", "adp_pay_periods", ["company_id"])

    # ── adp_timecards ─────────────────────────────────────────────────────────
    op.create_table(
        "adp_timecards",
        sa.Column("id",                UUID(as_uuid=True),         primary_key=True),
        sa.Column("company_id",        UUID(as_uuid=True),         nullable=False),
        sa.Column("employee_id",       UUID(as_uuid=True),         nullable=False),
        sa.Column("adp_associate_oid", sa.String(100),             nullable=False),
        sa.Column("work_date",         sa.Date(),                  nullable=False),
        sa.Column("is_working_day",    sa.Boolean(),               nullable=False, server_default="true"),
        sa.Column("raw_payload",       JSONB,                      nullable=True),
        sa.Column("fetched_at",        sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at",        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("employee_id", "work_date", name="uq_adp_timecards_employee_date"),
    )
    op.create_index("ix_adp_timecards_company_id",  "adp_timecards", ["company_id"])
    op.create_index("ix_adp_timecards_employee_id", "adp_timecards", ["employee_id"])
    op.create_index("ix_adp_timecards_work_date",   "adp_timecards", ["work_date"])

    # ── adp_timecard_segments ─────────────────────────────────────────────────
    op.create_table(
        "adp_timecard_segments",
        sa.Column("id",            UUID(as_uuid=True),         primary_key=True),
        sa.Column("company_id",    UUID(as_uuid=True),         nullable=False),
        sa.Column("timecard_id",   UUID(as_uuid=True),         nullable=False),
        sa.Column("segment_index", sa.Integer(),               nullable=False),
        sa.Column("clock_in_at",   sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out_at",  sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["timecard_id"], ["adp_timecards.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("timecard_id", "segment_index", name="uq_adp_timecard_segments_order"),
    )
    op.create_index("ix_adp_timecard_segments_company_id",  "adp_timecard_segments", ["company_id"])
    op.create_index("ix_adp_timecard_segments_timecard_id", "adp_timecard_segments", ["timecard_id"])

    # ── flex_timesheets ───────────────────────────────────────────────────────
    op.create_table(
        "flex_timesheets",
        sa.Column("id",             UUID(as_uuid=True),         primary_key=True),
        sa.Column("company_id",     UUID(as_uuid=True),         nullable=False),
        sa.Column("employee_id",    UUID(as_uuid=True),         nullable=False),
        sa.Column("work_date",      sa.Date(),                  nullable=False),
        sa.Column("clock_in_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_out_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("break_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("break_end_at",   sa.DateTime(timezone=True), nullable=False),
        sa.Column("source",         sa.String(30),              nullable=False, server_default="manual_upload"),
        sa.Column("uploaded_by",    UUID(as_uuid=True),         nullable=True),
        sa.Column("uploaded_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["employees.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("employee_id", "work_date", name="uq_flex_timesheets_employee_date"),
        sa.CheckConstraint("source IN ('manual_upload', 'api', 'bot')", name="ck_flex_timesheets_source"),
    )
    op.create_index("ix_flex_timesheets_company_id",  "flex_timesheets", ["company_id"])
    op.create_index("ix_flex_timesheets_employee_id", "flex_timesheets", ["employee_id"])

    # ── timecard_adjustments ──────────────────────────────────────────────────
    op.create_table(
        "timecard_adjustments",
        sa.Column("id",                     UUID(as_uuid=True),         primary_key=True),
        sa.Column("company_id",             UUID(as_uuid=True),         nullable=False),
        sa.Column("employee_id",            UUID(as_uuid=True),         nullable=False),
        sa.Column("pay_period_id",          UUID(as_uuid=True),         nullable=False),
        sa.Column("flex_timesheet_id",      UUID(as_uuid=True),         nullable=False),
        sa.Column("adp_timecard_id",        UUID(as_uuid=True),         nullable=False),
        sa.Column("work_date",              sa.Date(),                  nullable=False),
        sa.Column("mismatch_description",   sa.String(500),             nullable=False),
        sa.Column("proposed_break_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed_break_end_at",   sa.DateTime(timezone=True), nullable=False),
        sa.Column("status",       sa.String(20), nullable=False, server_default="pending_employee"),
        sa.Column("urgency",      sa.String(20), nullable=False, server_default="routine"),
        sa.Column("is_post_close", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("employee_signed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manager_approved_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("manager_id",             UUID(as_uuid=True),         nullable=True),
        sa.Column("adp_applied_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("adp_response_payload",   JSONB,                      nullable=True),
        sa.Column("detected_at",            sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at",             sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["employee_id"],       ["employees.id"],       ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pay_period_id"],     ["adp_pay_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["flex_timesheet_id"], ["flex_timesheets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["adp_timecard_id"],   ["adp_timecards.id"],   ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manager_id"],        ["employees.id"],       ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('pending_employee', 'pending_manager', 'approved', 'applied', 'rejected')",
            name="ck_timecard_adjustment_status",
        ),
        sa.CheckConstraint(
            "urgency IN ('routine', 'urgent', 'mandatory')",
            name="ck_timecard_adjustment_urgency",
        ),
    )
    op.create_index("ix_timecard_adjustments_company_id",  "timecard_adjustments", ["company_id"])
    op.create_index("ix_timecard_adjustments_employee_id", "timecard_adjustments", ["employee_id"])

    # ── company_configs — ADP escalation thresholds ───────────────────────────
    op.add_column("company_configs", sa.Column("adp_urgent_correction_day",    sa.Integer(), nullable=False, server_default="6"))
    op.add_column("company_configs", sa.Column("adp_mandatory_correction_hour", sa.Integer(), nullable=False, server_default="12"))


def downgrade() -> None:
    # Remove company_configs columns first — no dependencies
    op.drop_column("company_configs", "adp_mandatory_correction_hour")
    op.drop_column("company_configs", "adp_urgent_correction_day")

    # Drop in reverse dependency order:
    # timecard_adjustments references pay_periods, flex_timesheets, timecards → drop first
    op.drop_table("timecard_adjustments")
    # flex_timesheets and adp_timecard_segments have no dependents among new tables
    op.drop_table("flex_timesheets")
    op.drop_table("adp_timecard_segments")
    # adp_timecards must come after segments (segments FK → timecards)
    op.drop_table("adp_timecards")
    # adp_pay_periods must come after timecard_adjustments (already dropped)
    op.drop_table("adp_pay_periods")
    # adp_integrations has no FKs to other new tables — drop last
    op.drop_table("adp_integrations")
