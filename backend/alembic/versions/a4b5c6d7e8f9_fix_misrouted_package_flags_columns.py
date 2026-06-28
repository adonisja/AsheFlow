"""fix misrouted_package_flags columns and add normalised_addresses to routes

Revision ID: a4b5c6d7e8f9
Revises: z3a4b5c6d7e8
Create Date: 2026-06-28

Changes:
  - misrouted_package_flags: rename walker_route_id → route_id,
    rename suggested_walker_route_id → suggested_route_id,
    add destination_block_key (was missing from original table)
  - routes: add normalised_addresses ARRAY(Text) NOT NULL DEFAULT '{}'
    (DDL applied directly on staging; this migration is for fresh environments
    and the canonical record)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a4b5c6d7e8f9'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── misrouted_package_flags ───────────────────────────────────────────────
    # Rename walker_route_id → route_id (column + index)
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "RENAME COLUMN walker_route_id TO route_id"
    )
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "RENAME COLUMN suggested_walker_route_id TO suggested_route_id"
    )
    # destination_block_key was added directly on staging; guard with IF NOT EXISTS
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "ADD COLUMN IF NOT EXISTS destination_block_key VARCHAR(100)"
    )
    # Rename the FK index if it exists under the old name
    op.execute(
        "DO $$ BEGIN "
        "  IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_misrouted_package_flags_walker_route_id') THEN "
        "    ALTER INDEX ix_misrouted_package_flags_walker_route_id "
        "      RENAME TO ix_misrouted_package_flags_route_id; "
        "  END IF; "
        "END $$"
    )

    # ── routes ───────────────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE routes "
        "ADD COLUMN IF NOT EXISTS normalised_addresses TEXT[] NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "RENAME COLUMN route_id TO walker_route_id"
    )
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "RENAME COLUMN suggested_route_id TO suggested_walker_route_id"
    )
    op.execute(
        "ALTER TABLE misrouted_package_flags "
        "DROP COLUMN IF EXISTS destination_block_key"
    )
    op.execute(
        "ALTER TABLE routes "
        "DROP COLUMN IF EXISTS normalised_addresses"
    )
