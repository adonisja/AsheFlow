"""Backfill building profile operating-hours columns on fresh databases.

Revision ID: 914274a26b5c
Revises: aa2d80f4dfc5
Create Date: 2026-08-02

The hours columns are added by m6n7o8p9q0r1 (chain position 83), which runs
FOURTEEN revisions before b2c3d4e5f6a7 (position 97) creates the tables. That
migration is now guarded so a fresh database no longer dies there — but the
guard also means the columns were never added on that path, while existing
databases got them at position 83.

So this reconciles the two: add whatever is missing, at the head, where both
kinds of database pass through. On staging and prod every column is already
there and this is a no-op.

Found by diffing the migrated schema against the ORM models rather than by the
migration failing — it ran green in both cases. A passing migration is not the
same as a correct schema.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = '914274a26b5c'
down_revision = 'aa2d80f4dfc5'
branch_labels = None
depends_on = None

_HOURS = (
    ("opens_at",               lambda: sa.Column("opens_at",               sa.Time, nullable=True)),
    ("closes_at",              lambda: sa.Column("closes_at",              sa.Time, nullable=True)),
    ("break_start",            lambda: sa.Column("break_start",            sa.Time, nullable=True)),
    ("break_end",              lambda: sa.Column("break_end",              sa.Time, nullable=True)),
    ("days_open",              lambda: sa.Column("days_open",              ARRAY(sa.String(10)), nullable=True)),
    ("hours_timezone",         lambda: sa.Column("hours_timezone",         sa.String(50), nullable=True)),
    ("hours_verified",         lambda: sa.Column("hours_verified",         sa.Boolean, nullable=False, server_default="false")),
    ("hours_verified_by",      lambda: sa.Column("hours_verified_by",      UUID(as_uuid=True), nullable=True)),
    ("hours_verified_by_name", lambda: sa.Column("hours_verified_by_name", sa.String(100), nullable=True)),
    ("hours_verified_at",      lambda: sa.Column("hours_verified_at",      sa.DateTime(timezone=True), nullable=True)),
)


def upgrade() -> None:
    for table in ("building_profiles", "building_profile_library"):
        insp = sa.inspect(op.get_bind())
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for name, make in _HOURS:
            if name not in existing:
                op.add_column(table, make())


def downgrade() -> None:
    # No-op: this migration only ever ADDS what should already be present, so
    # dropping the columns here would delete data on databases that got them
    # legitimately at position 83.
    pass
