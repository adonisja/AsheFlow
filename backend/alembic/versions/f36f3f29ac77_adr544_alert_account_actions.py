"""ADR-544: record a reminder sent, or sessions ended, from an account alert.

Revision ID: f36f3f29ac77
Revises: 1617e68a20c4
"""
from alembic import op
import sqlalchemy as sa

revision = "f36f3f29ac77"
down_revision = "1617e68a20c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_alerts", sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("platform_alerts", sa.Column("reminded_by_email", sa.String(320), nullable=True))
    op.add_column("platform_alerts", sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("platform_alerts", sa.Column("sessions_ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("platform_alerts", sa.Column("sessions_ended_by_email", sa.String(320), nullable=True))


def downgrade() -> None:
    for col in ("sessions_ended_by_email", "sessions_ended_at", "reminder_count",
                "reminded_by_email", "reminded_at"):
        op.drop_column("platform_alerts", col)
