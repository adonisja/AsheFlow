"""Extend anchor_points with departure and running-late fields.

Adds:
  expected_departure_at — when driver expects to leave current AP (set on relocation submit)
  actual_departed_at    — stamped when driver taps "I'm leaving now"
  is_running_late       — True once ETA + 15 min has passed with no arrival
  running_late_flagged_at — when the late flag was first set

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5c6d7e8f9a0'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('anchor_points', sa.Column('expected_departure_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('anchor_points', sa.Column('actual_departed_at',    sa.DateTime(timezone=True), nullable=True))
    op.add_column('anchor_points', sa.Column('is_running_late',       sa.Boolean(),               nullable=False, server_default='false'))
    op.add_column('anchor_points', sa.Column('running_late_flagged_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('anchor_points', 'running_late_flagged_at')
    op.drop_column('anchor_points', 'is_running_late')
    op.drop_column('anchor_points', 'actual_departed_at')
    op.drop_column('anchor_points', 'expected_departure_at')
