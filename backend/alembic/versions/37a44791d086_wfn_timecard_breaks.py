"""Replace adp_timecard_segments with adp_timecard_breaks (ADR-233 Phase 3)

Workforce Now reports breaks explicitly —
teamTimeCards[].timeCards[].dayEntries[].timeEntries[].breaks[], "Meal times" in
ADP's own schema. RUN had no such field, so AsheFlow inferred a break from the
gap between clock-out and the next clock-in and stored those pairs as segments.
The two shapes do not map, and gap inference is wrong under WFN: it would treat
any long non-break gap as a meal and propose it as a payroll correction.

adp_timecard_segments is dropped rather than extended. It holds no data worth
migrating — mismatch detection has never run (the pay period guard skipped every
timecard, ADR-233 P0), so nothing downstream consumed it.

Also adds the two identifiers the WFN write requires and nothing previously
captured:
  - employees.hr_system_work_assignment_id_adp — PFID, from
    workAssignments[].itemID; required in every timeEntries.modify eventContext.
  - timecard_adjustments.adp_entry_id — timeEntries[].entryID captured at
    detection; the write addresses the correction by it.

Revision ID: 37a44791d086
Revises: 8e4be349b5f1
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "37a44791d086"
down_revision = "8e4be349b5f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adp_timecard_breaks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timecard_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("adp_entry_id", sa.String(64), nullable=False),
        sa.Column("break_item_id", sa.String(64), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("break_type_code", sa.String(40), nullable=True),
        sa.Column("break_status", sa.String(40), nullable=True),
        sa.Column("override_type_code", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["timecard_id"], ["adp_timecards.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "timecard_id", "adp_entry_id", "break_item_id",
            name="uq_adp_timecard_breaks_entry_item",
        ),
    )
    op.create_index("ix_adp_timecard_breaks_company_id", "adp_timecard_breaks", ["company_id"])
    op.create_index("ix_adp_timecard_breaks_timecard_id", "adp_timecard_breaks", ["timecard_id"])
    op.create_index("ix_adp_timecard_breaks_adp_entry_id", "adp_timecard_breaks", ["adp_entry_id"])

    op.add_column(
        "employees",
        sa.Column("hr_system_work_assignment_id_adp", sa.String(64), nullable=True),
    )
    op.add_column(
        "timecard_adjustments",
        sa.Column("adp_entry_id", sa.String(64), nullable=True),
    )

    op.drop_table("adp_timecard_segments")


def downgrade() -> None:
    # Recreated to its pre-Phase-3 shape. Data is not restored — the table was
    # empty in every environment (detection never ran).
    op.create_table(
        "adp_timecard_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timecard_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["timecard_id"], ["adp_timecards.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("timecard_id", "segment_index", name="uq_adp_timecard_segments_order"),
    )
    op.create_index("ix_adp_timecard_segments_company_id", "adp_timecard_segments", ["company_id"])
    op.create_index("ix_adp_timecard_segments_timecard_id", "adp_timecard_segments", ["timecard_id"])

    op.drop_column("timecard_adjustments", "adp_entry_id")
    op.drop_column("employees", "hr_system_work_assignment_id_adp")

    op.drop_index("ix_adp_timecard_breaks_adp_entry_id", table_name="adp_timecard_breaks")
    op.drop_index("ix_adp_timecard_breaks_timecard_id", table_name="adp_timecard_breaks")
    op.drop_index("ix_adp_timecard_breaks_company_id", table_name="adp_timecard_breaks")
    op.drop_table("adp_timecard_breaks")
