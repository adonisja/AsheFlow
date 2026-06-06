"""add walker_trips table

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "e6f7a8b9c0d1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "walker_trips",
        sa.Column("id",                        UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id",                UUID(as_uuid=True), nullable=False),
        sa.Column("walker_route_id",           UUID(as_uuid=True), sa.ForeignKey("walker_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trip_number",               sa.Integer(),       nullable=False),
        sa.Column("status",                    sa.String(20),      nullable=False, server_default="pending"),
        sa.Column("departed_at",               sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at",               sa.DateTime(timezone=True), nullable=True),
        sa.Column("suggested_walker_route_id", UUID(as_uuid=True), sa.ForeignKey("walker_routes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",                sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("walker_route_id", "trip_number", name="uq_walker_trips_route_trip"),
    )
    op.create_index("ix_walker_trips_company_id",      "walker_trips", ["company_id"])
    op.create_index("ix_walker_trips_walker_route_id", "walker_trips", ["walker_route_id"])


def downgrade():
    op.drop_index("ix_walker_trips_walker_route_id", table_name="walker_trips")
    op.drop_index("ix_walker_trips_company_id",      table_name="walker_trips")
    op.drop_table("walker_trips")
