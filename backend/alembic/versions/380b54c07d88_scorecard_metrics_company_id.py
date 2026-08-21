"""stamp company_id on scorecard_metrics

Revision ID: 380b54c07d88
Revises: 8f532fcadfcd
Create Date: 2026-07-30

scorecard_metrics reached its tenant only through scorecard_id. That is safe for
today's reads, which always start from a company-scoped Scorecard query, but it
makes the table unusable as a query ROOT: a cross-company comparison, a
benchmark, or any aggregate that starts from metric rows has no company_id to
filter on, and is one forgotten join away from leaking across tenants
(CLAUDE.md Dimension 1).

Backfills from the parent scorecard before applying NOT NULL, so existing rows
survive the upgrade.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "380b54c07d88"
down_revision = "8f532fcadfcd"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add nullable so existing rows are not rejected on creation.
    op.add_column(
        "scorecard_metrics",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2. Backfill from the parent. This is the authoritative source — every
    #    metric row already belongs to exactly one scorecard.
    op.execute(
        "UPDATE scorecard_metrics AS m "
        "SET company_id = s.company_id "
        "FROM scorecards AS s "
        "WHERE m.scorecard_id = s.id"
    )

    # 3. Orphans cannot exist (scorecard_id is NOT NULL with a CASCADE FK), but
    #    delete defensively so step 4 cannot fail on a stray row.
    op.execute("DELETE FROM scorecard_metrics WHERE company_id IS NULL")

    # 4. Enforce going forward.
    op.alter_column("scorecard_metrics", "company_id", nullable=False)
    op.create_index(
        "ix_scorecard_metrics_company_id", "scorecard_metrics", ["company_id"]
    )


def downgrade():
    op.drop_index("ix_scorecard_metrics_company_id", table_name="scorecard_metrics")
    op.drop_column("scorecard_metrics", "company_id")
