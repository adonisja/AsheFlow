"""merge normalised_addresses branch into main head

Revision ID: q1r2s3t4u5v6
Revises: v5w6x7y8z9a0, p0q1r2s3t4u5
Create Date: 2026-06-27

Merge migration — no DDL. Collapses the p0q1r2s3t4u5 (normalised_addresses)
branch with the current main head v5w6x7y8z9a0 (shift_roll_calls) so that
alembic upgrade heads runs cleanly from a single head going forward.
"""
from alembic import op

revision = 'q1r2s3t4u5v6'
down_revision = ('v5w6x7y8z9a0', 'p0q1r2s3t4u5')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
