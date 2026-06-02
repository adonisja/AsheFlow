"""add zone_date to truck_zones

Revision ID: v9w0x1y2z3a4
Revises: u8v9w0x1y2z3
Create Date: 2026-05-27

Adds zone_date (date, NOT NULL) to truck_zones so zones can be scoped
to a specific sort day. Backfills existing rows with the created_at date.
"""

from alembic import op
import sqlalchemy as sa


revision = 'v9w0x1y2z3a4'
down_revision = 'u8v9w0x1y2z3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('truck_zones',
        sa.Column('zone_date', sa.Date(), nullable=True)
    )
    op.execute("UPDATE truck_zones SET zone_date = created_at::date WHERE zone_date IS NULL")
    op.alter_column('truck_zones', 'zone_date', nullable=False)
    op.create_index('ix_truck_zones_zone_date', 'truck_zones', ['zone_date'])


def downgrade():
    op.drop_index('ix_truck_zones_zone_date', table_name='truck_zones')
    op.drop_column('truck_zones', 'zone_date')
