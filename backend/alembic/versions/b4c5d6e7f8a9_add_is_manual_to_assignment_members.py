"""Add is_manual column to assignment_members.

Tracks whether a crew member was placed by the dispatch algorithm (False)
or manually added by a dispatch coordinator after the run (True).
Used by the fill-rate analytics endpoint.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op

revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'assignment_members',
        sa.Column('is_manual', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('assignment_members', 'is_manual')
