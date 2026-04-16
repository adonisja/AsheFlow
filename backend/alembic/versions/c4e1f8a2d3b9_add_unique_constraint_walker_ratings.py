"""add unique constraint walker_ratings

Revision ID: c4e1f8a2d3b9
Revises: b1d4e7f3a2c8
Create Date: 2026-04-12

"""
from typing import Union, Sequence

from alembic import op

revision: str = 'c4e1f8a2d3b9'
down_revision: Union[str, Sequence[str], None] = 'b1d4e7f3a2c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_walker_ratings_driver_walker_date",
        "walker_ratings",
        ["driver_id", "walker_id", "date"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_walker_ratings_driver_walker_date",
        "walker_ratings",
        type_="unique",
    )
