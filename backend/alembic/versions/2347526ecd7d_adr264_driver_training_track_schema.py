"""ADR-264 — driver training track: config, solo flag, track-scoped quiz bank

Revision ID: 2347526ecd7d
Revises: ec6569da03b4
Create Date: 2026-08-22

Three additive columns. All three carry a server_default so existing rows stay
correct with no backfill:

- company_configs.driver_training_days — nullable, resolved via PLATFORM_DEFAULTS
  (5). Phases, not calendar days.
- training_records.supervised — server_default true. Every historical walker
  record WAS supervised, so the default is the truth rather than a placeholder.
- graduation_quiz_templates.roles — server_default '{walker}'. Every question
  authored to date is a walker question; without this default a track-scoped
  query would return an empty bank for a company that has a full one.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "2347526ecd7d"
down_revision = "ec6569da03b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "company_configs",
        sa.Column("driver_training_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "training_records",
        sa.Column("supervised", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "graduation_quiz_templates",
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String(length=20)),
            nullable=False,
            server_default="{walker}",
        ),
    )


def downgrade():
    op.drop_column("graduation_quiz_templates", "roles")
    op.drop_column("training_records", "supervised")
    op.drop_column("company_configs", "driver_training_days")
