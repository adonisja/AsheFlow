"""Add late_window_minutes to company_configs

Revision ID: a1b2c3d4e5f6
Revises: a0b1c2d3e4f5, e6fa3d53aa53, j3k4l5m6n7o8, k4l5m6n7o8p9, l5m6n7o8p9q0, o8p9q0r1s2t3
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = ('a0b1c2d3e4f5', 'e6fa3d53aa53', 'j3k4l5m6n7o8', 'k4l5m6n7o8p9', 'l5m6n7o8p9q0', 'o8p9q0r1s2t3')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('company_configs',
        sa.Column('late_window_minutes', sa.Integer(), nullable=True)
    )


def downgrade():
    op.drop_column('company_configs', 'late_window_minutes')
