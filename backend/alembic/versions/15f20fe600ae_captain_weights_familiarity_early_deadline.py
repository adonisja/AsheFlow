"""ADR-256: captain dispatch weight, truck familiarisation, early deadline

Three changes in one migration deliberately — each alters company_configs, and
splitting them means three ALTERs and three chances for the head to move under
another agent mid-flight.

1. company_configs.dispatch_weight_captain   — a captain's fan pull (0.50)
2. company_configs.captain_truck_rotation_days — days on one truck before rotating
3. company_configs.early_confirmation_deadline — earlier cutoff for driver+captain
4. captain_truck_familiarity                 — the per-captain-per-truck visited set

BACKFILL, and why it is not a no-op: dispatch_weight_trainer/_walker move to
0.25/0.15 at the PLATFORM DEFAULT level, but a platform default only covers an
unset value. Every existing tenant has a STORED 0.50/0.30 (they are in
_REQUIRED_FIELDS, so they cannot be null), and those are left untouched on
purpose — silently reweighting a live dispatch is not a migration's job. Tenants
adopt the new trainer/walker weights by clearing or editing their own config.

The new columns are nullable and NOT added to _REQUIRED_FIELDS: a null there
raises 503 for the whole company, which would take every tenant offline between
deploy and backfill.

Revision ID: 15f20fe600ae
Revises: 86b2aec7998f
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "15f20fe600ae"
down_revision = "86b2aec7998f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── company_configs ───────────────────────────────────────────────────────
    op.add_column("company_configs", sa.Column("dispatch_weight_captain", sa.Float(), nullable=True))
    op.add_column("company_configs", sa.Column("captain_truck_rotation_days", sa.Integer(), nullable=True))
    op.add_column("company_configs", sa.Column("early_confirmation_deadline", sa.Time(), nullable=True))

    op.create_check_constraint(
        "ck_company_configs_weight_captain",
        "company_configs",
        "dispatch_weight_captain IS NULL OR (dispatch_weight_captain BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_company_configs_captain_rotation_days",
        "company_configs",
        "captain_truck_rotation_days IS NULL OR captain_truck_rotation_days > 0",
    )

    # Backfill the two captain settings for every configured tenant so the values
    # are visible and editable in the config UI rather than sitting invisibly null.
    #
    # early_confirmation_deadline is deliberately left NULL: it is a TIME, and there
    # is no correct value to invent for a tenant whose shift starts at an hour this
    # migration cannot know. Null falls back to checkin_close, which is exactly what
    # driver confirmations used before this column existed — so the default is "no
    # behaviour change" rather than a guessed clock time.
    op.execute(
        "UPDATE company_configs SET dispatch_weight_captain = 0.50 "
        "WHERE dispatch_weight_captain IS NULL"
    )
    op.execute(
        "UPDATE company_configs SET captain_truck_rotation_days = 5 "
        "WHERE captain_truck_rotation_days IS NULL"
    )

    # ── captain_truck_familiarity ─────────────────────────────────────────────
    op.create_table(
        "captain_truck_familiarity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("truck_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("days_held", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_held_at", sa.Date(), nullable=True),
        sa.Column("last_held_at", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("employee_id", "truck_id", name="uq_captain_truck_familiarity"),
        sa.CheckConstraint("days_held >= 0", name="ck_captain_familiarity_days_nonneg"),
    )
    op.create_index("ix_captain_truck_familiarity_company_id", "captain_truck_familiarity", ["company_id"])
    op.create_index("ix_captain_truck_familiarity_employee_id", "captain_truck_familiarity", ["employee_id"])
    op.create_index("ix_captain_truck_familiarity_truck_id", "captain_truck_familiarity", ["truck_id"])


def downgrade() -> None:
    op.drop_index("ix_captain_truck_familiarity_truck_id", table_name="captain_truck_familiarity")
    op.drop_index("ix_captain_truck_familiarity_employee_id", table_name="captain_truck_familiarity")
    op.drop_index("ix_captain_truck_familiarity_company_id", table_name="captain_truck_familiarity")
    op.drop_table("captain_truck_familiarity")

    op.drop_constraint("ck_company_configs_captain_rotation_days", "company_configs", type_="check")
    op.drop_constraint("ck_company_configs_weight_captain", "company_configs", type_="check")
    op.drop_column("company_configs", "early_confirmation_deadline")
    op.drop_column("company_configs", "captain_truck_rotation_days")
    op.drop_column("company_configs", "dispatch_weight_captain")
