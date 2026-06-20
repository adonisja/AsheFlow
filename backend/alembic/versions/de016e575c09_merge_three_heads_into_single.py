"""merge_three_heads_into_single

Revision ID: de016e575c09
Revises: a0b1c2d3e4f5, b4e4430b78f1, g8h9i0j1k2l3
Create Date: 2026-06-19 19:57:32.008428

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de016e575c09'
down_revision: Union[str, Sequence[str], None] = ('a0b1c2d3e4f5', 'b4e4430b78f1', 'g8h9i0j1k2l3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
