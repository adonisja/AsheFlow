"""ADR-357: crew pins

Revision ID: e28c466df97e
Revises: 80814ae0a3dd
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e28c466df97e"
down_revision = "80814ae0a3dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crew_pins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column(
            "driver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("inactive_reason", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # One pin per driver: two active pins on one driver cannot both be
        # honoured and choosing between them would be arbitrary (ADR-357 D6).
        sa.UniqueConstraint("company_id", "driver_id", name="uq_crew_pin_driver"),
    )
    op.create_index("ix_crew_pins_company_id", "crew_pins", ["company_id"])
    op.create_index(
        "ix_crew_pins_company_active", "crew_pins", ["company_id", "is_active"]
    )

    op.create_table(
        "crew_pin_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_pins.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("pin_id", "employee_id", name="uq_crew_pin_member"),
    )
    op.create_index("ix_crew_pin_members_company_id", "crew_pin_members", ["company_id"])
    op.create_index("ix_crew_pin_members_employee", "crew_pin_members", ["employee_id"])


def downgrade() -> None:
    op.drop_table("crew_pin_members")
    op.drop_table("crew_pins")
