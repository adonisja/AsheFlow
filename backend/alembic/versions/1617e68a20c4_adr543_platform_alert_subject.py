"""ADR-543 D2: a platform alert about an account records which account.

Revision ID: 1617e68a20c4
Revises: a64cf3783c8d
"""
from alembic import op
import sqlalchemy as sa

revision = "1617e68a20c4"
down_revision = "a64cf3783c8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: infrastructure alerts are about no account, and existing rows
    # predate the column.
    op.add_column("platform_alerts", sa.Column("subject_kind", sa.String(16), nullable=True))
    op.add_column("platform_alerts", sa.Column("subject_ref", sa.String(128), nullable=True))
    op.add_column("platform_alerts", sa.Column("subject_role", sa.String(32), nullable=True))
    # The open-alert dedup index now includes the subject.
    op.drop_index("ix_platform_alerts_open", table_name="platform_alerts")
    op.create_index(
        "ix_platform_alerts_open", "platform_alerts",
        ["alert_type", "company_id", "subject_ref"],
        unique=False, postgresql_where=sa.text("is_resolved = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_platform_alerts_open", table_name="platform_alerts")
    op.create_index(
        "ix_platform_alerts_open", "platform_alerts",
        ["alert_type", "company_id"],
        unique=False, postgresql_where=sa.text("is_resolved = false"),
    )
    op.drop_column("platform_alerts", "subject_role")
    op.drop_column("platform_alerts", "subject_ref")
    op.drop_column("platform_alerts", "subject_kind")
