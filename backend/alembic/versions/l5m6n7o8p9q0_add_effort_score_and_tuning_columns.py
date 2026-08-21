"""add effort_score, coverage_pct to routes and effort tuning factors to company_config

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-24

Part of the BuildingProfile system weighted route scoring (see docs/BUILDING_PROFILE_DESIGN.md).

routes:
  effort_score   Float nullable  — weighted normalized score snapshot at sort-commit time
  coverage_pct   Float nullable  — profiled_package_count / total_package_count at sort time

company_config:
  effort_time_factor     Float nullable  — T constant in scoring formula (default 0.5)
  effort_physical_factor Float nullable  — P constant in scoring formula (default 0.5)

All new columns are nullable so existing rows are unaffected.
"""
from alembic import op
import sqlalchemy as sa

revision = 'l5m6n7o8p9q0'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("routes", sa.Column("effort_score", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("coverage_pct", sa.Float(), nullable=True))

    op.add_column("company_configs", sa.Column("effort_time_factor",     sa.Float(), nullable=True))
    op.add_column("company_configs", sa.Column("effort_physical_factor", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("routes", "effort_score")
    op.drop_column("routes", "coverage_pct")
    op.drop_column("company_configs", "effort_time_factor")
    op.drop_column("company_configs", "effort_physical_factor")
