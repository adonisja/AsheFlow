"""company_config: add is_configured, drop min crew columns

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-05-08

Changes:
  - DROP company_configs.min_trainers_per_truck  (removed from ORM, no longer used)
  - DROP company_configs.min_walkers_per_truck   (removed from ORM, no longer used)
  - ADD  company_configs.is_configured BOOLEAN NOT NULL DEFAULT false
  - Backfill seed company (a0000000-...-0001) to is_configured=true
    (company1 is live and already fully configured)
"""

import sqlalchemy as sa
from alembic import op

revision = "k2l3m4n5o6p7"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None

SEED_COMPANY_ID = "a0000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.drop_column("company_configs", "min_trainers_per_truck")
    op.drop_column("company_configs", "min_walkers_per_truck")

    op.add_column(
        "company_configs",
        sa.Column("is_configured", sa.Boolean(), nullable=False, server_default="false"),
    )

    # company1 is live — mark it configured so existing sessions are unaffected.
    op.execute(
        f"UPDATE company_configs SET is_configured = true "
        f"WHERE company_id = '{SEED_COMPANY_ID}'"
    )


def downgrade() -> None:
    op.drop_column("company_configs", "is_configured")
    op.add_column("company_configs", sa.Column("min_trainers_per_truck", sa.Integer(), nullable=True))
    op.add_column("company_configs", sa.Column("min_walkers_per_truck",  sa.Integer(), nullable=True))
