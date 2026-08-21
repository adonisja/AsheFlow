"""drop tier1_dbscan_eps / tier1_dbscan_min_samples from company_configs

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-01

ADR-169 retired DBSCAN/K-Means from the station sort — totes are now assigned
directly to truck anchor points (assign_totes.py). These two tuning columns are
consumed by nothing; the remaining tier1_* columns (classification thresholds)
are still used by tier1_verify and stay.
"""

from alembic import op
import sqlalchemy as sa

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('company_configs', 'tier1_dbscan_eps')
    op.drop_column('company_configs', 'tier1_dbscan_min_samples')


def downgrade() -> None:
    op.add_column('company_configs', sa.Column('tier1_dbscan_eps', sa.Float(), nullable=True))
    op.add_column('company_configs', sa.Column('tier1_dbscan_min_samples', sa.Integer(), nullable=True))
