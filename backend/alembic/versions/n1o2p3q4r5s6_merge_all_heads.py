"""merge all heads before shift_sessions

Revision ID: n1o2p3q4r5s6
Revises: i5e6f7g8h9i0, b4c5d6e7f8a9, add_expired_tor, d4e5f6a1b2c3, m4n5o6p7q8r9, a1b2c3d4e5f7
Create Date: 2026-05-15

"""
from alembic import op

revision = 'n1o2p3q4r5s6'
down_revision = ('i5e6f7g8h9i0', 'b4c5d6e7f8a9', 'add_expired_tor', 'd4e5f6a1b2c3', 'm4n5o6p7q8r9', 'a1b2c3d4e5f7')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
