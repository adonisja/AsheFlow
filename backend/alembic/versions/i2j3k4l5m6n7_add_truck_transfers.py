"""add truck transfers table

Revision ID: i2j3k4l5m6n7
Revises: e5f6a7b8c9d0
Create Date: 2026-06-05

Records intra-day transfers of field-role employees between trucks.
The original AssignmentMember row is preserved; this table is an
append-only audit trail of mid-dispatch moves.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "i2j3k4l5m6n7"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "truck_transfers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "employee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_assignment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("truck_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_assignment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("truck_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("transfer_date", sa.Date(), nullable=False),
        sa.Column(
            "transferred_by",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column(
            "transferred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_truck_transfers_company_id",    "truck_transfers", ["company_id"])
    op.create_index("ix_truck_transfers_employee_id",   "truck_transfers", ["employee_id"])
    op.create_index("ix_truck_transfers_transfer_date", "truck_transfers", ["transfer_date"])


def downgrade() -> None:
    op.drop_index("ix_truck_transfers_transfer_date", table_name="truck_transfers")
    op.drop_index("ix_truck_transfers_employee_id",   table_name="truck_transfers")
    op.drop_index("ix_truck_transfers_company_id",    table_name="truck_transfers")
    op.drop_table("truck_transfers")
