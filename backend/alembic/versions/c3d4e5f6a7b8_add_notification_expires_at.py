"""add expires_at to notifications

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-05

Adds an optional expires_at column to the notifications table.
- dispatch_assignment: set to the confirmation deadline (company cutoff time on dispatch_date)
- dispatch_assignment_info: set to midnight at end of dispatch_date
- all other types: NULL (never expires)

The GET /notifications endpoint filters out expired rows so they never
reach the client. The prune endpoint also hard-deletes them.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_expires_at",
        "notifications",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_expires_at", table_name="notifications")
    op.drop_column("notifications", "expires_at")
