"""Add ADP payroll group id and mismatch detection gate (ADR-233)

Two columns on adp_integrations:

- adp_payroll_group_id: identifies the ADP payroll group whose pay period
  schedule adp_pay_period_sync fetches. Nullable — existing integrations have
  no value until an admin configures one, and the sync no-ops without it.

- mismatch_detection_enabled: gates detect_timecard_mismatches per company.
  Defaults False, including for existing rows. Detection has never produced an
  adjustment (adp_pay_periods was never written to, and the task skips every
  timecard when no pay period covers its work_date), so populating that table
  takes detection from zero to real volume. The first pass over the historical
  window can open a large batch, each notifying an employee. Enabling per
  company after reviewing a dry-run count keeps that reviewable.

Revision ID: 8e4be349b5f1
Revises: a9c2e988f92c
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "8e4be349b5f1"
down_revision = "a9c2e988f92c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "adp_integrations",
        sa.Column("adp_payroll_group_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "adp_integrations",
        sa.Column(
            "mismatch_detection_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("adp_integrations", "mismatch_detection_enabled")
    op.drop_column("adp_integrations", "adp_payroll_group_id")
