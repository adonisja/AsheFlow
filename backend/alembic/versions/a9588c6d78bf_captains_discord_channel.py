"""ADR-256: a captains Discord channel

Crew embeds post to `discord_trainers_channel_id` on COMPANY_CONFIGS (the
discord_* columns live there, not on `companies`). Captains had no equivalent room,
so the truck's route lead had nowhere to receive or discuss the day's crew.

Nullable and left NULL — a channel id cannot be invented, and every consumer already
guards on the id being present (`if trainers_channel:`), so an unset value means the
post is skipped rather than sent somewhere wrong.

Revision ID: a9588c6d78bf
Revises: ff90779895f6
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa

revision = "a9588c6d78bf"
down_revision = "ff90779895f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_configs",
        sa.Column("discord_captains_channel_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("company_configs", "discord_captains_channel_id")