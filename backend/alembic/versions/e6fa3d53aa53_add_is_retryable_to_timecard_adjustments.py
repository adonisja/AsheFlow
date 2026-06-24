"""add_is_retryable_to_timecard_adjustments

Revision ID: e6fa3d53aa53
Revises: abf19992d507
Create Date: 2026-06-23 04:05:25.843702

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e6fa3d53aa53'
down_revision: Union[str, Sequence[str], None] = 'abf19992d507'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('timecard_adjustments', sa.Column('is_retryable', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('timecard_adjustments', 'is_retryable')
