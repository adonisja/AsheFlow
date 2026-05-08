"""Drop stale training_records columns; ORM sync for company_id on 4 models

Revision ID: j1k2l3m4n5o6
Revises: i6f7g8h9i0j1
Create Date: 2026-05-08

Changes:
  - DROP training_records.trainee_comments  (removed from ORM, orphaned in DB)
  - DROP training_records.trainer_rating    (removed from ORM, orphaned in DB)

ORM-only sync (columns already exist in DB from Phase 1 migration h2b3c4d5e6f7,
ORM models were not updated at the time — no DDL needed):
  - fuel_mileage_logs.company_id
  - vehicle_inspections.company_id
  - training_tasks.company_id
  - station_handoffs.company_id
"""

from alembic import op

revision = "j1k2l3m4n5o6"
down_revision = "i6f7g8h9i0j1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("training_records", "trainee_comments")
    op.drop_column("training_records", "trainer_rating")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column("training_records", sa.Column("trainee_comments", sa.Text(), nullable=True))
    op.add_column("training_records", sa.Column("trainer_rating", sa.Integer(), nullable=True))
