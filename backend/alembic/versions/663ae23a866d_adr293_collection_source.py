"""ADR-293 D3 — record how a building profile was collected

Revision ID: 663ae23a866d
Revises: adf3774c0612
Create Date: 2026-08-27

In full mode a profile accrues in context: a walker completes a stop and ADR-277
surfaces the building for assessment. In workforce mode there are no stops, so
collection is entirely manual — someone types an address they remembered.

Manual entries are not less true, but they are differently SAMPLED: a captain
enters the buildings they remember, which biases toward the memorable. Recording
provenance lets a later analysis account for that bias, and lets decay be
reasoned about per-source if that is ever wanted (ADR-293 D3).

server_default="route" because every existing row was collected on a route —
that is what the table has held until now, and backfilling it as "manual" would
misdescribe the entire history.
"""
from alembic import op
import sqlalchemy as sa

revision = "663ae23a866d"
down_revision = "adf3774c0612"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "building_profiles",
        sa.Column("collection_source", sa.String(20), nullable=False,
                  server_default="route"),
    )
    # Indexed: the point of the column is to segment analysis by source, which
    # means filtering on it.
    op.create_index("ix_building_profiles_collection_source",
                    "building_profiles", ["collection_source"])


def downgrade():
    op.drop_index("ix_building_profiles_collection_source",
                  table_name="building_profiles")
    op.drop_column("building_profiles", "collection_source")
