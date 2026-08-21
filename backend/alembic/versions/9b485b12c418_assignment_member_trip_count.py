"""assignment_member per-employee trip_count

Revision ID: 9b485b12c418
Revises: ac4fb6987230
Create Date: 2026-07-13

ADR-199 D3: per-employee-per-day trip counter, incremented on back-at-truck.
A "trip" = one route run completed AND returned. Distinct from Route.wave_number
(the truck's redistribution cycle). Existing rows default to 0 — no backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "9b485b12c418"
down_revision = "ac4fb6987230"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assignment_members",
        sa.Column("trip_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("assignment_members", "trip_count")
