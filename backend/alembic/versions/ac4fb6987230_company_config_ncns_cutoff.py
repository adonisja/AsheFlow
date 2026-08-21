"""company_config: ncns_cutoff_minutes

Revision ID: ac4fb6987230
Revises: 749e69a31f9b
Create Date: 2026-07-12

ADR-198: minutes past the attendance reference (max(shift_start, AP-established))
with no AP arrival before a crew member is NCNS. Nullable → code defaults to 60.
"""
from alembic import op
import sqlalchemy as sa

revision = "ac4fb6987230"
down_revision = "749e69a31f9b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company_configs", sa.Column("ncns_cutoff_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("company_configs", "ncns_cutoff_minutes")
