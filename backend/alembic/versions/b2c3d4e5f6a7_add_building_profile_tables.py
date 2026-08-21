"""add building_profiles and building_profile_library tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f9
Create Date: 2026-06-24

Part of the BuildingProfile system (see docs/BUILDING_PROFILE_DESIGN.md).

Adds two new tables:

  building_profiles — company-scoped, address-level source of truth.
    Keyed on (company_id, normalised_address). Carries building_type,
    workload_class, operational_note, and a pending→verified→locked lifecycle.
    Feeds both the route effort score (workload_class) and the walker delivery
    UI (building_type tag + operational_note).

  building_profile_library — AsheFlow-owned, platform-wide global layer.
    Keyed on normalised_address alone (no company_id). Promoted from
    building_profiles when the same address locks across 2+ independent companies.
    Serves cold-start workload data to any company entering a new delivery area.

No existing tables are modified in this migration.
LocationProfile simplification (dropping its notes/building_type columns) is
a separate migration once the new tables are confirmed stable in production.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f9'
branch_labels = None
depends_on = None


def upgrade():
    # ── building_profiles ────────────────────────────────────────────────────
    op.create_table(
        "building_profiles",
        sa.Column("id",                 UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",         UUID(as_uuid=True), nullable=False),

        # Address identity
        sa.Column("normalised_address", sa.String(200), nullable=False),
        sa.Column("block_key",          sa.String(60),  nullable=False),

        # Delivery character and routing signal
        sa.Column("building_type",      sa.String(30),  nullable=False),
        sa.Column("workload_class",     sa.String(20),  nullable=False),

        # Operational notes
        sa.Column("raw_note",           sa.Text,   nullable=True),
        sa.Column("operational_note",   sa.Text,   nullable=True),
        sa.Column("note_verified",      sa.Boolean, server_default="false", nullable=False),

        # Building type verification lifecycle
        sa.Column("building_type_status",           sa.String(20), server_default="pending", nullable=False),
        sa.Column("building_type_agreement_count",  sa.Integer,    server_default="0",       nullable=False),

        # Promotion pipeline
        sa.Column("nomination_status",  sa.String(20), nullable=True),

        # Note verification audit
        sa.Column("note_verified_by",       UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note_verified_by_name",  sa.String(100), nullable=True),
        sa.Column("note_verified_at",       sa.DateTime(timezone=True), nullable=True),

        # Submission audit
        sa.Column("submitted_by",       UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitted_by_name",  sa.String(100), nullable=False),
        sa.Column("submitted_at",       sa.DateTime(timezone=True), nullable=True),

        # Building type verification audit
        sa.Column("verified_by",        UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_by_name",   sa.String(100), nullable=True),
        sa.Column("verified_at",        sa.DateTime(timezone=True), nullable=True),

        # Row creation audit
        sa.Column("created_by",         UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_name",    sa.String(100), nullable=True),
        sa.Column("created_at",         sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at",         sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        sa.UniqueConstraint("company_id", "normalised_address", name="uq_building_profiles_company_address"),
    )
    op.create_index("ix_building_profiles_company_id", "building_profiles", ["company_id"])
    op.create_index("ix_building_profiles_block_key",  "building_profiles", ["block_key"])

    # ── building_profile_library ─────────────────────────────────────────────
    op.create_table(
        "building_profile_library",
        sa.Column("id",                 UUID(as_uuid=True), primary_key=True),

        # Address identity — global key, no company_id
        sa.Column("normalised_address", sa.String(200), nullable=False),
        sa.Column("block_key",          sa.String(60),  nullable=False),

        # Delivery character and routing signal
        sa.Column("building_type",      sa.String(30),  nullable=False),
        sa.Column("workload_class",     sa.String(20),  nullable=False),

        # Operational note — captain-verified tip, promoted from source company record
        sa.Column("operational_note",   sa.Text,   nullable=True),
        sa.Column("note_verified",      sa.Boolean, server_default="false", nullable=False),
        sa.Column("note_verified_by",      UUID(as_uuid=True), nullable=True),
        sa.Column("note_verified_by_name", sa.String(100), nullable=True),
        sa.Column("note_verified_at",      sa.DateTime(timezone=True), nullable=True),

        # Library lifecycle
        sa.Column("library_status",         sa.String(20), server_default="active", nullable=False),
        sa.Column("agreement_source_count", sa.Integer,    server_default="0",      nullable=False),
        sa.Column("last_conflict_at",       sa.DateTime(timezone=True), nullable=True),

        # Promotion audit
        sa.Column("promoted_from_company_ids", ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("promoted_at",               sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_by",               UUID(as_uuid=True), nullable=True),
        sa.Column("promoted_by_name",          sa.String(100), nullable=True),

        # Record audit
        sa.Column("created_by",         UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_name",    sa.String(100), nullable=True),
        sa.Column("created_at",         sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by",         UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_name",    sa.String(100), nullable=True),
        sa.Column("updated_at",         sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        sa.UniqueConstraint("normalised_address", name="uq_building_profile_library_address"),
    )
    op.create_index("ix_building_profile_library_block_key", "building_profile_library", ["block_key"])


def downgrade():
    op.drop_table("building_profile_library")
    op.drop_table("building_profiles")
