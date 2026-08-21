"""Add paired_arrival_confirmed to truck_assignments

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-06-25

ADR-145: pre-sort flag so arrival_confirm before commit_sort is not lost.
"""
from alembic import op
import sqlalchemy as sa

revision    = 'o8p9q0r1s2t3'
down_revision = 'n7o8p9q0r1s2'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        'truck_assignments',
        sa.Column('paired_arrival_confirmed', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('truck_assignments', 'paired_arrival_confirmed')
