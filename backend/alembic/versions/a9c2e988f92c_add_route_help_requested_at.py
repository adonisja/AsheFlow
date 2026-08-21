"""add route.help_requested_at (ADR-229)

Revision ID: a9c2e988f92c
Revises: f1da196d4c57
Create Date: 2026-07-23

ADR-229: persist the request-help distress signal on the route so the captain's
"cover remaining stops" emergency split can gate on it.
"""
from alembic import op
import sqlalchemy as sa


revision = "a9c2e988f92c"
down_revision = "f1da196d4c57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "routes",
        sa.Column("help_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("routes", "help_requested_at")
