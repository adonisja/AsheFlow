"""ADR-519: a notification carries the id of the thing it is about.

Revision ID: 4a63452a4f96
Revises: cd501a1d7bd2
"""
from alembic import op
import sqlalchemy as sa

revision = "4a63452a4f96"
down_revision = "cd501a1d7bd2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: rows written before ADR-519 have none and open their page.
    op.add_column("notifications", sa.Column("target_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "target_id")
