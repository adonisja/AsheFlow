"""Add injury_status to employees and wave_number to routes.

injury_status (injured|disabled|null) hard-blocks heavy route assignment.
wave_number (default 1) tracks first-wave vs second-wave assignments for
analytics and future auto-assignment model (ADR-139).

Revision ID: f8g9h0i1j2k3
Revises: 46336672ab3e
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'f8g9h0i1j2k3'
down_revision = '46336672ab3e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('injury_status',       sa.String(20),                 nullable=True))
    op.add_column('employees', sa.Column('injury_status_since', sa.DateTime(timezone=True),    nullable=True))
    op.add_column('routes',    sa.Column('wave_number',         sa.Integer(), server_default='1', nullable=False))


def downgrade() -> None:
    op.drop_column('routes',    'wave_number')
    op.drop_column('employees', 'injury_status_since')
    op.drop_column('employees', 'injury_status')
