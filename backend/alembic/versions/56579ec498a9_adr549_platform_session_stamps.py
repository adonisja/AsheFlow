"""ADR-549 D3: a session stamp for platform accounts (no Employee row).

Revision ID: 56579ec498a9
Revises: d88d57de02a5
"""
import sqlalchemy as sa
from alembic import op

revision = "56579ec498a9"
down_revision = "d88d57de02a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_session_stamps",
        sa.Column("cognito_sub", sa.String(64), primary_key=True),
        sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("platform_session_stamps")
