"""merge anchor fields and misrouted package flags heads

Revision ID: e2f3a4b5c6d8
Revises: c7d8e9f0a1b2, d1e2f3a4b5c6
Create Date: 2026-06-29

Merge migration — no DDL. Collapses two open heads:
  c7d8e9f0a1b2  fix_misrouted_package_flags_columns
  d1e2f3a4b5c6  add_initial_anchor_to_building_profiles
"""
from alembic import op

revision = 'e2f3a4b5c6d8'
down_revision = ('c7d8e9f0a1b2', 'd1e2f3a4b5c6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
