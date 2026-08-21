"""add routes.stops and misrouted_package_flags.normalised_address

Revision ID: 35b4ab02ff7d
Revises: 060827c275d1
Create Date: 2026-07-10

ADR-194: structured delivered-set stops on the Route row
([{block_key, address, tba_numbers}]) so route drill-downs group
block → address → TBAs without the Redis manifest, and the address on
misroute flags so the AP captain can physically locate the package and
the resolve endpoint can move the stop data with it.

Both columns are nullable — rows that predate this migration degrade to
the flat block_keys / normalised_addresses lists in every client.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '35b4ab02ff7d'
down_revision = '060827c275d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "routes",
        sa.Column("stops", JSONB(), nullable=True),
    )
    op.add_column(
        "misrouted_package_flags",
        sa.Column("normalised_address", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("misrouted_package_flags", "normalised_address")
    op.drop_column("routes", "stops")
