"""add damaged_packages table

Revision ID: c2fcfe15c4ce
Revises: d0e1f2a3b4c5
Create Date: 2026-07-09

Pre-route damage reporting (ADR-190): damage discovered at station sort,
truck load, or loose in the truck — before any Route exists, where
RTSPackage (route_id non-nullable) can't reach.

truck_assignment_id is SET NULL, not CASCADE: damage reports are physical-
event records and must survive clear-dispatch (deliberate ADR-182 divergence).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'c2fcfe15c4ce'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "damaged_packages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("route_date", sa.Date(), nullable=False, index=True),
        sa.Column("tba_number", sa.String(50), nullable=False),
        sa.Column("bag_id", sa.String(50), nullable=True),
        sa.Column("truck_assignment_id", UUID(as_uuid=True),
                  sa.ForeignKey("truck_assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("damage_notes", sa.Text(), nullable=False),
        sa.Column("normalised_address", sa.String(200), nullable=True, index=True),
        sa.Column("reported_by", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reported_by_name", sa.String(100), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("resolution_status", sa.String(20), nullable=False,
                  server_default="open", index=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by_name", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("damaged_packages")
