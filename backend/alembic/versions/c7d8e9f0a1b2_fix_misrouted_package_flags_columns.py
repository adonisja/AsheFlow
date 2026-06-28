"""fix misrouted_package_flags column names

Revision ID: c7d8e9f0a1b2
Revises: q1r2s3t4u5v6
Create Date: 2026-06-28

Renames walker_route_id → route_id and suggested_walker_route_id → suggested_route_id
on misrouted_package_flags. Adds destination_block_key if not already present
(column was applied directly on staging via psql).

normalised_addresses on routes is already covered by p0q1r2s3t4u5 — not repeated here.
"""
from alembic import op

revision = 'c7d8e9f0a1b2'
down_revision = 'q1r2s3t4u5v6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Staging had DDL applied directly, leaving both old and new columns present.
    # Strategy: rename only when the new column does NOT yet exist; otherwise
    # drop the stale old column (data was never populated there).

    # walker_route_id → route_id
    op.execute(
        "DO $$ BEGIN "
        "  IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
        "                 WHERE table_name='misrouted_package_flags' AND column_name='route_id') THEN "
        "    ALTER TABLE misrouted_package_flags RENAME COLUMN walker_route_id TO route_id; "
        "  ELSIF EXISTS (SELECT 1 FROM information_schema.columns "
        "                WHERE table_name='misrouted_package_flags' AND column_name='walker_route_id') THEN "
        "    ALTER TABLE misrouted_package_flags DROP COLUMN walker_route_id; "
        "  END IF; "
        "END $$"
    )
    # suggested_walker_route_id → suggested_route_id
    op.execute(
        "DO $$ BEGIN "
        "  IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
        "                 WHERE table_name='misrouted_package_flags' AND column_name='suggested_route_id') THEN "
        "    ALTER TABLE misrouted_package_flags RENAME COLUMN suggested_walker_route_id TO suggested_route_id; "
        "  ELSIF EXISTS (SELECT 1 FROM information_schema.columns "
        "                WHERE table_name='misrouted_package_flags' AND column_name='suggested_walker_route_id') THEN "
        "    ALTER TABLE misrouted_package_flags DROP COLUMN suggested_walker_route_id; "
        "  END IF; "
        "END $$"
    )
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "ADD COLUMN IF NOT EXISTS destination_block_key VARCHAR(100)"
    )
    # Rename FK index if it still has the old name
    op.execute(
        "DO $$ BEGIN "
        "  IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_misrouted_package_flags_walker_route_id') THEN "
        "    ALTER INDEX ix_misrouted_package_flags_walker_route_id "
        "      RENAME TO ix_misrouted_package_flags_route_id; "
        "  END IF; "
        "END $$"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "  IF EXISTS (SELECT 1 FROM information_schema.columns "
        "             WHERE table_name='misrouted_package_flags' AND column_name='route_id') THEN "
        "    ALTER TABLE misrouted_package_flags RENAME COLUMN route_id TO walker_route_id; "
        "  END IF; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "  IF EXISTS (SELECT 1 FROM information_schema.columns "
        "             WHERE table_name='misrouted_package_flags' AND column_name='suggested_route_id') THEN "
        "    ALTER TABLE misrouted_package_flags RENAME COLUMN suggested_route_id TO suggested_walker_route_id; "
        "  END IF; "
        "END $$"
    )
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "DROP COLUMN IF EXISTS destination_block_key"
    )
