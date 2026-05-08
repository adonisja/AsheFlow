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

def upgrade():
    op.add_column(
        'trucks',
        sa.Column('discord_channel_id', sa.BigInteger(), nullable=True),
    )
    # Channel IDs are server-specific — set via admin UI or seed script, not hardcoded here.


def downgrade():
    op.drop_column('trucks', 'discord_channel_id')
