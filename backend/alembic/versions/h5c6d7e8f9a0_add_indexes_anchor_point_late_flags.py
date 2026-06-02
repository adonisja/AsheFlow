"""merge audit-remediation chain + anchor_point_late_flags table, then add indexes

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9, c6d7e8f9a0b1
Create Date: 2026-06-01

Joins two branches before creating indexes:
  g4b5c6d7e8f9: dispatch weight CHECK constraints (audit-remediation chain)
  c6d7e8f9a0b1: anchor_point_late_flags table creation

The indexes require the table to exist — the explicit dependency on c6d7e8f9a0b1
guarantees Alembic runs the table-creation migration before this one regardless
of which branch it processes first.
"""
from alembic import op

revision = 'h5c6d7e8f9a0'
down_revision = ('g4b5c6d7e8f9', 'c6d7e8f9a0b1')
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_anchor_point_late_flags_truck_id",  "anchor_point_late_flags", ["truck_id"])
    op.create_index("ix_anchor_point_late_flags_driver_id", "anchor_point_late_flags", ["driver_id"])


def downgrade():
    op.drop_index("ix_anchor_point_late_flags_driver_id", table_name="anchor_point_late_flags")
    op.drop_index("ix_anchor_point_late_flags_truck_id",  table_name="anchor_point_late_flags")
