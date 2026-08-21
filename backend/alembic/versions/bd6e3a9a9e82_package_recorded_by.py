"""separate 'who recorded' from 'whose route' on package exceptions

Revision ID: bd6e3a9a9e82
Revises: 732d8bc120eb
Create Date: 2026-07-31

ADR-244. rts_packages.walker_id and missing_packages.walker_id were stamped as
caller.id, conflating the walker whose route it was with whoever submitted the
row. Elevated roles may submit on a walker's behalf, so those rows recorded the
submitter and lost the walker.

walker_id KEEPS its meaning (the route's executor) and recorded_by is added
alongside. Renaming would break every existing read.

Backfill: recorded_by = walker_id. That is correct for self-submitted rows and
wrong for rows an elevated role submitted — the distinction cannot be recovered
retroactively, and leaving it null would lose the common case too (ADR-244
Consequences).

damaged_packages is deliberately UNCHANGED: damage is usually found at station
sort before a route exists, so there is no executor to attribute. reported_by
already captures the accountable actor.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "bd6e3a9a9e82"
down_revision = "732d8bc120eb"
branch_labels = None
depends_on = None

_TABLES = ("rts_packages", "missing_packages")


def upgrade():
    for t in _TABLES:
        op.add_column(t, sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=True))
        op.add_column(t, sa.Column("recorded_by_name", sa.String(100), nullable=True))
        op.create_foreign_key(
            f"fk_{t}_recorded_by", t, "employees", ["recorded_by"], ["id"],
            ondelete="SET NULL",
        )
        # Nullable, so no NOT NULL step: rows predating this cannot be
        # distinguished, and a null recorded_by is an honest "unknown".
        op.execute(f"UPDATE {t} SET recorded_by = walker_id, recorded_by_name = walker_name")


def downgrade():
    for t in _TABLES:
        op.drop_constraint(f"fk_{t}_recorded_by", t, type_="foreignkey")
        op.drop_column(t, "recorded_by_name")
        op.drop_column(t, "recorded_by")
