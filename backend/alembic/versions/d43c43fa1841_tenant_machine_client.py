"""Per-tenant machine client id, and a unique guild (ADR-364)

Revision ID: d43c43fa1841
Revises: 252369465133
Create Date: 2026-09-03
"""
import sqlalchemy as sa
from alembic import op

revision = "d43c43fa1841"
down_revision = "252369465133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The Cognito app client this tenant's bot authenticates as. Nullable: every
    # existing company predates this, and a company without a bot never needs
    # one. The SECRET is deliberately not stored -- Cognito can return it via
    # DescribeUserPoolClient, so there is no reason to hold a live credential.
    op.add_column(
        "companies",
        sa.Column("machine_client_id", sa.String(length=128), nullable=True),
    )
    # One client serves exactly one tenant. Without this a client id could be
    # written against two companies and the tenant lookup would pick one
    # arbitrarily -- a cross-tenant read produced by a data-entry mistake.
    op.create_index(
        "uq_companies_machine_client_id",
        "companies",
        ["machine_client_id"],
        unique=True,
        postgresql_where=sa.text("machine_client_id IS NOT NULL"),
    )

    # ADR-364 D1 -- unrelated to the machine client, found while evaluating the
    # guild-header option. Two companies could claim the same Discord guild and
    # the bot's reverse lookup would pick one arbitrarily.
    op.create_index(
        "uq_company_config_discord_guild_id",
        "company_configs",
        ["discord_guild_id"],
        unique=True,
        postgresql_where=sa.text("discord_guild_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_company_config_discord_guild_id", table_name="company_configs")
    op.drop_index("uq_companies_machine_client_id", table_name="companies")
    op.drop_column("companies", "machine_client_id")
