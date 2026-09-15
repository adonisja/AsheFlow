"""btr_bags.sort_zone — the sheet's per-bag station location (ADR-405)

Revision ID: e52a0400d48b
Revises: 18239df658d8
Create Date: 2026-09-09

Additive and nullable. The verified export carries a zone for all 339 bags
across six trucks, but a sheet is an external file: a column that disappears
must degrade to null rather than fail an import.
"""
from alembic import op
import sqlalchemy as sa

revision = "e52a0400d48b"
down_revision = "18239df658d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("btr_bags", sa.Column("sort_zone", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("btr_bags", "sort_zone")
