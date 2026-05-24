"""add truck_zones table

Revision ID: q4r5s6t7u8v9
Revises: p3q4r5s6t7u8
Create Date: 2026-05-17
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'q4r5s6t7u8v9'
down_revision = 'p3q4r5s6t7u8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "truck_zones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("truck_id", UUID(as_uuid=True), sa.ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("truck_polygon", JSONB, nullable=False),
        sa.Column("zone_label", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )

    op.create_index("ix_truck_zones_company_id", "truck_zones", ["company_id"])
    op.create_index("ix_truck_zones_truck_id", "truck_zones", ["truck_id"])
    op.create_index("ix_truck_zones_created_by", "truck_zones", ["created_by"])


def downgrade() -> None:
    op.drop_table("truck_zones")
