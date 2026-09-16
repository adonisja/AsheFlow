"""ADR-440: the route log stops at the device.

Drops `collected_walker_days`. The route log is a personal record-keeping tool —
one operator reconstructing their own days to compare against dispatch output —
and it should never have had a collection endpoint. The table held coworker
names and, inside its JSONB payload, Amazon TBA package identifiers: a table
that holds those exists to be asked about, and "nobody uses this, it is my own
notes" is not an answer a collection endpoint supports.

THIS MIGRATION REFUSES TO DESTROY DATA. Dropping a table is irreversible, and
"it was empty when I checked" is a claim about one database at one moment. So
the upgrade COUNTS FIRST and aborts if anything is there, rather than trusting a
check run somewhere else. If it aborts, that is the migration doing its job:
export the rows and decide deliberately, do not force it through.

Verified 0 rows in production before writing this. Staging could not be queried
directly, which is exactly why the guard exists rather than being a formality.

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: 79d51e9b0610
Revises: 3a9f1116f17c
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "79d51e9b0610"
down_revision = "3a9f1116f17c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # The table may already be absent on a database built after this revision.
    exists = conn.execute(sa.text(
        "SELECT to_regclass('public.collected_walker_days') IS NOT NULL"
    )).scalar()
    if not exists:
        return

    rows = conn.execute(sa.text("SELECT count(*) FROM collected_walker_days")).scalar()
    if rows:
        raise RuntimeError(
            f"collected_walker_days holds {rows} row(s). This migration drops the "
            f"table and will not do that to real data. Export them "
            f"(GET /collection/walker-days before this revision, or pg_dump the "
            f"table), confirm they are not needed, then delete them and re-run."
        )

    op.drop_table("collected_walker_days")


def downgrade() -> None:
    """Recreates the table EMPTY.

    A downgrade cannot restore rows the upgrade refused to destroy — it only
    restores the shape, so a database rolled back past this point can accept
    writes again from an older application image. Said plainly because a
    downgrade that looks like a restore is worse than one that does not exist.
    """
    op.create_table(
        "collected_walker_days",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("token_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("collection_tokens.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("walker_name", sa.String(length=100), nullable=False),
        sa.Column("collected_on", sa.Date(), nullable=False, index=True),
        sa.Column("arrival_time", sa.String(length=5), nullable=True),
        sa.Column("departure_time", sa.String(length=5), nullable=True),
        sa.Column("route_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("token_id", "collected_on", "walker_name",
                            name="uq_collected_walker_days_token_day_walker"),
    )
