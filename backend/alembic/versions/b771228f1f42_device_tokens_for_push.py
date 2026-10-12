"""device_tokens — where a push notification is delivered (ADR-487 D5)

Revision ID: b771228f1f42
Revises: 045d62ef7d08
Create Date: 2026-10-11

25 of the 86 declared notification types carry the PUSH channel and nothing
delivered any of them (ADR-487 Finding 2). This is the delivery address.

TWO INDEXES THAT ARE NOT DECORATION
-----------------------------------
`uq_device_tokens_token` is GLOBAL, not per-employee. A phone handed from one
walker to another re-registers the same token against a new employee, and
without this constraint the old row keeps delivering the first person's
notifications to the second. The uniqueness is what lets registration MOVE the
row instead of inserting a duplicate.

`ix_device_tokens_live` is PARTIAL (`WHERE revoked_at IS NULL`). The send path
only ever wants live rows for one employee; without it every fan-out scans
revoked devices too, and revoked rows are kept forever by design (a sign-out
must stay distinguishable from a token that never existed).

NO BACKFILL
-----------
There is nothing to backfill: no device has ever registered, because there was
no endpoint to register with. The table starts empty in every environment.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "b771228f1f42"
down_revision = "045d62ef7d08"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("endpoint_arn", sa.String(256), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("platform IN ('ios', 'android')",
                           name="ck_device_token_platform"),
    )
    op.create_index("ix_device_tokens_company_id", "device_tokens", ["company_id"])
    op.create_index("ix_device_tokens_employee_id", "device_tokens", ["employee_id"])
    op.create_index("uq_device_tokens_token", "device_tokens", ["token"], unique=True)
    op.create_index(
        "ix_device_tokens_live", "device_tokens", ["company_id", "employee_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade():
    # Dropping this loses every registration, so every device must re-register
    # on next sign-in. That is recoverable (the app re-registers on launch) and
    # is why there is no data-preservation step here.
    op.drop_index("ix_device_tokens_live", table_name="device_tokens")
    op.drop_index("uq_device_tokens_token", table_name="device_tokens")
    op.drop_index("ix_device_tokens_employee_id", table_name="device_tokens")
    op.drop_index("ix_device_tokens_company_id", table_name="device_tokens")
    op.drop_table("device_tokens")
