"""Add anchor_point_late_flags table.

One row per late-arrival event. Written the first time a preliminary AP's
ETA + 15 min has passed without an arrival confirmation.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'c6d7e8f9a0b1'
down_revision = 'b5c6d7e8f9a0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'anchor_point_late_flags',
        sa.Column('id',              UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id',      UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('anchor_point_id', UUID(as_uuid=True), sa.ForeignKey('anchor_points.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('truck_id',        UUID(as_uuid=True), sa.ForeignKey('trucks.id',        ondelete='CASCADE'), nullable=False),
        sa.Column('driver_id',       UUID(as_uuid=True), sa.ForeignKey('employees.id',     ondelete='CASCADE'), nullable=False),
        sa.Column('date',            sa.Date(),          nullable=False, index=True),
        sa.Column('eta',             sa.String(20),      nullable=True),
        sa.Column('minutes_late',    sa.Integer(),       nullable=False),
        sa.Column('flagged_at',      sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('anchor_point_id', name='uq_anchor_point_late_flag'),
    )


def downgrade() -> None:
    op.drop_table('anchor_point_late_flags')
