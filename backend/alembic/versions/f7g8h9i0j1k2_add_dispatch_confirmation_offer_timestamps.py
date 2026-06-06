"""add offer_sent_at and offer_expires_at to dispatch_confirmations

Revision ID: f7g8h9i0j1k2
Revises: e6f7a8b9c0d1
Create Date: 2026-06-06

LA-2: Labor-law compliance timestamps for dispatch offer lifecycle.
Records when an offer was extended (offer_sent_at) and when it lapses
(offer_expires_at) so advance-notice obligations can be audited.
"""
from alembic import op
import sqlalchemy as sa

revision = "f7g8h9i0j1k2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dispatch_confirmations",
        sa.Column("offer_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dispatch_confirmations",
        sa.Column("offer_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dispatch_confirmations", "offer_expires_at")
    op.drop_column("dispatch_confirmations", "offer_sent_at")
