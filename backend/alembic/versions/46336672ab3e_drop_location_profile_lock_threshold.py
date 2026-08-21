"""Drop vestigial location_profile_lock_threshold from company_configs

Revision ID: 46336672ab3e
Revises: z3a4b5c6d7e8
Create Date: 2026-06-24

location_profile_lock_threshold was added for LocationProfile promotion
thresholds. LocationProfile was dropped in ADR-135 (BuildingProfile replaced
it). The column has been NULL on all rows since then.

Fixed 2026-07-25: the table is `company_configs` (plural) — every other migration
uses that name; this one said `company_config`, which never matched anything. The
bug only surfaced on a from-base rebuild (an incremental upgrade past this point
never re-ran it). Also made the drop/add IF EXISTS-guarded: this revision branches
off z3a4b5c6d7e8, so depending on branch merge order the column may not be present
when it runs.
"""
from alembic import op
import sqlalchemy as sa


revision = '46336672ab3e'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE company_configs "
        "DROP COLUMN IF EXISTS location_profile_lock_threshold"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE company_configs "
        "ADD COLUMN IF NOT EXISTS location_profile_lock_threshold INTEGER"
    )
