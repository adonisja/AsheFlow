"""ADR-332: captains summary message receipt

Revision ID: d2f99487115b
Revises: 85c5d62abc6f
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa

revision = "d2f99487115b"
down_revision = "85c5d62abc6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dispatch_day_summaries",
        sa.Column("captains_summary_message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dispatch_day_summaries", "captains_summary_message_id")
