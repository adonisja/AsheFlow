"""ADR-493 D3 — PI erasure ledger

Revision ID: 4b26674f3cba
Revises: 45397407cee1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "4b26674f3cba"
down_revision = "45397407cee1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pi_erasure_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("value_hash", sa.String(64), nullable=False),
        sa.Column("erased_by", sa.String(64), nullable=True),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('address', 'tba')", name="ck_pi_erasure_ledger_kind"),
    )
    op.create_index("ix_pi_erasure_ledger_value_hash", "pi_erasure_ledger", ["value_hash"])
    op.create_index("ix_pi_erasure_ledger_company_erased_at", "pi_erasure_ledger", ["company_id", "erased_at"])


def downgrade() -> None:
    op.drop_index("ix_pi_erasure_ledger_company_erased_at", table_name="pi_erasure_ledger")
    op.drop_index("ix_pi_erasure_ledger_value_hash", table_name="pi_erasure_ledger")
    op.drop_table("pi_erasure_ledger")
