"""workforce_ovs — OVs are their own unit in workforce mode (ADR-400 A2/A4/A5)

Revision ID: b1a4c956bae4
Revises: a7beae8a8562
Create Date: 2026-09-09

Purely additive: one new table, no change to any existing one. `BTROVZone` keeps
its rows and its meaning — this is what finally reads them.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "b1a4c956bae4"
down_revision = "a7beae8a8562"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workforce_ovs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("truck_id", UUID(as_uuid=True),
                  sa.ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("ov_id", sa.String(20), nullable=False),
        # A5a: the DRIVER's field — where the station staged it. Null when the OV
        # did not come from a sheet (a milk-run item has no zone).
        sa.Column("zone_label", sa.String(30), nullable=True),
        # Null until the captain measures it. Not defaulted: a guessed size
        # silently mis-costs the route.
        sa.Column("size", sa.String(4), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="sheet"),
        # Null = expected, not yet in hand. Never blocks the day close (A5c).
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # A5d — the race guard. Two captains minting from one daily company sequence
    # both compute the same max()+1; this makes the loser fail loudly and retry
    # rather than silently writing a duplicate id.
    op.create_unique_constraint(
        "uq_workforce_ovs_company_date_id",
        "workforce_ovs", ["company_id", "entry_date", "ov_id"],
    )

    op.create_index("ix_workforce_ovs_company_id", "workforce_ovs", ["company_id"])
    op.create_index("ix_workforce_ovs_truck_id", "workforce_ovs", ["truck_id"])
    op.create_index("ix_workforce_ovs_entry_date", "workforce_ovs", ["entry_date"])
    op.create_index("ix_workforce_ovs_ov_id", "workforce_ovs", ["ov_id"])
    # The roster and the sort adapter both read by truck-day.
    op.create_index(
        "ix_workforce_ovs_truck_date", "workforce_ovs",
        ["company_id", "truck_id", "entry_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_workforce_ovs_truck_date", table_name="workforce_ovs")
    op.drop_index("ix_workforce_ovs_ov_id", table_name="workforce_ovs")
    op.drop_index("ix_workforce_ovs_entry_date", table_name="workforce_ovs")
    op.drop_index("ix_workforce_ovs_truck_id", table_name="workforce_ovs")
    op.drop_index("ix_workforce_ovs_company_id", table_name="workforce_ovs")
    op.drop_constraint("uq_workforce_ovs_company_date_id", "workforce_ovs", type_="unique")
    op.drop_table("workforce_ovs")
