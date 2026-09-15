"""ADR-417 D3: collected_walker_days

The route log's quarantine table. Nothing joins to it; the eventual PII strip
is a DELETE.

Revision ID: c8fee0459a8a
Revises: 9c32a580c1d3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c8fee0459a8a"
down_revision = "9c32a580c1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collected_walker_days",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("walker_name", sa.String(length=100), nullable=False),
        sa.Column("collected_on", sa.Date(), nullable=False),
        sa.Column("arrival_time", sa.String(length=5), nullable=True),
        sa.Column("departure_time", sa.String(length=5), nullable=True),
        sa.Column("route_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["token_id"], ["collection_tokens.id"],
                                ondelete="CASCADE"),
        # ADR-417 D5: the upsert key. A resubmission replaces the day.
        sa.UniqueConstraint("token_id", "collected_on", "walker_name",
                            name="uq_collected_days_token_day_walker"),
    )
    op.create_index("ix_collected_walker_days_company_id",
                    "collected_walker_days", ["company_id"])
    op.create_index("ix_collected_walker_days_token_id",
                    "collected_walker_days", ["token_id"])
    op.create_index("ix_collected_walker_days_collected_on",
                    "collected_walker_days", ["collected_on"])


def downgrade() -> None:
    op.drop_index("ix_collected_walker_days_collected_on",
                  table_name="collected_walker_days")
    op.drop_index("ix_collected_walker_days_token_id",
                  table_name="collected_walker_days")
    op.drop_index("ix_collected_walker_days_company_id",
                  table_name="collected_walker_days")
    op.drop_table("collected_walker_days")
