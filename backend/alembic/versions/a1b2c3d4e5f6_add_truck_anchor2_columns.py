"""add secondary anchor point columns to trucks

Revision ID: a1b2c3d4e5f6
Revises: z3a4b5c6d7e8
Create Date: 2026-06-30

Adds optional anchor point 2 columns to the trucks table. When set, the sort
pipeline increments K by 1 for that truck, allowing K-Means to produce two
clusters (one per anchor) for trucks that cover two geographically distinct
sub-zones.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'a1b2c3d4e5f6'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trucks', sa.Column('initial_anchor2_address',          sa.String(300), nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor2_display_address',  sa.String(300), nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor2_lat',              sa.Float(),     nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor2_lng',              sa.Float(),     nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor2_set_by',           UUID(as_uuid=True), nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor2_set_at',           sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('trucks', 'initial_anchor2_set_at')
    op.drop_column('trucks', 'initial_anchor2_set_by')
    op.drop_column('trucks', 'initial_anchor2_lng')
    op.drop_column('trucks', 'initial_anchor2_lat')
    op.drop_column('trucks', 'initial_anchor2_display_address')
    op.drop_column('trucks', 'initial_anchor2_address')
