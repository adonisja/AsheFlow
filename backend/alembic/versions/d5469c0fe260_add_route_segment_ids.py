"""add routes.segment_ids — persist LION topology the sort already computes

ADR-260. route_sort resolves segment_id per package and builds an adjacency
graph from it, then discarded it when constructing the route. Persisting it
gives intake a route-side anchor for proximity ranking, and closes the gap
ADR-238 left open (misroute detection had no per-route segment set).

Safe to store on the route, unlike normalised_addresses (nulled 48h post-route
by ADR-219): a LION segment id is public street topology — no house numbers,
no addresses, no TBAs. Nothing tenant-derived, so no PII retention clock.

Existing rows get '{}' and fall back to same-street block ranking until the
next sort rebuilds them. No backfill is possible: the source packages leave
Redis with the manifest's 24h TTL.

Revision ID: d5469c0fe260
Revises: 914274a26b5c
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d5469c0fe260"
down_revision = "914274a26b5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "routes",
        sa.Column(
            "segment_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("routes", "segment_ids")
