"""add shift_sessions table

Revision ID: o2p3q4r5s6t7
Revises: n1o2p3q4r5s6
Create Date: 2026-05-15

"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'o2p3q4r5s6t7'
down_revision = 'n1o2p3q4r5s6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'shift_sessions',
        sa.Column('id',                UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id',        UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('driver_id',         UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('current_gate',      sa.Integer,         nullable=False, server_default='1'),
        sa.Column('started_at',        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('gate_1_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('gate_2_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('gate_3_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('gate_4_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at',      sa.DateTime(timezone=True), nullable=True),
    )
    # One active (incomplete) session per driver at a time
    op.create_index(
        'ix_shift_sessions_driver_active',
        'shift_sessions',
        ['driver_id'],
        unique=True,
        postgresql_where=sa.text('completed_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_shift_sessions_driver_active', table_name='shift_sessions')
    op.drop_table('shift_sessions')
