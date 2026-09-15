"""ADR-415: public collection quarantine tables

Revision ID: 0e5917d6e99f
Revises: 6d6b30ddb9b9
Create Date: 2026-09-15

Adds the two tables behind the public collection page:

  collection_tokens          — revocable campaign keys; company_id is resolved
                               from here, never from a request body.
  collected_address_profiles — quarantine. Nothing reads it except an
                               authenticated promotion review, so an anonymous
                               submitter can never reach building_profiles and
                               change how a real tenant's routes are built.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0e5917d6e99f"
down_revision = "6d6b30ddb9b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_cap", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_collection_tokens_company_id", "collection_tokens", ["company_id"])
    # Unique AND indexed: every submission looks the token up by value, and two
    # campaigns sharing a secret would make attribution meaningless.
    op.create_index("ix_collection_tokens_token", "collection_tokens", ["token"], unique=True)

    op.create_table(
        "collected_address_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("collection_tokens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("building_type", sa.String(30), nullable=False),
        sa.Column("workload_class", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("opens_at", sa.Time(), nullable=True),
        sa.Column("closes_at", sa.Time(), nullable=True),
        sa.Column("break_start", sa.Time(), nullable=True),
        sa.Column("break_end", sa.Time(), nullable=True),
        sa.Column("troublesome", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("collected_by", sa.String(100), nullable=True),
        sa.Column("collected_on", sa.Date(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_collected_profiles_company_id", "collected_address_profiles", ["company_id"])
    op.create_index("ix_collected_profiles_token_id", "collected_address_profiles", ["token_id"])
    op.create_index("ix_collected_profiles_review_status", "collected_address_profiles", ["review_status"])
    # A resubmit after a dropped connection is the normal case in the field, so
    # the duplicate is absorbed by this constraint rather than rejected upstream.
    op.create_unique_constraint(
        "uq_collected_profiles_token_day_address",
        "collected_address_profiles",
        ["token_id", "collected_on", "address"],
    )


def downgrade() -> None:
    op.drop_table("collected_address_profiles")
    op.drop_table("collection_tokens")
