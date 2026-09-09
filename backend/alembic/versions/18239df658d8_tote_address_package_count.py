"""tote_addresses.package_count — a drop's weight votes (ADR-403 D1a)

Revision ID: 18239df658d8
Revises: b1a4c956bae4
Create Date: 2026-09-09

Additive and non-null with a server default of 1, so every existing row reads as
one package — which is what it was. No backfill, no constraint change.
"""
from alembic import op
import sqlalchemy as sa

revision = "18239df658d8"
down_revision = "b1a4c956bae4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tote_addresses",
        sa.Column("package_count", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("tote_addresses", "package_count")
