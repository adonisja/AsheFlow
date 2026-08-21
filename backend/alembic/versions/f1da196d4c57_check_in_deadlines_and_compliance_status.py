"""check_in_deadlines table + crew_compliance.status (ADR-228)

Revision ID: f1da196d4c57
Revises: f9d65c1f723f
Create Date: 2026-07-22

ADR-228: configurable per-check-in deadlines (check_in_deadlines: company_id,
sequence, offset_minutes past the attendance reference) replacing the flat
CompanyConfig.driver_checkin_count; and crew_compliance.status (draft|submitted)
so compliance can be captured live on the Crew Roster page and finalized by
Check-In #1.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f1da196d4c57"
down_revision = "f9d65c1f723f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "check_in_deadlines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "sequence", name="uq_check_in_deadline_company_sequence"),
    )
    op.create_index("ix_check_in_deadlines_company_id", "check_in_deadlines", ["company_id"])

    op.add_column(
        "crew_compliance",
        sa.Column("status", sa.String(length=20), server_default="submitted", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("crew_compliance", "status")
    op.drop_index("ix_check_in_deadlines_company_id", table_name="check_in_deadlines")
    op.drop_table("check_in_deadlines")
