"""add station_arrivals table

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-01 00:00:03.000000

Tracks when drivers arrive at the station — two visits per shift:
  - "loading": arriving to load packages before route departure
  - "return": arriving back with RTS packages after the route
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'station_arrivals',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('arrival_type', sa.String(20), nullable=False),
        sa.Column('arrived_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('driver_id', 'date', 'arrival_type', name='uq_station_arrivals_driver_date_type'),
    )
    op.create_index('ix_station_arrivals_driver_id', 'station_arrivals', ['driver_id'])
    op.create_index('ix_station_arrivals_date', 'station_arrivals', ['date'])


def downgrade() -> None:
    op.drop_index('ix_station_arrivals_date', table_name='station_arrivals')
    op.drop_index('ix_station_arrivals_driver_id', table_name='station_arrivals')
    op.drop_table('station_arrivals')
