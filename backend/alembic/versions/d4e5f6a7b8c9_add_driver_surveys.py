"""add driver survey tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-06

Two tables:
  driver_surveys         — one per company per dispatch date (management activates).
  driver_survey_responses — one response per respondent per survey.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_surveys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_driver_surveys_company_id", "driver_surveys", ["company_id"])
    op.create_index("ix_driver_surveys_date", "driver_surveys", ["date"])
    op.create_unique_constraint(
        "uq_driver_survey_company_date", "driver_surveys", ["company_id", "date"]
    )

    op.create_table(
        "driver_survey_responses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("survey_id", UUID(as_uuid=True),
                  sa.ForeignKey("driver_surveys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("respondent_id", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("truck_assignment_id", UUID(as_uuid=True),
                  sa.ForeignKey("truck_assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("routes_organized",      sa.Boolean(), nullable=False),
        sa.Column("anchor_point_location", sa.Boolean(), nullable=False),
        sa.Column("supplies_ready",        sa.Boolean(), nullable=False),
        sa.Column("driver_support",        sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_driver_survey_responses_company_id", "driver_survey_responses", ["company_id"])
    op.create_index("ix_driver_survey_responses_survey_id",  "driver_survey_responses", ["survey_id"])
    op.create_unique_constraint(
        "uq_driver_survey_response_per_respondent",
        "driver_survey_responses",
        ["survey_id", "respondent_id"],
    )


def downgrade() -> None:
    op.drop_table("driver_survey_responses")
    op.drop_table("driver_surveys")
