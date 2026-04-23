"""add dispatch_confirmations table

Revision ID: d3f2a1b4c5e6
Revises: c4e1f8a2d3b9
Create Date: 2026-04-18

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'd3f2a1b4c5e6'
down_revision: Union[str, None] = 'c4e1f8a2d3b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dispatch_confirmations',
        sa.Column('id',           UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('employee_id',  UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date',         sa.Date(),           nullable=False),
        sa.Column('status',       sa.String(20),       nullable=False, server_default='pending'),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source',       sa.String(20),       nullable=False, server_default='discord_bot'),
        sa.Column('created_at',   sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('employee_id', 'date', name='uq_dispatch_confirmation_employee_date'),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'declined')", name='ck_dispatch_confirmations_status'),
        sa.CheckConstraint("source IN ('discord_bot', 'manual')", name='ck_dispatch_confirmations_source'),
    )
    op.create_index('ix_dispatch_confirmations_employee_id', 'dispatch_confirmations', ['employee_id'])
    op.create_index('ix_dispatch_confirmations_date',        'dispatch_confirmations', ['date'])


def downgrade() -> None:
    op.drop_index('ix_dispatch_confirmations_date',        table_name='dispatch_confirmations')
    op.drop_index('ix_dispatch_confirmations_employee_id', table_name='dispatch_confirmations')
    op.drop_table('dispatch_confirmations')
