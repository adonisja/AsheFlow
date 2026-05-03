"""merge inspection_type branch with is_manual branch

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f7, b4c5d6e7f8a9
Create Date: 2026-05-01 00:00:01.000000

Merge two parallel heads:
  - a1b2c3d4e5f7: add inspection_type to vehicle_inspections
  - b4c5d6e7f8a9: add is_manual to assignment_members
"""
from alembic import op

revision = 'c1d2e3f4a5b6'
down_revision = ('a1b2c3d4e5f7', 'b4c5d6e7f8a9')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
