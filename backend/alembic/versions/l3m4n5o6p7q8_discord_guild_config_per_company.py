"""company_configs: add per-company Discord guild configuration columns

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-05-08

Changes:
  - ADD company_configs.discord_guild_id         BIGINT NULL
  - ADD company_configs.discord_drivers_channel_id  BIGINT NULL
  - ADD company_configs.discord_trainers_channel_id BIGINT NULL
  - ADD company_configs.discord_general_channel_id  BIGINT NULL
  - ADD company_configs.discord_invite_channel_id   BIGINT NULL
  - ADD company_configs.discord_role_admin       BIGINT NULL
  - ADD company_configs.discord_role_manager     BIGINT NULL
  - ADD company_configs.discord_role_asheflow    BIGINT NULL
  - ADD company_configs.discord_role_bot         BIGINT NULL
  - ADD company_configs.discord_role_dispatch    BIGINT NULL
  - ADD company_configs.discord_role_driver      BIGINT NULL
  - ADD company_configs.discord_role_captain     BIGINT NULL
  - ADD company_configs.discord_role_walker      BIGINT NULL

All columns are nullable — Discord integration is optional per company.
After running this migration, backfill company1's values via the super admin UI
(Discord Config section) using the IDs currently in bot/.env.
"""

import sqlalchemy as sa
from alembic import op

revision = "l3m4n5o6p7q8"
down_revision = "k2l3m4n5o6p7"
branch_labels = None
depends_on = None

_TABLE = "company_configs"

_COLUMNS = [
    "discord_guild_id",
    "discord_drivers_channel_id",
    "discord_trainers_channel_id",
    "discord_general_channel_id",
    "discord_invite_channel_id",
    "discord_role_admin",
    "discord_role_manager",
    "discord_role_asheflow",
    "discord_role_bot",
    "discord_role_dispatch",
    "discord_role_driver",
    "discord_role_captain",
    "discord_role_walker",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column(_TABLE, sa.Column(col, sa.BigInteger(), nullable=True))


def downgrade() -> None:
    for col in reversed(_COLUMNS):
        op.drop_column(_TABLE, col)
