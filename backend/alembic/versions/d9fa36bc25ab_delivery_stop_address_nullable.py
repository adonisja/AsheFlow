"""delivery_stops.normalised_address nullable (ADR-219)

Revision ID: d9fa36bc25ab
Revises: 81489afd11c9
Create Date: 2026-07-21

ADR-219: the 48h nulling job nulls the customer delivery address on delivery
rows. DeliveryStop.normalised_address was NOT NULL — make it nullable so it can
be scrubbed while the row survives (block_key + counts). The
(route_id, normalised_address) unique constraint tolerates NULLs (Postgres
treats NULLs as distinct).
"""
from alembic import op
import sqlalchemy as sa

revision = "d9fa36bc25ab"
down_revision = "81489afd11c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("delivery_stops", "normalised_address",
                    existing_type=sa.String(length=200), nullable=True)


def downgrade() -> None:
    # Backfill NULLs before restoring NOT NULL (scrubbed rows can't go back).
    op.execute("UPDATE delivery_stops SET normalised_address = '' WHERE normalised_address IS NULL")
    op.alter_column("delivery_stops", "normalised_address",
                    existing_type=sa.String(length=200), nullable=False)
