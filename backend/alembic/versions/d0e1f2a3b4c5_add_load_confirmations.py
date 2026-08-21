"""add load_confirmations table (ADR-181)

Revision ID: d0e1f2a3b4c5
Revises: c8d9e0f1a2b3
Create Date: 2026-07-04

One row per truck per load day: the driver's explicit handoff to dispatch when
their truck is loaded. Partial confirms allowed — short_bag_ids records roster
bags still unchecked at confirm time. Unique on (company_id, load_date,
truck_id); the confirm-load endpoint enforces a 409 one-way guard.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'd0e1f2a3b4c5'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'load_confirmations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('load_date', sa.Date, nullable=False, index=True),
        sa.Column('truck_id', UUID(as_uuid=True), sa.ForeignKey('trucks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('confirmed_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('confirmed_by_name', sa.String(100), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('short_bag_ids', JSONB, nullable=True),
        sa.Column('total_totes', sa.Integer, nullable=False, server_default='0'),
        sa.Column('checked_totes', sa.Integer, nullable=False, server_default='0'),
        sa.UniqueConstraint('company_id', 'load_date', 'truck_id', name='uq_load_confirm_per_truck_day'),
    )


def downgrade() -> None:
    op.drop_table('load_confirmations')
