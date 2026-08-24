"""ADR-295 — crew_embed_message_id on truck_assignments

Lets a crew change EDIT the truck channel's posted crew embed instead of
leaving a stale roster standing (ADR-288 D5 posted a correction beside it).

Written against 2347526ecd7d (the last COMMITTED revision) rather than the
then-current head a35e323d69f5, because that head is the ADR-289 migration —
staged but not committed, so chaining onto it would break this migration if
that one were revised or dropped.

ADR-289 has since re-parented itself onto this revision, so the chain is
a35e323d69f5 -> b778b371da7f -> 2347526ecd7d with a single head. No merge
migration is needed. If ADR-289 is ever dropped, this revision stands on its
own committed parent.

Revision ID: b778b371da7f
Revises: 2347526ecd7d
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "b778b371da7f"
down_revision = "2347526ecd7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no default and no backfill: every existing truck-day
    # legitimately has no recorded embed, and NULL is the value the edit path
    # reads as "nothing to edit, post fresh".
    op.add_column(
        "truck_assignments",
        sa.Column("crew_embed_message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("truck_assignments", "crew_embed_message_id")
