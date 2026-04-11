"""add_fuel_mileage_logs_table

Revision ID: e7d2130af5b1
Revises: c2a983f01e44
Create Date: 2026-04-10 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7d2130af5b1'
down_revision: Union[str, Sequence[str], None] = 'c2a983f01e44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fuel_mileage_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('truck_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('odometer_start', sa.Integer(), nullable=False),
        sa.Column('odometer_end', sa.Integer(), nullable=True),
        sa.Column('fuel_added', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fuel_mileage_logs_driver_id', 'fuel_mileage_logs', ['driver_id'])
    op.create_index('ix_fuel_mileage_logs_date', 'fuel_mileage_logs', ['date'])
    op.create_index('ix_fuel_mileage_logs_truck_id', 'fuel_mileage_logs', ['truck_id'])


def downgrade() -> None:
    op.drop_index('ix_fuel_mileage_logs_truck_id', table_name='fuel_mileage_logs')
    op.drop_index('ix_fuel_mileage_logs_date', table_name='fuel_mileage_logs')
    op.drop_index('ix_fuel_mileage_logs_driver_id', table_name='fuel_mileage_logs')
    op.drop_table('fuel_mileage_logs')
