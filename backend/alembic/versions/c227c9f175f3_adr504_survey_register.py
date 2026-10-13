"""ADR-504: the survey register, kept outside any tenant.

Revision ID: c227c9f175f3
Revises: 5f305baedeec
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c227c9f175f3"
down_revision = "5f305baedeec"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "survey_contributors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cognito_sub", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("agreement_version", sa.String(20), nullable=False),
        sa.Column("agreement_signed_on", sa.Date(), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("admitted_by", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_survey_contributors_cognito_sub", "survey_contributors", ["cognito_sub"], unique=True)

    op.create_table(
        "survey_walks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("writer_sub", sa.String(255), nullable=False),
        sa.Column("block_key", sa.String(100), nullable=False),
        sa.Column("street", sa.String(120), nullable=False),
        sa.Column("addresses", JSONB(), nullable=False),
        sa.Column("source_dataset", sa.String(20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attest_off_shift", sa.Boolean(), nullable=False),
        sa.Column("attest_unbranded", sa.Boolean(), nullable=False),
        sa.Column("attest_as_self", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attest_off_shift AND attest_unbranded AND attest_as_self",
                           name="ck_survey_walk_attested"),
    )
    op.create_index("ix_survey_walks_writer_sub", "survey_walks", ["writer_sub"])
    op.create_index("ix_survey_walks_block_key", "survey_walks", ["block_key"])

    op.create_table(
        "survey_observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("walk_id", UUID(as_uuid=True),
                  sa.ForeignKey("survey_walks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("writer_sub", sa.String(255), nullable=False),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("bin", sa.String(20), nullable=True),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("building_type", sa.String(30), nullable=False),
        sa.Column("delivery_point", sa.String(20), nullable=True),
        sa.Column("entrance_side", sa.String(120), nullable=True),
        sa.Column("security_desk", sa.Boolean(), nullable=True),
        sa.Column("sign_in_required", sa.Boolean(), nullable=True),
        sa.Column("delivery_mode", sa.String(20), nullable=True),
        sa.Column("floors", sa.Integer(), nullable=True),
        sa.Column("opens_at", sa.Time(), nullable=True),
        sa.Column("closes_at", sa.Time(), nullable=True),
        sa.Column("break_start", sa.Time(), nullable=True),
        sa.Column("break_end", sa.Time(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("attestation", sa.String(200), nullable=False),
        sa.CheckConstraint("source IN ('observed', 'front_desk', 'mailroom', 'security')",
                           name="ck_survey_obs_source"),
        sa.CheckConstraint("delivery_point IS NULL OR delivery_point IN "
                           "('main_entrance', 'service_entrance', 'loading_dock', 'mailroom', 'front_desk')",
                           name="ck_survey_obs_delivery_point"),
        sa.CheckConstraint("delivery_mode IS NULL OR delivery_mode IN ('each_unit', 'one_drop_point')",
                           name="ck_survey_obs_delivery_mode"),
        sa.CheckConstraint("floors IS NULL OR (floors >= 1 AND floors <= 200)", name="ck_survey_obs_floors"),
    )
    op.create_index("ix_survey_observations_walk_id", "survey_observations", ["walk_id"])
    op.create_index("ix_survey_observations_writer_sub", "survey_observations", ["writer_sub"])
    op.create_index("ix_survey_observations_bin", "survey_observations", ["bin"])


def downgrade():
    op.drop_table("survey_observations")
    op.drop_table("survey_walks")
    op.drop_table("survey_contributors")
