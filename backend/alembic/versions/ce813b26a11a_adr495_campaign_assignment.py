"""ADR-495 D3: an open campaign is assigned to one company, once.

Revision ID: ce813b26a11a
Revises: 4b26674f3cba
"""
from alembic import op
import sqlalchemy as sa

revision = "ce813b26a11a"
down_revision = "4b26674f3cba"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("collection_tokens",
                  sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    # The super admin's id. No FK: a platform principal has no Employee row.
    op.add_column("collection_tokens",
                  sa.Column("assigned_by", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("collection_tokens", "assigned_by")
    op.drop_column("collection_tokens", "assigned_at")
