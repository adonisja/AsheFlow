"""scorecards: Amazon weekly scorecard + metric rows (ADR-204)

Revision ID: 75bc7c379db7
Revises: 08db137f3ce5
Create Date: 2026-07-16

ADR-204: store the official Amazon (NYCD) weekly scorecard. scorecards holds one
row per (company, week, scope, employee) — scope individual|company; metric rows
are data-driven so new Amazon metrics need no schema change.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "75bc7c379db7"
down_revision = "08db137f3ce5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("week", sa.String(length=10), nullable=False, index=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="individual"),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("overall_standing", sa.String(length=30), nullable=True),
        sa.Column("source_file_url", sa.Text(), nullable=True),
        sa.Column("entered_by", UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("company_id", "week", "scope", "employee_id", name="uq_scorecards_company_week_scope_employee"),
        sa.CheckConstraint("scope IN ('individual', 'company')", name="ck_scorecards_scope"),
    )
    op.create_table(
        "scorecard_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scorecard_id", UUID(as_uuid=True), sa.ForeignKey("scorecards.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=50), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("tier", sa.String(length=30), nullable=True),
        sa.Column("flag", sa.String(length=20), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("scorecard_id", "key", name="uq_scorecard_metrics_scorecard_key"),
    )


def downgrade() -> None:
    op.drop_table("scorecard_metrics")
    op.drop_table("scorecards")
