"""Add anchor_points table.

Stores driver EOD anchor point submissions (location + ETA) per truck per date.
Dispatch can confirm each submission. Used to feed next-morning dispatch planning
and to auto-post to truck Discord channels so drivers don't need to type manually.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'a3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'anchor_points',
        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('truck_id',     postgresql.UUID(as_uuid=True), sa.ForeignKey('trucks.id',     ondelete='CASCADE'),    nullable=False),
        sa.Column('driver_id',    postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id',  ondelete='CASCADE'),    nullable=False),
        sa.Column('date',         sa.Date(),           nullable=False),
        sa.Column('location',     sa.String(255),      nullable=False),
        sa.Column('eta',          sa.String(20),       nullable=True),
        sa.Column('notes',        sa.Text(),           nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('confirmed_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('truck_id', 'date', name='uq_anchor_points_truck_date'),
    )
    op.create_index('ix_anchor_points_truck_id',  'anchor_points', ['truck_id'])
    op.create_index('ix_anchor_points_driver_id', 'anchor_points', ['driver_id'])
    op.create_index('ix_anchor_points_date',      'anchor_points', ['date'])


def downgrade() -> None:
    op.drop_index('ix_anchor_points_date',      'anchor_points')
    op.drop_index('ix_anchor_points_driver_id', 'anchor_points')
    op.drop_index('ix_anchor_points_truck_id',  'anchor_points')
    op.drop_table('anchor_points')
