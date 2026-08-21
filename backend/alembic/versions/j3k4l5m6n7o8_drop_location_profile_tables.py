"""drop location_profiles and location_profile_library tables

Revision ID: j3k4l5m6n7o8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-24

LocationProfile and LocationProfileLibrary are dropped entirely.

Decision: the block-level fallback tier added complexity without solving the real
problem. BuildingProfile (address-level) and BuildingProfileLibrary (global) are
the two-tier system. Cold-start for a brand new company with zero library data
returns "standard" workload for all packages — coverage_pct=0% is surfaced to
the trainer who redistributes manually. First customer operates as beta tester
at a discount and seeds the library for all future customers in the same market.

See docs/BUILDING_PROFILE_DESIGN.md.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = 'j3k4l5m6n7o8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("location_profiles")
    op.drop_table("location_profile_library")


def downgrade():
    # Restore location_profile_library
    op.create_table(
        "location_profile_library",
        sa.Column("id",                     UUID(as_uuid=True), primary_key=True),
        sa.Column("block_key",              sa.String(60),  nullable=False),
        sa.Column("building_type",          sa.String(30),  nullable=False),
        sa.Column("workload_class",         sa.String(20),  nullable=False),
        sa.Column("library_status",         sa.String(20),  server_default="active", nullable=False),
        sa.Column("agreement_source_count", sa.Integer,     server_default="0",      nullable=False),
        sa.Column("last_conflict_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_from_company_ids", ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("promoted_at",            sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_by",            UUID(as_uuid=True), nullable=True),
        sa.Column("promoted_by_name",       sa.String(100), nullable=True),
        sa.Column("updated_by",             UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_name",        sa.String(100), nullable=True),
        sa.Column("updated_at",             sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at",             sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("block_key", "building_type", name="uq_location_profile_library_block_type"),
    )

    # Restore location_profiles
    op.create_table(
        "location_profiles",
        sa.Column("id",                             UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",                     UUID(as_uuid=True), nullable=False),
        sa.Column("block_key",                      sa.String(60),  nullable=False),
        sa.Column("building_type",                  sa.String(30),  nullable=False),
        sa.Column("workload_class",                 sa.String(20),  nullable=False),
        sa.Column("building_type_status",           sa.String(20),  server_default="pending"),
        sa.Column("building_type_agreement_count",  sa.Integer,     server_default="0"),
        sa.Column("nomination_status",              sa.String(20),  nullable=True),
        sa.Column("raw_notes",          sa.Text,    nullable=True),
        sa.Column("operational_note",   sa.Text,    nullable=True),
        sa.Column("note_verified",      sa.Boolean, server_default="false", nullable=False),
        sa.Column("note_verified_by",       UUID(as_uuid=True), nullable=True),
        sa.Column("note_verified_by_name",  sa.String(100), nullable=True),
        sa.Column("note_verified_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by",       UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_by_name",  sa.String(100), nullable=True),
        sa.Column("submitted_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by",        UUID(as_uuid=True), nullable=True),
        sa.Column("verified_by_name",   sa.String(100), nullable=True),
        sa.Column("verified_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by",         UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_name",    sa.String(100), nullable=True),
        sa.Column("created_at",         sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at",         sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "block_key", "building_type", name="uq_location_profiles_company_block_type"),
    )
    op.create_index("ix_location_profiles_company_id", "location_profiles", ["company_id"])
