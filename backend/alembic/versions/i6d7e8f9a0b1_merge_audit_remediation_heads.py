"""merge main chain + audit remediation chain into single head

Revision ID: i6d7e8f9a0b1
Revises: c1d2e3f4b5a6, h5c6d7e8f9a0
Create Date: 2026-06-01

Merge migration — joins two branches:
  c1d2e3f4b5a6: sort lock + sort pipeline merge (main chain head)
  h5c6d7e8f9a0: audit remediation chain + anchor_point_late_flags indexes
                (h5c6d7e8f9a0 already merges c6d7e8f9a0b1 + g4b5c6d7e8f9)
No schema changes.
"""
from alembic import op

revision = 'i6d7e8f9a0b1'
down_revision = ('c1d2e3f4b5a6', 'h5c6d7e8f9a0')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
