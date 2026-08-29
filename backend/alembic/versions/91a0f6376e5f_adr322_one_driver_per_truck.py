"""ADR-322 — one driver per truck

Revision ID: 91a0f6376e5f
Revises: 663ae23a866d
Create Date: 2026-08-29

Mirrors uq_assignment_members_one_captain. `driver_trainee` is a distinct role
string, so a trainee riding with their supervising driver is unaffected by
construction — which is the expected pairing (ADR-264).

Safe to add without a data fix: measured 0 violations across 2,675 truck-days
with at least one driver, all history. A constraint already true everywhere is
the cheapest kind to add.

IF NOT EXISTS so a re-run is a no-op.
"""
from alembic import op

revision = "91a0f6376e5f"
down_revision = "663ae23a866d"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_assignment_members_one_driver "
        "ON assignment_members (assignment_id) WHERE role = 'driver'"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_assignment_members_one_driver")
