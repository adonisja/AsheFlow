"""add gear request tables

Revision ID: a0b1c2d3e4f5
Revises: z3a4b5c6d7e8
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'a0b1c2d3e4f5'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'gear_orders',
        sa.Column('id',           UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id',   UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id',  UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_gear_orders_company_id',  'gear_orders', ['company_id'])
    op.create_index('ix_gear_orders_employee_id', 'gear_orders', ['employee_id'])

    op.create_table(
        'gear_order_items',
        sa.Column('id',           UUID(as_uuid=True), primary_key=True),
        sa.Column('order_id',     UUID(as_uuid=True), sa.ForeignKey('gear_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id',   UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id',  UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item',         sa.String(20),  nullable=False),
        sa.Column('size',         sa.String(5),   nullable=True),
        sa.Column('season',       sa.String(10),  nullable=False),
        sa.Column('status',       sa.String(15),  nullable=False, server_default='pending'),
        sa.Column('approved_by',  UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at',  sa.DateTime(timezone=True), nullable=True),
        sa.Column('fulfilled_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes',        sa.Text, nullable=True),
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_gear_order_items_order_id',    'gear_order_items', ['order_id'])
    op.create_index('ix_gear_order_items_company_id',  'gear_order_items', ['company_id'])
    op.create_index('ix_gear_order_items_employee_id', 'gear_order_items', ['employee_id'])


def downgrade() -> None:
    op.drop_table('gear_order_items')
    op.drop_table('gear_orders')
