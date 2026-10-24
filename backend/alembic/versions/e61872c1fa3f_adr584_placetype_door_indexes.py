"""ADR-584: indexes for the door resolver and the nearby-doors picker.

Revision ID: e61872c1fa3f
Revises: c3a7056d756b
"""
from alembic import op

revision = "e61872c1fa3f"
down_revision = "c3a7056d756b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_building_profile_library_borough_block", "building_profile_library",
                    ["borough", "block_key"])
    op.create_index("ix_building_profile_library_lat_lng", "building_profile_library", ["lat", "lng"])


def downgrade():
    op.drop_index("ix_building_profile_library_lat_lng", table_name="building_profile_library")
    op.drop_index("ix_building_profile_library_borough_block", table_name="building_profile_library")
