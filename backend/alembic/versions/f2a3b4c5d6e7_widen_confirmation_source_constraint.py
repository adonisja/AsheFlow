"""Widen dispatch_confirmation source check constraint.

Adds 'app' (in-app button) and 'dispatch_override' (privileged user acting for
someone else) to the allowed source values.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-04-22
"""

from alembic import op
from sqlalchemy import text

revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "ALTER TABLE dispatch_confirmations "
        "DROP CONSTRAINT IF EXISTS ck_dispatch_confirmations_source"
    ))
    conn.execute(text(
        "ALTER TABLE dispatch_confirmations ADD CONSTRAINT ck_dispatch_confirmations_source "
        "CHECK (source IN ('discord_bot', 'manual', 'app', 'dispatch_override'))"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "ALTER TABLE dispatch_confirmations "
        "DROP CONSTRAINT IF EXISTS ck_dispatch_confirmations_source"
    ))
    conn.execute(text(
        "ALTER TABLE dispatch_confirmations ADD CONSTRAINT ck_dispatch_confirmations_source "
        "CHECK (source IN ('discord_bot', 'manual'))"
    ))
