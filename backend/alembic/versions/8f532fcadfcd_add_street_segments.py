"""Add street_segments — persistent LION topology map (ADR-236)

Revision ID: 8f532fcadfcd
Revises: 9b34f7fd7ef7
Create Date: 2026-07-27

Global (no company_id) by design: street topology is public geography, and the
table stores only street names + LION ids — no addresses, no package data. See
the model docstring and ADR-236 for the multi-tenancy rationale.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "8f532fcadfcd"
down_revision = "9b34f7fd7ef7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "street_segments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("segment_id", sa.String(32), nullable=False),
        sa.Column("from_lion_node_id", sa.String(32), nullable=True),
        sa.Column("to_lion_node_id", sa.String(32), nullable=True),
        sa.Column("street_name", sa.String(120), nullable=True),
        sa.Column("borough", sa.String(30), nullable=True),
        sa.Column("block_key", sa.String(60), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="package_address"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("segment_id", name="uq_street_segments_segment_id"),
    )
    # Adjacency is "shares a LION node", so both node columns are lookup keys.
    op.create_index("ix_street_segments_from_node", "street_segments", ["from_lion_node_id"])
    op.create_index("ix_street_segments_to_node", "street_segments", ["to_lion_node_id"])
    # Bounding-box prefilter for the per-company zone fragment (no PostGIS).
    op.create_index("ix_street_segments_lat_lng", "street_segments", ["lat", "lng"])


def downgrade() -> None:
    op.drop_index("ix_street_segments_lat_lng", table_name="street_segments")
    op.drop_index("ix_street_segments_to_node", table_name="street_segments")
    op.drop_index("ix_street_segments_from_node", table_name="street_segments")
    op.drop_table("street_segments")
