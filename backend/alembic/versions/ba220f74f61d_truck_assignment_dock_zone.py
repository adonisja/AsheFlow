"""truck_assignments.dock_zone — dispatch-set physical bay (ADR-274 D17)

Revision ID: ba220f74f61d
Revises: c7a1e4b93f52
Create Date: 2026-08-19

The bay a truck occupies for the day. On the ASSIGNMENT rather than on Truck
because a bay can differ day to day — a column on Truck would rewrite history
every time it changed. Nullable: unset is a normal state, and the value is
prefilled from the truck's previous assignment for dispatch to confirm.

String(50) matches dock_assignments.dock_zone, which is written from this at
publish so the existing per-driver home cards keep working unchanged.
"""
from alembic import op
import sqlalchemy as sa

revision = "ba220f74f61d"
down_revision = "c7a1e4b93f52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "truck_assignments",
        sa.Column("dock_zone", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("truck_assignments", "dock_zone")
