"""Add shift_roll_calls table

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'v5w6x7y8z9a0'
down_revision = 'u4v5w6x7y8z9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'shift_roll_calls',
        sa.Column('id',              UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id',      UUID(as_uuid=True), nullable=False),
        sa.Column('submitted_by_id', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('employee_id',     UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date',            sa.Date(),          nullable=False),
        sa.Column('status',          sa.String(10),      nullable=False),
        sa.Column('notes',           sa.Text(),          nullable=True),
        sa.Column('submitted_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',      sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_by_id',   UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('confirmed',       sa.Boolean(),       nullable=False, server_default='false'),
        sa.Column('confirmed_at',    sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('employee_id', 'date', name='uq_shift_roll_calls_employee_date'),
        sa.CheckConstraint("status IN ('early', 'present', 'late', 'ncns')", name='ck_shift_roll_calls_status'),
    )
    op.create_index('ix_shift_roll_calls_company_id',      'shift_roll_calls', ['company_id'])
    op.create_index('ix_shift_roll_calls_employee_id',     'shift_roll_calls', ['employee_id'])
    op.create_index('ix_shift_roll_calls_date',            'shift_roll_calls', ['date'])
    op.create_index('ix_shift_roll_calls_submitted_by_id', 'shift_roll_calls', ['submitted_by_id'])


def downgrade():
    op.drop_table('shift_roll_calls')
