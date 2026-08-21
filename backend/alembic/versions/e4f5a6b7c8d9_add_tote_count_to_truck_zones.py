"""add tote_count to truck_zones

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-01

ADR-169 measures zone equity in totes per truck. Persisting the distinct tote
count per zone lets the dispatch map legend show the equity proof without
re-deriving bag membership from the (expiring) Redis manifest.
"""

from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('truck_zones', sa.Column('tote_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('truck_zones', 'tote_count')
