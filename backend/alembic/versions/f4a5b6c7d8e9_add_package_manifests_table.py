"""add package_manifests table

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-05-01 00:00:04.000000

Records tote and OV (oversized) package counts per truck per date.
Submitted by dispatch at station load time; one record per truck per date.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'package_manifests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('truck_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('tote_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ov_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('truck_id', 'date', name='uq_package_manifests_truck_date'),
    )
    op.create_index('ix_package_manifests_truck_id', 'package_manifests', ['truck_id'])
    op.create_index('ix_package_manifests_date', 'package_manifests', ['date'])


def downgrade() -> None:
    op.drop_index('ix_package_manifests_date', table_name='package_manifests')
    op.drop_index('ix_package_manifests_truck_id', table_name='package_manifests')
    op.drop_table('package_manifests')
