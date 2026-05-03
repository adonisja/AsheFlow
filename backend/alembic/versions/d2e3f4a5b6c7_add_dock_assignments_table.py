"""add dock_assignments table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-01 00:00:02.000000

Dispatch assigns a dock zone to each driver before their pre-trip inspection.
One record per driver per date; updatable via PATCH.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dock_assignments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('dock_zone', sa.String(50), nullable=False),
        sa.Column('assigned_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_by'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('driver_id', 'date', name='uq_dock_assignments_driver_date'),
    )
    op.create_index('ix_dock_assignments_driver_id', 'dock_assignments', ['driver_id'])
    op.create_index('ix_dock_assignments_date', 'dock_assignments', ['date'])


def downgrade() -> None:
    op.drop_index('ix_dock_assignments_date', table_name='dock_assignments')
    op.drop_index('ix_dock_assignments_driver_id', table_name='dock_assignments')
    op.drop_table('dock_assignments')
