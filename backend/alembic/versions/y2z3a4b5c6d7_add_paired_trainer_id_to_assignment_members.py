"""add paired_trainer_id to assignment_members

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-05-29

Persists the specific trainer paired with a trainee during dispatch so that
training records, Discord DMs, and dashboards all reference the correct pairing
rather than inferring it from truck position at publish time.

Nullable — only set for rows where role = 'trainee'. All other roles leave it NULL.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'y2z3a4b5c6d7'
down_revision = 'x1y2z3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assignment_members",
        sa.Column(
            "paired_trainer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_assignment_members_paired_trainer_id",
        "assignment_members",
        ["paired_trainer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assignment_members_paired_trainer_id", table_name="assignment_members")
    op.drop_column("assignment_members", "paired_trainer_id")
