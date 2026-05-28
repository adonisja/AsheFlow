"""add ingestion_mode to company_configs

Revision ID: w0x1y2z3a4b5
Revises: v9w0x1y2z3a4
Create Date: 2026-05-27

Adds ingestion_mode VARCHAR(10) to company_configs.
Values: "file" (dispatch uploads CSV/XLSX) | "api" (Amazon API feed).
Defaults to "file" for all existing rows.
"""

from alembic import op
import sqlalchemy as sa


revision = 'w0x1y2z3a4b5'
down_revision = 'v9w0x1y2z3a4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('company_configs',
        sa.Column('ingestion_mode', sa.String(10), nullable=True)
    )
    op.execute("UPDATE company_configs SET ingestion_mode = 'file' WHERE ingestion_mode IS NULL")


def downgrade():
    op.drop_column('company_configs', 'ingestion_mode')
