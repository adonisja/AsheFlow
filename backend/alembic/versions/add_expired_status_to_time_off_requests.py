"""Add 'expired' status to time_off_requests

Revision ID: add_expired_tor
Revises: f996344de217
Create Date: 2026-04-09
"""

revision = 'add_expired_tor'
down_revision = 'cec73d660c0a'
branch_labels = None
depends_on = None
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.execute("UPDATE time_off_requests SET status='expired' WHERE status='pending' AND date <= CURRENT_DATE")
    op.drop_constraint('valid_time_off_status', 'time_off_requests', type_='check')
    op.create_check_constraint('valid_time_off_status', 'time_off_requests', "status IN ('pending', 'approved', 'rejected', 'expired')")


def downgrade() -> None:
    op.execute("UPDATE time_off_requests SET status='pending' WHERE status='expired'")
    op.drop_constraint('valid_time_off_status', 'time_off_requests', type_='check')
    op.create_check_constraint('valid_time_off_status', 'time_off_requests', "status IN ('pending', 'approved', 'rejected')")
