"""add tier1 and location_profile config fields to company_configs

Revision ID: t7u8v9w0x1y2
Revises: s6t7u8v9w0x1
Create Date: 2026-05-26

These fields were defined in the CompanyConfig ORM model (migration r5s6t7u8v9w0)
but were never added to the database schema.  This migration closes that gap.
"""

from alembic import op
import sqlalchemy as sa


revision = 't7u8v9w0x1y2'
down_revision = 's6t7u8v9w0x1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('company_configs', sa.Column('tier1_dbscan_eps',           sa.Float(),   nullable=True))
    op.add_column('company_configs', sa.Column('tier1_dbscan_min_samples',   sa.Integer(), nullable=True))
    op.add_column('company_configs', sa.Column('tier1_small_tote_cutoff',    sa.Integer(), nullable=True))
    op.add_column('company_configs', sa.Column('tier1_small_stray_max',      sa.Integer(), nullable=True))
    op.add_column('company_configs', sa.Column('tier1_small_uncertain_max',  sa.Integer(), nullable=True))
    op.add_column('company_configs', sa.Column('tier1_stray_pct',            sa.Float(),   nullable=True))
    op.add_column('company_configs', sa.Column('tier1_uncertain_pct',        sa.Float(),   nullable=True))
    op.add_column('company_configs', sa.Column('location_profile_lock_threshold', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('company_configs', 'location_profile_lock_threshold')
    op.drop_column('company_configs', 'tier1_uncertain_pct')
    op.drop_column('company_configs', 'tier1_stray_pct')
    op.drop_column('company_configs', 'tier1_small_uncertain_max')
    op.drop_column('company_configs', 'tier1_small_stray_max')
    op.drop_column('company_configs', 'tier1_small_tote_cutoff')
    op.drop_column('company_configs', 'tier1_dbscan_min_samples')
    op.drop_column('company_configs', 'tier1_dbscan_eps')
