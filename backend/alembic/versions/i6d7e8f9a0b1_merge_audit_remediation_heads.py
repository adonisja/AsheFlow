"""merge all heads — audit remediation + anchor_point_late_flags + main chain

Revision ID: i6d7e8f9a0b1
Revises: c1d2e3f4b5a6, c6d7e8f9a0b1, h5c6d7e8f9a0
Create Date: 2026-06-01

Merge migration — joins three branches:
  c1d2e3f4b5a6: sort lock + sort pipeline merge (main chain head)
  c6d7e8f9a0b1: anchor_point_late_flags table (previously unmerged branch)
  h5c6d7e8f9a0: audit remediation chain (truck name scoping, composite
                indexes, dispatch weight CHECK constraints, late flags indexes)
No schema changes.
"""
from alembic import op

revision = 'i6d7e8f9a0b1'
down_revision = ('c1d2e3f4b5a6', 'c6d7e8f9a0b1', 'h5c6d7e8f9a0')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
