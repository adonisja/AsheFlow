"""ADR-335: platform alerts for super admins

Revision ID: ff1deea176cf
Revises: d2f99487115b
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "ff1deea176cf"
down_revision = "d2f99487115b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_type", sa.String(64), nullable=False),
        # Nullable by design (ADR-335 D1) — a platform-wide incident has no
        # owning tenant. Mirrors audit_log.company_id.
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # NOT a ForeignKey — a super admin has no Employee row (ADR-274 D13).
        sa.Column("resolved_by_sub", sa.String(128), nullable=True),
        sa.Column("resolved_by_email", sa.String(320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_platform_alerts_alert_type", "platform_alerts", ["alert_type"])
    op.create_index("ix_platform_alerts_company_id", "platform_alerts", ["company_id"])
    op.create_index("ix_platform_alerts_is_resolved", "platform_alerts", ["is_resolved"])
    # The dedup lookup: open alerts by type and tenant.
    op.create_index(
        "ix_platform_alerts_open", "platform_alerts", ["alert_type", "company_id"],
        postgresql_where=sa.text("is_resolved = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_platform_alerts_open", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_is_resolved", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_company_id", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_alert_type", table_name="platform_alerts")
    op.drop_table("platform_alerts")
