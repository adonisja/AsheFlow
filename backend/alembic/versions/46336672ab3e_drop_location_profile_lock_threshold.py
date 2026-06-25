"""Drop vestigial location_profile_lock_threshold from company_config

Revision ID: 46336672ab3e
Revises: z3a4b5c6d7e8
Create Date: 2026-06-24

location_profile_lock_threshold was added for LocationProfile promotion
thresholds. LocationProfile was dropped in ADR-135 (BuildingProfile replaced
it). The column has been NULL on all rows since then.
"""
from alembic import op
import sqlalchemy as sa


revision = '46336672ab3e'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('company_config', 'location_profile_lock_threshold')


def downgrade() -> None:
    op.add_column(
        'company_config',
        sa.Column('location_profile_lock_threshold', sa.Integer(), nullable=True),
    )
