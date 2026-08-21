"""add trucks.is_hub — a hub is a kind of truck, not a status (ADR-274)

Replaces the ADR-125 inference, where a hub was any TruckAssignment left in
status='planned'. That matched EVERY truck before publish, so every card on the
dispatch page offered a "Publish Hub" button.

server_default="false" so every existing truck keeps its current behaviour: the
column is additive and no backfill is needed.

Revision ID: 0969fd813b6a
Revises: a9588c6d78bf
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa


revision = "0969fd813b6a"
down_revision = "a9588c6d78bf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trucks",
        sa.Column("is_hub", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Indexed because run_dispatch filters on it on every dispatch run, next to
    # the is_active filter that is already indexed.
    op.create_index("ix_trucks_is_hub", "trucks", ["is_hub"])


def downgrade() -> None:
    op.drop_index("ix_trucks_is_hub", table_name="trucks")
    op.drop_column("trucks", "is_hub")
