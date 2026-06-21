"""update_timecard_adjustments_write_failed_and_defaults

Revision ID: 079c7f2673cc
Revises: 9081104444eb
Create Date: 2026-06-20 10:02:47.809124

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '079c7f2673cc'
down_revision: Union[str, Sequence[str], None] = '9081104444eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_timecard_adjustment_status", "timecard_adjustments")
    op.create_check_constraint(
        "ck_timecard_adjustment_status",
        "timecard_adjustments",
        "status IN ('pending_employee', 'pending_manager', 'approved', 'applied', 'write_failed', 'rejected')",
    )
    op.add_column("timecard_adjustments", sa.Column("write_attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("timecard_adjustments", "is_post_close", server_default=None)

def downgrade() -> None:
    """Downgrade schema. """
    op.drop_constraint("ck_timecard_adjustment_status", "timecard_adjustments")
    op.create_check_constraint(
        "ck_timecard_adjustment_status",
        "timecard_adjustments",
        "status IN ('pending_employee', 'pending_manager', 'approved', 'applied', 'rejected')"
    )
    op.drop_column("timecard_adjustments", "write_attempt_count")
    op.alter_column("timecard_adjustments", "is_post_close", server_default=None)
