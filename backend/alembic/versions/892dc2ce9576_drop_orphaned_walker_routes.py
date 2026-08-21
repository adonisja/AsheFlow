"""drop the orphaned walker_routes/walker_trips tables (ADR-278)

WalkerRoute.__tablename__ is "routes". The tables named walker_routes and
walker_trips are debris from a rename that was applied by hand to the database
and never written into a revision: j7e8f9a0b1c2 adds columns to 'walker_routes'
but creates indexes named ix_routes_*, and its downgrade drops a table 'routes'
that no migration ever creates.

Measured on staging 2026-08-19 before writing this:
    routes         46,889 rows,  7 inbound FKs   <- live
    walker_routes       0 rows,  1 inbound FK    <- orphan (from walker_trips)
    walker_trips        0 rows                   <- orphan

The danger is not storage, it is that a query against walker_routes SUCCEEDS
and returns zeros, so a wrong table produces a confident wrong answer instead
of an error. That happened while measuring segment_ids coverage for ADR-277.

Order: walker_trips first — it holds the FK into walker_routes.

Revision ID: 892dc2ce9576
Revises: 3fd39c1ae2a7
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "892dc2ce9576"
down_revision = "3fd39c1ae2a7"
branch_labels = None
depends_on = None


def _rows(conn, table: str) -> int | None:
    """Row count, or None when the table is absent."""
    present = conn.execute(
        sa.text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
    ).scalar()
    if present is None:
        return None
    return conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()


def upgrade() -> None:
    conn = op.get_bind()

    # Refuse to destroy data. A DB that took a different path — where these
    # names ARE the live tables — must fail loudly rather than lose rows.
    for table in ("walker_trips", "walker_routes"):
        n = _rows(conn, table)
        if n:
            raise RuntimeError(
                f"ADR-278: refusing to drop non-empty {table!r} ({n} rows). "
                "On this database that table is not an orphan. Investigate "
                "before migrating; the live route table should be 'routes'."
            )

    # Sanity: the table we are keeping must actually exist.
    if _rows(conn, "routes") is None:
        raise RuntimeError(
            "ADR-278: 'routes' does not exist on this database. The rename "
            "this migration cleans up after has not happened here."
        )

    op.execute("DROP TABLE IF EXISTS walker_trips CASCADE")
    op.execute("DROP TABLE IF EXISTS walker_routes CASCADE")


def downgrade() -> None:
    """Recreate both tables empty.

    Reversible in shape, not in data — there were no rows to restore. Columns
    mirror the pre-drop schema observed on staging so a downgrade leaves the
    schema self-consistent.
    """
    op.create_table(
        "walker_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("truck_assignment_id", postgresql.UUID(as_uuid=True)),
        sa.Column("route_date", sa.Date(), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True)),
        sa.Column("total_packages", sa.Integer()),
        sa.Column("total_bags", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("total_routes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_slot_cost", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_walker_routes_company_id", "walker_routes", ["company_id"])
    op.create_index("ix_walker_routes_route_date", "walker_routes", ["route_date"])
    op.create_index(
        "ix_walker_routes_company_route_date", "walker_routes", ["company_id", "route_date"]
    )
    op.create_index(
        "ix_walker_routes_truck_assignment_id", "walker_routes", ["truck_assignment_id"]
    )
    op.create_index("ix_walker_routes_walker_id", "walker_routes", ["employee_id"])

    op.create_table(
        "walker_trips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "walker_route_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("walker_routes.id", ondelete="CASCADE"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
