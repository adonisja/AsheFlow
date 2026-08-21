"""add truck anchor display address field

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    # Add display address column (stores raw user input; initial_anchor_address now holds
    # the GeoClient-normalised canonical form).
    op.add_column(
        'trucks',
        sa.Column('initial_anchor_display_address', sa.String(300), nullable=True),
    )
    # Back-fill: existing rows have raw input in initial_anchor_address; treat it as
    # the display address until dispatch re-saves the anchor (which will then normalise).
    op.execute(
        "UPDATE trucks SET initial_anchor_display_address = initial_anchor_address "
        "WHERE initial_anchor_address IS NOT NULL"
    )


def downgrade():
    op.drop_column('trucks', 'initial_anchor_display_address')
