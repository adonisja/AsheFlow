"""station load finalization: tote_roster on truck_zones + tote_transfers + tote_load_checks

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-02

ADR-174: the station sort's product is a finalized loading payload for AP Sort.
Persist the per-zone tote roster (durable beyond the 24h Redis manifest TTL),
record physical tote transfers between trucks at the station, and track
per-tote load check-offs.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('truck_zones', sa.Column('tote_roster', JSONB(), nullable=True))

    op.create_table(
        'tote_transfers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('transfer_date', sa.Date(), nullable=False, index=True),
        sa.Column('bag_id', sa.String(100), nullable=False),
        sa.Column('from_truck_id', UUID(as_uuid=True), sa.ForeignKey('trucks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('to_truck_id', UUID(as_uuid=True), sa.ForeignKey('trucks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('package_count', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='suggested'),
        sa.Column('reason', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('resolved_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('resolved_by_name', sa.String(100), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'tote_load_checks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('load_date', sa.Date(), nullable=False, index=True),
        sa.Column('truck_id', UUID(as_uuid=True), sa.ForeignKey('trucks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bag_id', sa.String(100), nullable=False),
        sa.Column('checked_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('checked_by_name', sa.String(100), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('company_id', 'load_date', 'bag_id', name='uq_tote_check_per_day'),
    )


def downgrade() -> None:
    op.drop_table('tote_load_checks')
    op.drop_table('tote_transfers')
    op.drop_column('truck_zones', 'tote_roster')
