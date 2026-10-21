"""ADR-555 D2: withdrawing a contributor's survey records (append-only).

Revision ID: 5486f5848f58
Revises: 946148bf49cc
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5486f5848f58"
down_revision = "946148bf49cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "survey_withdrawals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("contributor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("survey_contributors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("writer_sub", sa.String(255), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("withdrawn_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("from_date <= to_date", name="ck_survey_withdrawal_range"),
    )
    op.create_index("ix_survey_withdrawals_contributor_id", "survey_withdrawals", ["contributor_id"])
    op.create_table(
        "survey_observation_withdrawals",
        sa.Column("observation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("survey_observations.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("withdrawal_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("survey_withdrawals.id", ondelete="RESTRICT"), nullable=False),
    )
    op.create_index("ix_survey_observation_withdrawals_withdrawal_id",
                    "survey_observation_withdrawals", ["withdrawal_id"])


def downgrade() -> None:
    op.drop_index("ix_survey_observation_withdrawals_withdrawal_id", table_name="survey_observation_withdrawals")
    op.drop_table("survey_observation_withdrawals")
    op.drop_index("ix_survey_withdrawals_contributor_id", table_name="survey_withdrawals")
    op.drop_table("survey_withdrawals")
