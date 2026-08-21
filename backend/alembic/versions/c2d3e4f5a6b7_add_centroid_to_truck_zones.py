"""add centroid_lat/lng to truck_zones

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-01

Stores the true package-mean centroid on TruckZone so warm-start K-Means
seeds use the actual center of mass of the cluster's packages rather than
the average of polygon vertices (which is skewed by alphashape edge density).
"""

from alembic import op
import sqlalchemy as sa

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('truck_zones', sa.Column('centroid_lat', sa.Float(), nullable=True))
    op.add_column('truck_zones', sa.Column('centroid_lng', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('truck_zones', 'centroid_lng')
    op.drop_column('truck_zones', 'centroid_lat')
