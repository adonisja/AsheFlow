"""add_vehicle_inspections_table

Revision ID: f4e891bc2d10
Revises: aa7f771104eb
Create Date: 2026-04-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4e891bc2d10'
down_revision: Union[str, Sequence[str], None] = 'aa7f771104eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vehicle_inspections',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('truck_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('has_failures', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vehicle_inspections_driver_id', 'vehicle_inspections', ['driver_id'])
    op.create_index('ix_vehicle_inspections_date', 'vehicle_inspections', ['date'])
    op.create_index('ix_vehicle_inspections_truck_id', 'vehicle_inspections', ['truck_id'])


def downgrade() -> None:
    op.drop_index('ix_vehicle_inspections_truck_id', table_name='vehicle_inspections')
    op.drop_index('ix_vehicle_inspections_date', table_name='vehicle_inspections')
    op.drop_index('ix_vehicle_inspections_driver_id', table_name='vehicle_inspections')
    op.drop_table('vehicle_inspections')
