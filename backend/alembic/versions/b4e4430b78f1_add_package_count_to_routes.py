"""add_package_count_to_routes

Revision ID: b4e4430b78f1
Revises: j7e8f9a0b1c2
Create Date: 2026-06-03

The Route.package_count column was added to the ORM model but never had a
migration. Without it every INSERT to the routes table would fail with a
NOT NULL violation once the column is added here.

DEFAULT 0 handles any existing rows; application code always sets the value.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b4e4430b78f1'
down_revision = 'j7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'routes',
        sa.Column('package_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('routes', 'package_count', server_default=None)


def downgrade() -> None:
    op.drop_column('routes', 'package_count')
