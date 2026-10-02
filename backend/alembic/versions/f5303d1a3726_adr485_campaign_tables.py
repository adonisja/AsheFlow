"""ADR-485: the campaign system's seven tables.

Admin-designed surveys scoped to a day on a truck. Replaces the four hardcoded
Boolean columns on `driver_survey_responses` with question rows and typed
answer rows, so adding a question stops being a migration.

CREATE ONLY. The existing driver_survey tables are untouched here: their
migration and drop is ADR-485 D17, a separate revision that runs after the
routers exist to serve the new shape. A table dropped before its replacement
can serve traffic is an outage, not a migration.

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: f5303d1a3726
Revises: b75e2dbe24d4
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f5303d1a3726"
down_revision = "b75e2dbe24d4"
branch_labels = None
depends_on = None

# Mirrors campaign.VALID_* . Duplicated deliberately: a migration that imports
# live code breaks the moment that code is renamed (ADR-427).
_SUBJECT_ROLES = "'driver', 'trainer', 'trainee', 'walker', 'captain', 'driver_trainee'"
_KINDS = "'bool', 'scale', 'text', 'choice'"
_MODES = "'daily', 'weekly_fixed', 'weekly_random', 'monthly'"


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("subject_role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="active"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_campaign_status"),
        sa.CheckConstraint(f"subject_role IN ({_SUBJECT_ROLES})",
                           name="ck_campaign_subject_role"),
    )

    op.create_table(
        "campaign_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("scale_min", sa.Integer(), nullable=True),
        sa.Column("scale_max", sa.Integer(), nullable=True),
        sa.Column("choices", postgresql.JSONB(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_questions.id", ondelete="SET NULL"),
                  nullable=True),
        sa.UniqueConstraint("campaign_id", "position", "retired_at",
                            name="uq_campaign_question_position"),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name="ck_campaign_question_kind"),
        sa.CheckConstraint(
            "(kind <> 'scale') OR (scale_min IS NOT NULL AND scale_max IS NOT NULL"
            " AND scale_min < scale_max)",
            name="ck_campaign_question_scale_bounds"),
        sa.CheckConstraint("(kind <> 'choice') OR (choices IS NOT NULL)",
                           name="ck_campaign_question_choices"),
    )

    op.create_table(
        "campaign_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("ended_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(f"mode IN ({_MODES})", name="ck_campaign_schedule_mode"),
        sa.CheckConstraint("(mode <> 'weekly_fixed') OR (weekday BETWEEN 0 AND 6)",
                           name="ck_campaign_schedule_weekday"),
        sa.CheckConstraint("ends_on >= starts_on", name="ck_campaign_schedule_range"),
    )

    op.create_table(
        "campaign_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opened_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_schedules.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("notified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_assignment_ids", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.UniqueConstraint("campaign_id", "date", name="uq_campaign_run_date"),
        sa.CheckConstraint("closes_at > opens_at", name="ck_campaign_run_window"),
    )

    op.create_table(
        "campaign_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_runs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("respondent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("truck_assignment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("truck_assignments.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "respondent_id", name="uq_campaign_response"),
        sa.CheckConstraint("respondent_id <> subject_id",
                           name="ck_campaign_response_not_self"),
    )

    op.create_table(
        "campaign_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("response_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_responses.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("question_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_questions.id", ondelete="RESTRICT"),
                  nullable=False, index=True),
        sa.Column("bool_value", sa.Boolean(), nullable=True),
        sa.Column("int_value", sa.Integer(), nullable=True),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.String(length=10), nullable=True),
        sa.Column("sentiment_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("names_redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("response_id", "question_id", name="uq_campaign_answer"),
        sa.CheckConstraint(
            "(CASE WHEN bool_value IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN int_value  IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN text_value IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_campaign_answer_exactly_one_value"),
    )

    op.create_table(
        "campaign_attribution_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_runs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("denied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drops all seven. Safe in a way D17's drop is not: these tables are
    created empty by this revision, so a downgrade immediately after an upgrade
    loses nothing. A downgrade run LATER destroys real campaign data, which is
    the ordinary meaning of a downgrade and is why it is not guarded here."""
    for table in (
        "campaign_attribution_requests",
        "campaign_answers",
        "campaign_responses",
        "campaign_runs",
        "campaign_schedules",
        "campaign_questions",
        "campaigns",
    ):
        op.drop_table(table)
