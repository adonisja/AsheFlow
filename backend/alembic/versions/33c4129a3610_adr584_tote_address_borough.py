"""ADR-584 D9: tote_addresses.borough, so the door identity is stored, not its attributes.

Revision ID: 33c4129a3610
Revises: a5f522b5b53d
"""
from alembic import op
import sqlalchemy as sa

revision = "33c4129a3610"
down_revision = "a5f522b5b53d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tote_addresses", sa.Column("borough", sa.String(1), nullable=True))


def downgrade():
    op.drop_column("tote_addresses", "borough")
