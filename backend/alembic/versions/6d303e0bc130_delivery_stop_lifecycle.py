"""delivery_stop lifecycle: status/started_at/is_unplanned + nullable completion fields

Revision ID: 6d303e0bc130
Revises: 35b4ab02ff7d
Create Date: 2026-07-12

ADR-197 Phase 0a: DeliveryStop rows are now pre-seeded as 'planned' at route
creation and transition planned→in_progress→completed (walker-location tracking,
per-stop duration telemetry, clean completion %). Completion-time fields become
nullable because a planned/in_progress row has not been delivered yet.

Existing rows are all completed deliveries → status defaults to 'completed',
is_unplanned to false; their completion fields are already populated. No backfill
needed.
"""
from alembic import op
import sqlalchemy as sa

revision = "6d303e0bc130"
down_revision = "35b4ab02ff7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("delivery_stops", sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"))
    op.add_column("delivery_stops", sa.Column("is_unplanned", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("delivery_stops", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    # Completion-time fields relax to nullable (planned rows have no value yet).
    op.alter_column("delivery_stops", "completed_at", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.alter_column("delivery_stops", "packages_total", existing_type=sa.Integer(), nullable=True)
    op.alter_column("delivery_stops", "packages_delivered", existing_type=sa.Integer(), nullable=True)
    op.alter_column("delivery_stops", "effort_class", existing_type=sa.String(length=20), nullable=True)


def downgrade() -> None:
    # Restore NOT NULL only if no planned/in_progress rows exist (they'd violate it).
    op.execute("DELETE FROM delivery_stops WHERE status <> 'completed'")
    op.alter_column("delivery_stops", "effort_class", existing_type=sa.String(length=20), nullable=False)
    op.alter_column("delivery_stops", "packages_delivered", existing_type=sa.Integer(), nullable=False)
    op.alter_column("delivery_stops", "packages_total", existing_type=sa.Integer(), nullable=False)
    op.alter_column("delivery_stops", "completed_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.drop_column("delivery_stops", "started_at")
    op.drop_column("delivery_stops", "is_unplanned")
    op.drop_column("delivery_stops", "status")
