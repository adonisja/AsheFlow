"""add package_removals — out-of-zone freight pulled at the station

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-07-03

ADR-176: out-of-company-zone totes/packages are flagged for REMOVAL (returned
to Amazon), never transferred between trucks; dispatch tracks what was pulled.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'a6b7c8d9e0f1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'package_removals',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('removal_date', sa.Date(), nullable=False, index=True),
        sa.Column('bag_id', sa.String(100), nullable=False),
        sa.Column('tba', sa.String(50), nullable=True),
        sa.Column('tba_numbers', JSONB(), nullable=True),
        sa.Column('package_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('whole_tote', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reason', sa.String(30), nullable=False, server_default='out_of_zone'),
        sa.Column('locator', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='flagged'),
        sa.Column('flagged_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('removed_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('removed_by_name', sa.String(100), nullable=True),
        sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('package_removals')
