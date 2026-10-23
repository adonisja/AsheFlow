"""ADR-583 D5: PlaceType door identity is (borough, canonical address).

Revision ID: c3a7056d756b
Revises: 1a2a54f009ff
"""
from alembic import op
import sqlalchemy as sa

revision = "c3a7056d756b"
down_revision = "1a2a54f009ff"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("building_profile_library", sa.Column("borough", sa.String(1), nullable=True))
    op.create_index("ix_building_profile_library_borough", "building_profile_library", ["borough"])
    op.drop_constraint("uq_building_profile_library_address", "building_profile_library", type_="unique")
    op.create_unique_constraint("uq_building_profile_library_door", "building_profile_library",
                                ["borough", "normalised_address"])


def downgrade():
    op.drop_constraint("uq_building_profile_library_door", "building_profile_library", type_="unique")
    op.create_unique_constraint("uq_building_profile_library_address", "building_profile_library",
                                ["normalised_address"])
    op.drop_index("ix_building_profile_library_borough", table_name="building_profile_library")
    op.drop_column("building_profile_library", "borough")
