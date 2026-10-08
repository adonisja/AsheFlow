"""notice templates and schedules (ADR-488)

Two tables for recurring reminders scheduled against the tenant's own clock.
Platform-seeded and tenant-authored notices share both, per ADR-488 D1 — a
special-cased built-in is a second code path that drifts from the one admins use.

Revision ID: f3c49b344868
Revises: c717f49fbae6
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f3c49b344868"
down_revision = "c717f49fbae6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notice_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False, server_default="tenant"),
        sa.Column("seed_key", sa.String(64), nullable=True),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("body", sa.String(280), nullable=False),
        sa.Column("anchor", sa.String(32), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("at_local", sa.Time(), nullable=True),
        sa.Column("condition", sa.String(48), nullable=False, server_default="always"),
        sa.Column("audience", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("anchor <> 'fixed_local' OR at_local IS NOT NULL",
                           name="ck_notice_fixed_local_needs_time"),
        sa.CheckConstraint("origin IN ('platform', 'tenant')", name="ck_notice_origin"),
    )
    op.create_index("ix_notice_templates_company_id", "notice_templates", ["company_id"])
    op.create_index("ix_notice_templates_is_active", "notice_templates", ["is_active"])
    # Partial unique: one platform notice per seed_key per tenant, which is what
    # makes the backfill idempotent. Tenant notices (seed_key NULL) unconstrained.
    op.create_index(
        "uq_notice_seed_per_company", "notice_templates", ["company_id", "seed_key"],
        unique=True, postgresql_where=sa.text("seed_key IS NOT NULL"),
    )

    op.create_table(
        "notice_schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notice_id", UUID(as_uuid=True),
                  sa.ForeignKey("notice_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        # Nullable, unlike campaign_schedules.ends_on: a PLATFORM notice anchored
        # to shift_end should not expire. The constraint below binds "every
        # schedule ends" to tenant notices only (ADR-488 D11).
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("ended_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fired_on", sa.Date(), nullable=True),
        sa.Column("fired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeat_after_minutes", sa.Integer(), nullable=True),
        sa.Column("max_fires_per_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "mode IN ('daily', 'weekly_fixed', 'weekly_random', 'monthly')",
            name="ck_notice_schedule_mode"),
        sa.CheckConstraint("mode <> 'weekly_fixed' OR weekday IS NOT NULL",
                           name="ck_notice_weekly_needs_weekday"),
        sa.CheckConstraint("max_fires_per_day >= 1", name="ck_notice_fires_positive"),
        sa.CheckConstraint(
            "max_fires_per_day = 1 OR repeat_after_minutes IS NOT NULL",
            name="ck_notice_repeat_needs_interval"),
    )
    op.create_index("ix_notice_schedules_company_id", "notice_schedules", ["company_id"])
    op.create_index("ix_notice_schedules_notice_id", "notice_schedules", ["notice_id"])
    op.create_index("ix_notice_schedules_fired_on", "notice_schedules", ["fired_on"])

    # The tenant-must-end rule needs both tables, so it is added after the second.
    # Expressed as a trigger-free constraint by denormalising origin? No — a
    # cross-table CHECK is not portable, so this one is enforced in the service
    # layer and pinned by a test. Recorded here so the absence is deliberate
    # rather than forgotten: see services/notices.py and ADR-488 D11.


def downgrade() -> None:
    op.drop_index("ix_notice_schedules_fired_on", table_name="notice_schedules")
    op.drop_index("ix_notice_schedules_notice_id", table_name="notice_schedules")
    op.drop_index("ix_notice_schedules_company_id", table_name="notice_schedules")
    op.drop_table("notice_schedules")
    op.drop_index("uq_notice_seed_per_company", table_name="notice_templates")
    op.drop_index("ix_notice_templates_is_active", table_name="notice_templates")
    op.drop_index("ix_notice_templates_company_id", table_name="notice_templates")
    op.drop_table("notice_templates")
