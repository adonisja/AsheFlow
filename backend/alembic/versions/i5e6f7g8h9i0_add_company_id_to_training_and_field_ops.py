"""Add company_id to TrainingRecord, Departure, WalkerRating (ORM sync)

Revision ID: i5e6f7g8h9i0
Revises: h4d5e6f7g8h9
Create Date: 2026-05-08

The broad Phase 1 migration (h2b3c4d5e6f7) already added company_id to all 32
tables including training_records, departures, and walker_ratings. The ORM models
were not updated at the time. This revision stamps the chain so the merge migration
can reference it; no DDL changes needed.
"""

from alembic import op

revision = "i5e6f7g8h9i0"
down_revision = "h4d5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
