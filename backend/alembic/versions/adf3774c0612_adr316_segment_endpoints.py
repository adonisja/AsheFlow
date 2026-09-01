"""ADR-316 — segment endpoint coordinates complete the cache

Revision ID: adf3774c0612
Revises: de731d1f9557
Create Date: 2026-08-27

`GeoClientResult` carries 14 fields; PlaceType stored 9. The four missing ones
were the blockface endpoint coordinates, and their absence forced every routing
caller to miss the cache and call GeoClient anyway (ADR-316 D2).

They are SEGMENT geometry, not address geometry — verified live: three addresses
on segment 0297696 all return the identical
x/yCoordinateLow/HighAddressEnd. So they join from `street_segments` exactly as
the house-number span does (ADR-314 D3), rather than duplicating ~18 times per
block.

NY State Plane feet, 7 digits, no decimals — Integer.

That leaves `geo_message` as the only unstored field, and it is diagnostic text
about a single lookup rather than a fact about a place.
"""
from alembic import op
import sqlalchemy as sa

revision = "adf3774c0612"
down_revision = "de731d1f9557"
branch_labels = None
depends_on = None


def upgrade():
    for col in ("x_low_address_end", "y_low_address_end",
                "x_high_address_end", "y_high_address_end"):
        op.add_column("street_segments", sa.Column(col, sa.Integer(), nullable=True))


def downgrade():
    for col in ("y_high_address_end", "x_high_address_end",
                "y_low_address_end", "x_low_address_end"):
        op.drop_column("street_segments", col)
