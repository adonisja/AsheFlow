"""scorecard appeals + line items

Revision ID: 732d8bc120eb
Revises: 380b54c07d88
Create Date: 2026-07-31

Two new tables (ADR-243). No backfill — nothing existed before.

company_id is stamped on BOTH tables, including the child. Reaching the tenant
only through appeal_id would make scorecard_appeal_items unusable as a query root
("which metrics do we win most often?") without a join being the only thing
preventing a cross-tenant leak. Same lesson as migration 380b54c07d88.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "732d8bc120eb"
down_revision = "380b54c07d88"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scorecard_appeals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scorecard_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("scorecards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week", sa.String(10), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False, server_default="company"),
        # SET NULL, not CASCADE: an appeal is a financial record and must outlive
        # the employee it concerns.
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitted_by_name", sa.String(100), nullable=True),
        sa.Column("amazon_reference", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by_name", sa.String(100), nullable=True),
        sa.Column("outcome_notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'won', 'lost', 'withdrawn')",
            name="ck_scorecard_appeals_status",
        ),
    )
    op.create_index("ix_scorecard_appeals_company_id", "scorecard_appeals", ["company_id"])
    op.create_index("ix_scorecard_appeals_scorecard_id", "scorecard_appeals", ["scorecard_id"])
    op.create_index("ix_scorecard_appeals_week", "scorecard_appeals", ["week"])
    op.create_index("ix_scorecard_appeals_status", "scorecard_appeals", ["status"])
    op.create_index("ix_scorecard_appeals_employee_id", "scorecard_appeals", ["employee_id"])

    op.create_table(
        "scorecard_appeal_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appeal_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("scorecard_appeals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_key", sa.String(50), nullable=False),
        sa.Column("metric_label", sa.String(100), nullable=False),
        sa.Column("amazon_value", sa.String(50), nullable=True),
        sa.Column("our_value", sa.String(50), nullable=True),
        sa.Column("delta", sa.Float(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("claim", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("outcome_notes", sa.Text(), nullable=True),
        sa.Column("corrected_value", sa.String(50), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("appeal_id", "metric_key", name="uq_appeal_items_appeal_metric"),
        sa.CheckConstraint(
            "outcome IN ('pending', 'accepted', 'rejected')",
            name="ck_scorecard_appeal_items_outcome",
        ),
    )
    op.create_index("ix_scorecard_appeal_items_company_id", "scorecard_appeal_items", ["company_id"])
    op.create_index("ix_scorecard_appeal_items_appeal_id", "scorecard_appeal_items", ["appeal_id"])
    op.create_index("ix_scorecard_appeal_items_outcome", "scorecard_appeal_items", ["outcome"])


def downgrade():
    op.drop_table("scorecard_appeal_items")
    op.drop_table("scorecard_appeals")
