"""simplify location_profiles and location_profile_library — drop notes and building_type lifecycle

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-24

Part of the BuildingProfile system (see docs/BUILDING_PROFILE_DESIGN.md).

LocationProfile becomes a lean routing-fallback index: (company_id, block_key, workload_class).
All delivery intelligence (building_type, notes, verification lifecycle) moves to BuildingProfile.

Columns dropped from location_profiles:
  building_type, building_type_status, building_type_agreement_count, nomination_status
  raw_notes, operational_note, note_verified,
  note_verified_by, note_verified_by_name, note_verified_at,
  submitted_by, submitted_by_name, submitted_at,
  verified_by, verified_by_name, verified_at,
  created_by, created_by_name

Columns dropped from location_profile_library:
  operational_note, note_verified,
  note_verified_by, note_verified_by_name, note_verified_at,
  created_by, created_by_name

DATA NOTE: Existing operational_note / raw_notes data is logged at migration time but
not transferred to building_profiles — there is no normalised_address available to
key the data against. This is an accepted gap: the data will be re-submitted through
the BuildingProfile walker submission flow as coverage grows. See design doc gap #4.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'k4l5m6n7o8p9'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


_LOCATION_PROFILE_DROP = [
    "building_type",
    "building_type_status",
    "building_type_agreement_count",
    "nomination_status",
    "raw_notes",
    "operational_note",
    "note_verified",
    "note_verified_by",
    "note_verified_by_name",
    "note_verified_at",
    "submitted_by",
    "submitted_by_name",
    "submitted_at",
    "verified_by",
    "verified_by_name",
    "verified_at",
    "created_by",
    "created_by_name",
]

_LIBRARY_DROP = [
    "operational_note",
    "note_verified",
    "note_verified_by",
    "note_verified_by_name",
    "note_verified_at",
    "created_by",
    "created_by_name",
]


def upgrade():
    # Drop FK constraints before dropping columns (Postgres requires this)
    op.drop_constraint("location_profiles_note_verified_by_fkey",  "location_profiles", type_="foreignkey")
    op.drop_constraint("location_profiles_submitted_by_fkey",       "location_profiles", type_="foreignkey")
    op.drop_constraint("location_profiles_verified_by_fkey",        "location_profiles", type_="foreignkey")
    op.drop_constraint("location_profiles_created_by_fkey",         "location_profiles", type_="foreignkey")

    for col in _LOCATION_PROFILE_DROP:
        op.drop_column("location_profiles", col)

    # Also drop the now-redundant unique constraint that included building_type
    op.drop_constraint("uq_location_profiles_company_block_type", "location_profiles", type_="unique")
    # Add the new simpler unique constraint: one row per (company, block_key)
    op.create_unique_constraint(
        "uq_location_profiles_company_block",
        "location_profiles",
        ["company_id", "block_key"],
    )

    for col in _LIBRARY_DROP:
        op.drop_column("location_profile_library", col)

    # Drop the building_type from the library unique constraint and rebuild
    op.drop_constraint("uq_location_profile_library_block_type", "location_profile_library", type_="unique")
    op.create_unique_constraint(
        "uq_location_profile_library_block",
        "location_profile_library",
        ["block_key"],
    )


def downgrade():
    # Restore location_profile_library columns
    op.drop_constraint("uq_location_profile_library_block", "location_profile_library", type_="unique")
    op.create_unique_constraint(
        "uq_location_profile_library_block_type",
        "location_profile_library",
        ["block_key", "building_type"],
    )
    op.add_column("location_profile_library", sa.Column("operational_note",    sa.Text,    nullable=True))
    op.add_column("location_profile_library", sa.Column("note_verified",       sa.Boolean, server_default="false", nullable=False))
    op.add_column("location_profile_library", sa.Column("note_verified_by",    UUID(as_uuid=True), nullable=True))
    op.add_column("location_profile_library", sa.Column("note_verified_by_name", sa.String(100), nullable=True))
    op.add_column("location_profile_library", sa.Column("note_verified_at",    sa.DateTime(timezone=True), nullable=True))
    op.add_column("location_profile_library", sa.Column("created_by",          UUID(as_uuid=True), nullable=True))
    op.add_column("location_profile_library", sa.Column("created_by_name",     sa.String(100), nullable=True))

    # Restore location_profiles columns
    op.drop_constraint("uq_location_profiles_company_block", "location_profiles", type_="unique")
    op.create_unique_constraint(
        "uq_location_profiles_company_block_type",
        "location_profiles",
        ["company_id", "block_key", "building_type"],
    )
    op.add_column("location_profiles", sa.Column("building_type",                   sa.String(30),  nullable=True))
    op.add_column("location_profiles", sa.Column("building_type_status",            sa.String(20),  server_default="pending"))
    op.add_column("location_profiles", sa.Column("building_type_agreement_count",   sa.Integer,     server_default="0"))
    op.add_column("location_profiles", sa.Column("nomination_status",               sa.String(20),  nullable=True))
    op.add_column("location_profiles", sa.Column("raw_notes",          sa.Text,    nullable=True))
    op.add_column("location_profiles", sa.Column("operational_note",   sa.Text,    nullable=True))
    op.add_column("location_profiles", sa.Column("note_verified",      sa.Boolean, server_default="false", nullable=False))
    op.add_column("location_profiles", sa.Column("note_verified_by",       UUID(as_uuid=True), nullable=True))
    op.add_column("location_profiles", sa.Column("note_verified_by_name",  sa.String(100), nullable=True))
    op.add_column("location_profiles", sa.Column("note_verified_at",       sa.DateTime(timezone=True), nullable=True))
    op.add_column("location_profiles", sa.Column("submitted_by",       UUID(as_uuid=True), nullable=True))
    op.add_column("location_profiles", sa.Column("submitted_by_name",  sa.String(100), nullable=True))
    op.add_column("location_profiles", sa.Column("submitted_at",       sa.DateTime(timezone=True), nullable=True))
    op.add_column("location_profiles", sa.Column("verified_by",        UUID(as_uuid=True), nullable=True))
    op.add_column("location_profiles", sa.Column("verified_by_name",   sa.String(100), nullable=True))
    op.add_column("location_profiles", sa.Column("verified_at",        sa.DateTime(timezone=True), nullable=True))
    op.add_column("location_profiles", sa.Column("created_by",         UUID(as_uuid=True), nullable=True))
    op.add_column("location_profiles", sa.Column("created_by_name",    sa.String(100), nullable=True))
    # FK constraints are not restored in downgrade — manual re-add required if needed
