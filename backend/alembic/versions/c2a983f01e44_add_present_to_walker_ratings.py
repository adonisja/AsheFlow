"""add_present_to_walker_ratings

Revision ID: c2a983f01e44
Revises: f4e891bc2d10
Create Date: 2026-04-10 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2a983f01e44'
down_revision: Union[str, Sequence[str], None] = 'f4e891bc2d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add present column (default True so existing rows are treated as present)
    op.add_column('walker_ratings', sa.Column('present', sa.Boolean(), nullable=False, server_default='true'))
    # Make stars nullable to support no-show records
    op.alter_column('walker_ratings', 'stars', nullable=True)


def downgrade() -> None:
    op.alter_column('walker_ratings', 'stars', nullable=False)
    op.drop_column('walker_ratings', 'present')
