"""alter_adp_timecard_segments_clock_times_nullable

Revision ID: abf19992d507
Revises: 079c7f2673cc
Create Date: 2026-06-21 18:21:46.431997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abf19992d507'
down_revision: Union[str, Sequence[str], None] = '079c7f2673cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("adp_timecard_segments", "clock_in_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.alter_column("adp_timecard_segments", "clock_out_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column("adp_timecard_segments", "clock_in_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column("adp_timecard_segments", "clock_out_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
