"""assignment_member crew status: status + departed_at

Revision ID: 749e69a31f9b
Revises: 6d303e0bc130
Create Date: 2026-07-12

ADR-197 Phase 0b: live crew membership lifecycle. status active|departed|
transferred (default active) + departed_at. F5's live-crew count = active
members. Existing rows default to 'active' — no backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "749e69a31f9b"
down_revision = "6d303e0bc130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assignment_members", sa.Column("status", sa.String(length=20), nullable=False, server_default="active"))
    op.add_column("assignment_members", sa.Column("departed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_assignment_members_status",
        "assignment_members",
        "status IN ('active', 'departed', 'transferred')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_assignment_members_status", "assignment_members", type_="check")
    op.drop_column("assignment_members", "departed_at")
    op.drop_column("assignment_members", "status")
