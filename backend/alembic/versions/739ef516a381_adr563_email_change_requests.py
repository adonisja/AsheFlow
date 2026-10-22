"""ADR-563: admin-started email changes, confirmed by the new inbox.

Revision ID: 739ef516a381
Revises: 5486f5848f58
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "739ef516a381"
down_revision = "5486f5848f58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cognito_sub", sa.String(64), nullable=False),
        sa.Column("cognito_username", sa.String(128), nullable=False),
        sa.Column("account_kind", sa.String(16), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("new_email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_by_kind", sa.String(16), nullable=False),
        sa.Column("requested_by_ref", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("account_kind IN ('employee', 'surveyor', 'staff')", name="ck_email_change_kind"),
        sa.CheckConstraint("requested_by_kind IN ('tenant_admin', 'super_admin')", name="ck_email_change_requester"),
        sa.CheckConstraint("status IN ('pending', 'applied', 'cancelled', 'expired')", name="ck_email_change_status"),
        sa.UniqueConstraint("token_hash", name="uq_email_change_requests_token_hash"),
    )
    op.create_index("ix_email_change_requests_cognito_sub", "email_change_requests", ["cognito_sub"])
    op.create_index("ix_email_change_requests_company_id", "email_change_requests", ["company_id"])
    op.create_index("uq_email_change_pending", "email_change_requests", ["cognito_sub"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index("uq_email_change_pending", table_name="email_change_requests")
    op.drop_index("ix_email_change_requests_company_id", table_name="email_change_requests")
    op.drop_index("ix_email_change_requests_cognito_sub", table_name="email_change_requests")
    op.drop_table("email_change_requests")
