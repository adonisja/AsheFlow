"""add_discord_channel_id_to_trucks

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-04-22 02:00:00.000000

Adds discord_channel_id (BigInteger, nullable) to trucks.
Seeded immediately with the known channel IDs for the AsheFlow Test Server.
"""

from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a1b2'
down_revision = 'b2c3d4e5f6a1'
branch_labels = None
depends_on = None

# Truck name → Discord channel snowflake (AsheFlow Test Server)
TRUCK_CHANNEL_MAP = {
    "Atlas":  TRUCK_CHANNEL_REDACTED,
    "Eagle":  TRUCK_CHANNEL_REDACTED,
    "Falcon": TRUCK_CHANNEL_REDACTED,
    "Gemini": TRUCK_CHANNEL_REDACTED,
    "Jackal": TRUCK_CHANNEL_REDACTED,
    "Morgan": TRUCK_CHANNEL_REDACTED,
    "Omega":  TRUCK_CHANNEL_REDACTED,
}


def upgrade():
    op.add_column(
        'trucks',
        sa.Column('discord_channel_id', sa.BigInteger(), nullable=True),
    )

    # Seed channel IDs for existing trucks
    conn = op.get_bind()
    for name, channel_id in TRUCK_CHANNEL_MAP.items():
        conn.execute(
            sa.text("UPDATE trucks SET discord_channel_id = :cid WHERE name = :name"),
            {"cid": channel_id, "name": name},
        )


def downgrade():
    op.drop_column('trucks', 'discord_channel_id')
