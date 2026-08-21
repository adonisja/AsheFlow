"""delivery_stops.segment_id — the purge-durable per-stop join key (ADR-279)

ADR-260 stopped the ROUTE discarding the segment ids the sort already resolved.
The STOP still discarded them: _build_stops groups real _Package objects (each
carrying segment_id from route_sort.py:1678) but StopOut declared only
block_key/address/tba_numbers/bags, so the segment died at the moment a stop
was formed. Third instance of one pattern in this path — bag_color and ADR-260
were the first two.

Why it matters: ADR-219 nulls normalised_address 48h post-route and keeps
block_key. Measured on staging 2026-08-20, 1,194,365 stops across 46,601 routes
collapse to just 266 distinct block_keys — so past the window a stop is
locatable to a block and no finer. A segment id is a block-FACE: precise enough
to identify the building's street segment, coarse enough that it cannot
reconstruct a house number.

NOT added to the ADR-219 nulling, deliberately (ADR-279 D4). Per StreetSegment:
"no house numbers, no normalised_address, no package/TBA data". Same class of
public-geography fact as block_key, which the purge already retains.

Nullable, and null is a real answer (D2): GeoClient can match a street but
return no segment topology (grc 42), and the three ad-hoc creation paths
(rts.py x2, package_intake.py) build stops from a typed address with no
enriched package to read a segment from.

No backfill is possible — the source packages leave Redis on the manifest's 24h
TTL, the same constraint ADR-260 recorded. Existing rows stay NULL; the column
fills forward from the next sort.

Revision ID: b4ed8a79b9a6
Revises: 892dc2ce9576
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "b4ed8a79b9a6"
down_revision = "892dc2ce9576"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_stops",
        sa.Column("segment_id", sa.String(length=32), nullable=True),
    )
    # Indexed because the ADR-277 truck page queries stops BY segment once the
    # address is purged — that lookup is the whole point of the column.
    op.create_index(
        "ix_delivery_stops_segment_id", "delivery_stops", ["segment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_stops_segment_id", table_name="delivery_stops")
    op.drop_column("delivery_stops", "segment_id")
