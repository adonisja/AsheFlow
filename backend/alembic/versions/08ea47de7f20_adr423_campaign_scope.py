"""ADR-423: open vs company campaign scope

`company_id` becomes nullable on the three collection tables — NULL means an
open, platform-owned campaign with no tenant — and `collection_tokens` gains
`scope`.

Revision ID: 08ea47de7f20
Revises: c8fee0459a8a
"""
from alembic import op
import sqlalchemy as sa

revision = "08ea47de7f20"
down_revision = "c8fee0459a8a"
branch_labels = None
depends_on = None

_TABLES = (
    "collection_tokens",
    "collected_address_profiles",
    "collected_walker_days",
)


def upgrade() -> None:
    for t in _TABLES:
        op.alter_column(t, "company_id", existing_type=sa.dialects.postgresql.UUID(),
                        nullable=True)

    op.add_column(
        "collection_tokens",
        sa.Column("scope", sa.String(length=10), nullable=False,
                  server_default="open"),
    )
    op.create_index("ix_collection_tokens_scope", "collection_tokens", ["scope"])

    # Every existing campaign was created by a company admin through the old
    # endpoint, which set company_id from the caller's employee record. They are
    # company-scoped by construction, so say so rather than letting the "open"
    # server_default silently widen them.
    op.execute(sa.text(
        "UPDATE collection_tokens SET scope = 'company' WHERE company_id IS NOT NULL"
    ))


def downgrade() -> None:
    # Rows with a NULL company_id cannot be made NOT NULL again without
    # inventing a tenant for them, so they are deleted — they are open-campaign
    # data that has no meaning under the old model. Tokens cascade to their
    # collected rows.
    op.execute(sa.text("DELETE FROM collection_tokens WHERE company_id IS NULL"))
    op.execute(sa.text("DELETE FROM collected_address_profiles WHERE company_id IS NULL"))
    op.execute(sa.text("DELETE FROM collected_walker_days WHERE company_id IS NULL"))

    op.drop_index("ix_collection_tokens_scope", table_name="collection_tokens")
    op.drop_column("collection_tokens", "scope")
    for t in _TABLES:
        op.alter_column(t, "company_id", existing_type=sa.dialects.postgresql.UUID(),
                        nullable=False)
