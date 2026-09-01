"""ADR-327: receipts for the day-level Discord summary posts

Revision ID: 85c5d62abc6f
Revises: 91a0f6376e5f
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "85c5d62abc6f"
down_revision = "91a0f6376e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispatch_day_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("drivers_summary_message_id", sa.BigInteger(), nullable=True),
        sa.Column("trainers_summary_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("company_id", "date",
                            name="uq_dispatch_day_summary_company_date"),
    )
    op.create_index("ix_dispatch_day_summaries_company_id",
                    "dispatch_day_summaries", ["company_id"])
    op.create_index("ix_dispatch_day_summaries_date",
                    "dispatch_day_summaries", ["date"])


def downgrade() -> None:
    op.drop_index("ix_dispatch_day_summaries_date", table_name="dispatch_day_summaries")
    op.drop_index("ix_dispatch_day_summaries_company_id", table_name="dispatch_day_summaries")
    op.drop_table("dispatch_day_summaries")
