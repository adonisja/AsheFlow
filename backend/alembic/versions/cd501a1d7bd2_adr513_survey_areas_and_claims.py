"""ADR-513: survey areas from public boundaries, block claims, door unlocks.

Revision ID: cd501a1d7bd2
Revises: de5c8cf85778
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "cd501a1d7bd2"
down_revision = "de5c8cf85778"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "survey_areas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("boundary_dataset", sa.String(20), nullable=False),
        sa.Column("address_dataset", sa.String(20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("declared_by", sa.String(255), nullable=False),
        sa.Column("declared_by_kind", sa.String(20), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(255), nullable=True),
        sa.CheckConstraint("kind IN ('nta', 'cd')", name="ck_survey_area_kind"),
        sa.CheckConstraint("declared_by_kind IN ('super_admin', 'platform_support')",
                           name="ck_survey_area_declared_by_kind"),
    )
    op.create_index("uq_survey_area_open_boundary", "survey_areas", ["kind", "code"], unique=True,
                    postgresql_where=sa.text("closed_at IS NULL"))

    op.create_table(
        "survey_area_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("area_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("survey_areas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("borough", sa.String(1), nullable=False),
        sa.Column("block_key", sa.String(100), nullable=False),
        sa.Column("street", sa.String(120), nullable=False),
        sa.Column("description", sa.String(160), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("door_snapshot", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("borough IN ('1', '2', '3', '4', '5')", name="ck_survey_area_block_borough"),
        sa.UniqueConstraint("area_id", "borough", "block_key", name="uq_survey_area_block"),
    )
    op.create_index("ix_survey_area_blocks_area_id", "survey_area_blocks", ["area_id"])
    op.create_index("ix_survey_area_blocks_block", "survey_area_blocks", ["borough", "block_key"])

    op.add_column("survey_walks", sa.Column("borough", sa.String(1), nullable=True))
    op.add_column("survey_walks", sa.Column(
        "area_id", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("survey_areas.id", ondelete="RESTRICT"), nullable=True))
    op.create_index("ix_survey_walks_area_id", "survey_walks", ["area_id"])

    op.create_table(
        "survey_block_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("area_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("survey_areas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("area_block_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("survey_area_blocks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("borough", sa.String(1), nullable=False),
        sa.Column("block_key", sa.String(100), nullable=False),
        sa.Column("writer_sub", sa.String(255), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(20), nullable=True),
        sa.Column("walk_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("survey_walks.id", ondelete="RESTRICT"), nullable=True),
        sa.CheckConstraint(
            "release_reason IS NULL OR release_reason IN ('released', 'walk_closed', 'area_closed')",
            name="ck_survey_claim_release_reason"),
        sa.CheckConstraint("(released_at IS NULL) = (release_reason IS NULL)",
                           name="ck_survey_claim_released_with_reason"),
    )
    op.create_index("ix_survey_block_claims_area_id", "survey_block_claims", ["area_id"])
    op.create_index("ix_survey_block_claims_writer_sub", "survey_block_claims", ["writer_sub"])
    op.create_index("ix_survey_block_claims_block", "survey_block_claims", ["borough", "block_key"])

    op.create_table(
        "survey_door_unlocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("borough", sa.String(1), nullable=False),
        sa.Column("block_key", sa.String(100), nullable=False),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("unlocked_by", sa.String(255), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_survey_door_unlocks_block", "survey_door_unlocks", ["borough", "block_key"])


def downgrade():
    op.drop_index("ix_survey_door_unlocks_block", table_name="survey_door_unlocks")
    op.drop_table("survey_door_unlocks")
    op.drop_index("ix_survey_block_claims_block", table_name="survey_block_claims")
    op.drop_index("ix_survey_block_claims_writer_sub", table_name="survey_block_claims")
    op.drop_index("ix_survey_block_claims_area_id", table_name="survey_block_claims")
    op.drop_table("survey_block_claims")
    op.drop_index("ix_survey_walks_area_id", table_name="survey_walks")
    op.drop_column("survey_walks", "area_id")
    op.drop_column("survey_walks", "borough")
    op.drop_index("ix_survey_area_blocks_block", table_name="survey_area_blocks")
    op.drop_index("ix_survey_area_blocks_area_id", table_name="survey_area_blocks")
    op.drop_table("survey_area_blocks")
    op.drop_index("uq_survey_area_open_boundary", table_name="survey_areas")
    op.drop_table("survey_areas")
