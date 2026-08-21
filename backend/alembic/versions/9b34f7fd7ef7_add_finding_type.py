"""Add timecard_adjustments.finding_type (ADR-233 Phase 4)

Records which kind of ADP/Flex disagreement an adjustment represents:

  break_time_mismatch   both have a break, windows differ >5 min
  break_missing_in_adp  Flex has a qualifying break, ADP's breaks[] is empty
  break_short_in_adp    Flex >=30 min, ADP's break is shorter
  entry_missing_in_adp  Flex working day, ADP has no timeEntries at all

Drives operational routing — what a manager does about a missing break differs
from a shifted one — not compliance reporting, which is ADP's.

Nullable with a NULL-tolerant CHECK: existing rows predate the column. They are
not backfilled, because detection has never actually run (the pay period guard
skipped every timecard, ADR-233 P0), so there are none in any environment. The
column is left nullable rather than defaulted so a legacy row stays visibly
untyped instead of being mislabelled.

Revision ID: 9b34f7fd7ef7
Revises: 37a44791d086
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "9b34f7fd7ef7"
down_revision = "37a44791d086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "timecard_adjustments",
        sa.Column("finding_type", sa.String(40), nullable=True),
    )
    op.create_index(
        "ix_timecard_adjustments_finding_type",
        "timecard_adjustments",
        ["finding_type"],
    )
    op.create_check_constraint(
        "ck_timecard_adjustment_finding_type",
        "timecard_adjustments",
        "finding_type IS NULL OR finding_type IN ("
        "'break_time_mismatch', 'break_missing_in_adp', "
        "'break_short_in_adp', 'entry_missing_in_adp')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_timecard_adjustment_finding_type", "timecard_adjustments", type_="check"
    )
    op.drop_index("ix_timecard_adjustments_finding_type", table_name="timecard_adjustments")
    op.drop_column("timecard_adjustments", "finding_type")
