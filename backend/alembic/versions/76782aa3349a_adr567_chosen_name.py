"""ADR-567: a person's chosen name, shown in place of their legal name.

Revision ID: 76782aa3349a
Revises: 739ef516a381
"""
import sqlalchemy as sa
from alembic import op

revision = "76782aa3349a"
down_revision = "739ef516a381"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("chosen_name", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "chosen_name")
