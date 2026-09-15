"""ADR-408 D2 — store the LION segment a tote address resolves to.

`resolve_address` already computes `segment_id`; the workforce write site had
nowhere to put it, so the sort ran on a graph with no cost-1 edges while the
topology sat one join away.

Additive and nullable: no backfill, no constraint change, no data migration.
Existing rows stay null, which the sort already handles as "no segment" and
falls back to block-key adjacency.

Revision ID: 6d6b30ddb9b9
Revises: 5831fdbb4827
"""
from alembic import op
import sqlalchemy as sa

revision = "6d6b30ddb9b9"
down_revision = "5831fdbb4827"
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS so a box where the column was applied by hand converges
    # rather than failing the whole upgrade.
    op.execute(
        "ALTER TABLE tote_addresses ADD COLUMN IF NOT EXISTS segment_id VARCHAR(32)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tote_addresses_segment_id "
        "ON tote_addresses (segment_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_tote_addresses_segment_id")
    op.execute("ALTER TABLE tote_addresses DROP COLUMN IF EXISTS segment_id")
