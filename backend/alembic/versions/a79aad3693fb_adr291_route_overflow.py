"""ADR-291 D7 — routes.overflow_half_slots

Revision ID: a79aad3693fb
Revises: c32c9930c584
Create Date: 2026-08-24

One additive column, NOT NULL with a server_default of 0.

Workforce mode lets a route exceed its capacity lock — the captain judging the
load by eye is the authority there, not a computed limit. The amount carried
above the lock is recorded so the overflow is VISIBLE: ADR-273's diagnosis is
that routes closing for unrecorded reasons are invisible in production, and a
silent overflow is that same failure under another name.

Defaulting to 0 rather than NULL is deliberate. Every existing route was built
under an enforced capacity lock and genuinely overflowed by nothing, so 0 is the
truth for those rows, not a placeholder. That also makes a non-zero value
unambiguous: it always means a deliberate workforce overflow.
"""
from alembic import op
import sqlalchemy as sa

revision = "a79aad3693fb"
down_revision = "c32c9930c584"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "routes",
        sa.Column("overflow_half_slots", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("routes", "overflow_half_slots")
