"""ADR-358: truck pins — a person held to a truck on named weekdays

Revision ID: 34d7780d715d
Revises: e28c466df97e
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "34d7780d715d"
down_revision = "e28c466df97e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "truck_pins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "truck_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trucks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_of_week", sa.String(10), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # One truck per person per day: a second row for the same weekday is a
        # contradiction, not an additional preference.
        sa.UniqueConstraint(
            "employee_id", "day_of_week", name="uq_truck_pin_employee_day"
        ),
        sa.CheckConstraint(
            "day_of_week IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', "
            "'Friday', 'Saturday', 'Sunday')",
            name="ck_truck_pins_day_of_week",
        ),
    )
    op.create_index("ix_truck_pins_company_id", "truck_pins", ["company_id"])
    op.create_index("ix_truck_pins_day_of_week", "truck_pins", ["day_of_week"])
    op.create_index("ix_truck_pins_company_day", "truck_pins", ["company_id", "day_of_week"])


def downgrade() -> None:
    op.drop_table("truck_pins")
