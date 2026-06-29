"""add initial anchor point fields to building_profiles

Revision ID: a4b5c6d7e8f9
Revises: z3a4b5c6d7e8
Create Date: 2026-06-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = 'a4b5c6d7e8f9'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('building_profiles', sa.Column('initial_anchor_lat',  sa.Float(), nullable=True))
    op.add_column('building_profiles', sa.Column('initial_anchor_lng',  sa.Float(), nullable=True))
    op.add_column('building_profiles', sa.Column('initial_anchor_note', sa.String(200), nullable=True))
    op.add_column('building_profiles', sa.Column('initial_anchor_set_by',      PG_UUID(as_uuid=True), nullable=True))
    op.add_column('building_profiles', sa.Column('initial_anchor_set_by_name', sa.String(100), nullable=True))
    op.add_column('building_profiles', sa.Column('initial_anchor_set_at',      sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('building_profiles', 'initial_anchor_set_at')
    op.drop_column('building_profiles', 'initial_anchor_set_by_name')
    op.drop_column('building_profiles', 'initial_anchor_set_by')
    op.drop_column('building_profiles', 'initial_anchor_note')
    op.drop_column('building_profiles', 'initial_anchor_lng')
    op.drop_column('building_profiles', 'initial_anchor_lat')
