"""ADR-551: a locked-out person's request for a two-factor reset.

Revision ID: 946148bf49cc
Revises: 56579ec498a9
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "946148bf49cc"
down_revision = "56579ec498a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_reset_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cognito_sub", sa.String(64), nullable=False),
        sa.Column("account_kind", sa.String(16), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contributor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_ip", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_kind", sa.String(32), nullable=True),
        sa.Column("resolved_by_ref", sa.String(64), nullable=True),
        sa.CheckConstraint("account_kind IN ('employee', 'surveyor', 'staff')", name="ck_mfa_reset_request_kind"),
        sa.CheckConstraint("status IN ('pending', 'resolved')", name="ck_mfa_reset_request_status"),
    )
    op.create_index("ix_mfa_reset_requests_cognito_sub", "mfa_reset_requests", ["cognito_sub"])
    op.create_index("ix_mfa_reset_requests_company_id", "mfa_reset_requests", ["company_id"])
    op.create_index("uq_mfa_reset_request_pending", "mfa_reset_requests", ["cognito_sub"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index("uq_mfa_reset_request_pending", table_name="mfa_reset_requests")
    op.drop_index("ix_mfa_reset_requests_company_id", table_name="mfa_reset_requests")
    op.drop_index("ix_mfa_reset_requests_cognito_sub", table_name="mfa_reset_requests")
    op.drop_table("mfa_reset_requests")
