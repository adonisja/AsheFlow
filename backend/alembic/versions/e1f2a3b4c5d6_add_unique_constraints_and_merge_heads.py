"""Add unique constraints and merge migration heads.

Merges the two independent heads:
  - d4e5f6a1b2c3 (add_dispatch_date_to_notifications)
  - 20260409_add_expired_status_to_time_off_requests

Unique constraints added:
  - assignment_members (assignment_id, employee_id) — prevents double-assignment
  - fuel_mileage_logs  (driver_id, date)            — prevents duplicate daily log

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a1b2c3, 20260409_add_expired_status_to_time_off_requests
Create Date: 2026-04-22
"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = ('d4e5f6a1b2c3', '20260409_add_expired_status_to_time_off_requests')
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Prevent the same employee from appearing twice on the same assignment.
    # CREATE UNIQUE INDEX IF NOT EXISTS is idempotent; it also backs the constraint.
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_assignment_members_assignment_employee "
        "ON assignment_members (assignment_id, employee_id)"
    ))

    # Prevent a driver from submitting two fuel/mileage logs for the same day.
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_fuel_mileage_logs_driver_date "
        "ON fuel_mileage_logs (driver_id, date)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP INDEX IF EXISTS uq_fuel_mileage_logs_driver_date"))
    conn.execute(text("DROP INDEX IF EXISTS uq_assignment_members_assignment_employee"))
