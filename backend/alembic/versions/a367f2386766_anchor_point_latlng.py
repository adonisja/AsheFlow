"""anchor_points: geocoded lat/lng (ADR-206)

Revision ID: a367f2386766
Revises: 75bc7c379db7
Create Date: 2026-07-16

ADR-206: AP location is now geocoded server-side (cross street/address → GeoClient).
Persist the resolved coordinates on the AP row. Nullable — pre-ADR-206 rows have no
coordinates, and a non-GeoClient tenant may create APs without them.
"""
from alembic import op
import sqlalchemy as sa

revision = "a367f2386766"
down_revision = "75bc7c379db7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("anchor_points", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("anchor_points", sa.Column("lng", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("anchor_points", "lng")
    op.drop_column("anchor_points", "lat")
