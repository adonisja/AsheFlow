"""Mark a TruckAssignment dispatch created on its own (ADR-368)

Revision ID: 5600ba7f9958
Revises: d43c43fa1841
Create Date: 2026-09-03
"""
import sqlalchemy as sa
from alembic import op

revision = "5600ba7f9958"
down_revision = "d43c43fa1841"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Why the assignment carries this rather than the board deriving it:
    # "was this auto-created?" answered as "does a matching pin exist?" flips to
    # false the moment the pin is edited or deleted, rewriting history. ADR-274
    # named that trap -- correlations drift.
    #
    # Nullable with no backfill: null is correct for every existing row and for
    # every assignment a dispatcher makes by hand.
    op.add_column(
        "truck_assignments",
        sa.Column("auto_created_reason", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("truck_assignments", "auto_created_reason")
