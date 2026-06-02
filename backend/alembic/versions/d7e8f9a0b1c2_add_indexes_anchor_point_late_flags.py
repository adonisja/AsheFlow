"""add indexes on truck_id and driver_id in anchor_point_late_flags

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-06-01

These columns are used in WHERE clauses when querying late flags by truck or
driver for a given date; without indexes each query scans the full table.
"""
from alembic import op

revision = 'd7e8f9a0b1c2'
down_revision = 'c6d7e8f9a0b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_anchor_point_late_flags_truck_id",  "anchor_point_late_flags", ["truck_id"])
    op.create_index("ix_anchor_point_late_flags_driver_id", "anchor_point_late_flags", ["driver_id"])


def downgrade():
    op.drop_index("ix_anchor_point_late_flags_driver_id", table_name="anchor_point_late_flags")
    op.drop_index("ix_anchor_point_late_flags_truck_id",  table_name="anchor_point_late_flags")
