"""add ap_arrived_at to assignment_members

Revision ID: 060827c275d1
Revises: cd0ed8874f19
Create Date: 2026-07-10

ADR-145 arrival flow rework: the trainee confirms physical arrival at the
anchor point from their app (stamped here), the paired trainer is notified,
and the trainer then runs the 1.5× rebalance — replacing the web pickers
that let you select arbitrary trainer/trainee combinations.
"""

from alembic import op
import sqlalchemy as sa

revision = '060827c275d1'
down_revision = 'cd0ed8874f19'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assignment_members",
        sa.Column("ap_arrived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assignment_members", "ap_arrived_at")
