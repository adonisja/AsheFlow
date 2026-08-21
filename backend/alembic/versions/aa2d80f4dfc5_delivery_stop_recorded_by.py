"""separate 'whose stop' from 'who completed it' on delivery_stops

Revision ID: aa2d80f4dfc5
Revises: bd6e3a9a9e82
Create Date: 2026-08-01

ADR-244 amendment. delivery_stops.walker_id was stamped caller.id in both
complete_delivery_stop and start_delivery_stop, behind a gate that authorises
against route.executor_id and admits any elevated role. So a trainer completing
a trainee's stop, or a walker covering for another during an emergency, was
recorded as the walker who owns the stop.

That skews three consumers that read walker_id as "who did the deliveries":
get_my_performance (mobile, ADR-203), cross_check_scorecard (our_delivered — the
figure we appeal Amazon with), and the management top-walker rankings.

walker_id KEEPS its meaning (the route's executor, which is what all three
consumers want) and recorded_by is added for the completer.

Backfill: recorded_by = walker_id. Correct for self-completed stops and wrong
for delegated ones; the distinction is unrecoverable, and nullable leaves
"unknown" expressible for rows written before this.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "aa2d80f4dfc5"
down_revision = "bd6e3a9a9e82"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("delivery_stops", sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("delivery_stops", sa.Column("recorded_by_name", sa.String(100), nullable=True))
    op.create_foreign_key(
        "fk_delivery_stops_recorded_by", "delivery_stops", "employees",
        ["recorded_by"], ["id"], ondelete="SET NULL",
    )
    op.execute("UPDATE delivery_stops SET recorded_by = walker_id, recorded_by_name = walker_name")


def downgrade():
    op.drop_constraint("fk_delivery_stops_recorded_by", "delivery_stops", type_="foreignkey")
    op.drop_column("delivery_stops", "recorded_by_name")
    op.drop_column("delivery_stops", "recorded_by")
