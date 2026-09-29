"""ADR-476: a Transporter ID is the match.

Adds `employees.transporter_id` -- Amazon's stable DA identifier, the match key
for bulk scorecard import -- and `scorecard_import_pending`, where a row whose
id we do not yet recognise waits for a human to bind it.

NO BACKFILL IS POSSIBLE. The id comes from Amazon's export and nothing in our
data implies it, so every employee starts NULL and each id is bound once on
first sight. That is the intended shape: guessing the binding is the misroute
this ADR exists to prevent.

Self-contained: no import from app.*.

Revision ID: 3457b5455fff
Revises: 5b99f5189665
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "3457b5455fff"
down_revision = "5b99f5189665"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees",
                  sa.Column("transporter_id", sa.String(length=32), nullable=True))
    op.create_index("ix_employees_transporter_id", "employees", ["transporter_id"])
    # Per COMPANY, not global: the id is Amazon's, and two tenants at different
    # stations colliding is not our business to police.
    op.create_unique_constraint(
        "uq_employees_company_transporter", "employees",
        ["company_id", "transporter_id"],
    )

    op.create_table(
        "scorecard_import_pending",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("week", sa.String(length=10), nullable=False, index=True),
        sa.Column("transporter_id", sa.String(length=32), nullable=False, index=True),
        sa.Column("da_name", sa.String(length=200), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False,
                  server_default="unknown_transporter_id"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "week", "transporter_id",
                            name="uq_scorecard_import_pending_week_transporter"),
    )


def downgrade() -> None:
    """Drops both. Lossy, and said plainly: every binding made since the upgrade
    is destroyed, so the next import re-queues every id for a human again."""
    op.drop_table("scorecard_import_pending")
    op.drop_constraint("uq_employees_company_transporter", "employees", type_="unique")
    op.drop_index("ix_employees_transporter_id", table_name="employees")
    op.drop_column("employees", "transporter_id")
