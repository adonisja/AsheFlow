"""building_profiles address resolution + GeoClient fields (ADR-277 D1/D2)

POST /building-profiles/ stores normalised_address VERBATIM. Fine on mobile,
which passes the enriched manifest's string. Wrong everywhere a human types.

Derived (building_profiles is empty on staging, so this is what WILL happen on
first use, not an observed duplicate set):

    '433 West 32nd Street'  -> block_key W_32_St_400
    '433 W 32 St'           -> block_key W_32_St_400   <- the manifest's form
    '433 W 32 ST'           -> block_key W_32_St_400
    '433 w 32 st'           -> block_key W_32_St_400

One block_key, but the unique constraint is (company_id, normalised_address) —
four rows for one building, and routing (which looks up BY normalised address)
matches none of the three the captain typed.

address_status carries the resolution outcome (pending -> resolved | rejected).
On success a Celery task REWRITES normalised_address to GeoClient's canonical
form; the typed string is not retained separately, because the canonical form
is the address. A rejected row keeps geo_grc/geo_message so the submitter can
edit and retry, and is excluded from routing lookups until it resolves.

lat/lng/segment_id are the GeoClient fields worth keeping (D2). segment_id is
the structural one: paired with DeliveryStop.segment_id (ADR-279) it survives
the ADR-219 48h address nulling, so a stop still finds its building past the
window.

Existing rows: none on staging (0 profiles). The server_default covers any that
appear on other environments — they are 'pending' and the resolver picks them up.

Revision ID: 03f64a885658
Revises: b4ed8a79b9a6
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "03f64a885658"
down_revision = "b4ed8a79b9a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "building_profiles",
        sa.Column(
            "address_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("building_profiles", sa.Column("geo_grc", sa.String(length=10), nullable=True))
    op.add_column("building_profiles", sa.Column("geo_message", sa.String(length=200), nullable=True))
    op.add_column("building_profiles", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("building_profiles", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("building_profiles", sa.Column("segment_id", sa.String(length=32), nullable=True))

    # Indexed because both are query predicates, not just stored data:
    # every routing lookup filters address_status != 'rejected', and the
    # ADR-277 D3 truck page joins stops to profiles on segment_id.
    op.create_index(
        "ix_building_profiles_address_status", "building_profiles", ["address_status"]
    )
    op.create_index(
        "ix_building_profiles_segment_id", "building_profiles", ["segment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_building_profiles_segment_id", table_name="building_profiles")
    op.drop_index("ix_building_profiles_address_status", table_name="building_profiles")
    op.drop_column("building_profiles", "segment_id")
    op.drop_column("building_profiles", "lng")
    op.drop_column("building_profiles", "lat")
    op.drop_column("building_profiles", "geo_message")
    op.drop_column("building_profiles", "geo_grc")
    op.drop_column("building_profiles", "address_status")
