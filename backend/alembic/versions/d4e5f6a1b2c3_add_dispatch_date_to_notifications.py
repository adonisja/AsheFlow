"""add_dispatch_date_to_notifications

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-04-23 03:00:00.000000

Adds dispatch_date (Date, nullable) to notifications.
Used by dispatch_assignment notifications so the frontend knows
which date to POST the confirmation against.
All other notification types leave this column NULL.
"""

from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a1b2c3'
down_revision = 'c3d4e5f6a1b2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'notifications',
        sa.Column('dispatch_date', sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column('notifications', 'dispatch_date')
