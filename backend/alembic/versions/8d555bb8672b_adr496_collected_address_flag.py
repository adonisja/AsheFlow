"""ADR-496 D3: a collected address that has lost its street is flagged.

Revision ID: 8d555bb8672b
Revises: ce813b26a11a
"""
from alembic import op
import sqlalchemy as sa

revision = "8d555bb8672b"
down_revision = "ce813b26a11a"
branch_labels = None
depends_on = None


def upgrade():
    # "street_lost" | "no_street" | NULL. Existing rows stay NULL: the flag
    # records what the check said at submit, and these predate it. Promotion
    # recomputes from the address, so old rows are still caught there.
    op.add_column("collected_address_profiles",
                  sa.Column("address_flag", sa.String(20), nullable=True))
    op.create_index("ix_collected_address_profiles_address_flag",
                    "collected_address_profiles", ["address_flag"])


def downgrade():
    op.drop_index("ix_collected_address_profiles_address_flag",
                  table_name="collected_address_profiles")
    op.drop_column("collected_address_profiles", "address_flag")
