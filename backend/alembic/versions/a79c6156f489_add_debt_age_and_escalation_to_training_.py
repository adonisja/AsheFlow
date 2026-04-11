"""add_debt_age_and_escalation_to_training_tasks

Revision ID: a79c6156f489
Revises: 8523668a4665
Create Date: 2026-04-10 11:29:00.669247

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a79c6156f489'
down_revision: Union[str, Sequence[str], None] = '8523668a4665'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('training_tasks', sa.Column('debt_age', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('training_tasks', sa.Column('is_escalated', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('training_tasks', 'is_escalated')
    op.drop_column('training_tasks', 'debt_age')
