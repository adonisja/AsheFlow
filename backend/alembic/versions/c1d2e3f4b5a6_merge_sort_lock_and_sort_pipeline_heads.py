"""merge sort lock and sort pipeline heads

Revision ID: c1d2e3f4b5a6
Revises: a1b2c3d4e5f8, b3c4d5e6f7g8
Create Date: 2026-05-30

Merges two parallel migration branches:
- a1b2c3d4e5f8: sort lock fields on truck_assignments
- b3c4d5e6f7g8: sort pipeline safety index on truck_zones
"""

from alembic import op

revision = 'c1d2e3f4b5a6'
down_revision = ('a1b2c3d4e5f8', 'b3c4d5e6f7g8')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
