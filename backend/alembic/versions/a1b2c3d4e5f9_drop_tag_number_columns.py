"""drop tag_number columns from routes and misrouted_package_flags

Revision ID: a1b2c3d4e5f9
Revises: z3a4b5c6d7e8
Create Date: 2026-06-24

tag_number (Amazon's warehouse staging locator, e.g. "A-12") is informational
at load time only. It was incorrectly persisted into both routes.tag_numbers
and misrouted_package_flags.tag_number. These columns are dropped here.

  routes.tag_numbers              — ARRAY(Text) column removed
  misrouted_package_flags.tag_number — VARCHAR(50) column removed
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a1b2c3d4e5f9'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('routes', 'tag_numbers')
    op.drop_column('misrouted_package_flags', 'tag_number')


def downgrade() -> None:
    op.add_column(
        'routes',
        sa.Column('tag_numbers', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
    )
    op.add_column(
        'misrouted_package_flags',
        sa.Column('tag_number', sa.String(50), nullable=True),
    )
