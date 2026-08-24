"""ADR-291 — tote_addresses: captain-entered geography for workforce mode

Revision ID: c32c9930c584
Revises: a824ffaedeb7
Create Date: 2026-08-24

One new table, purely additive.

A row per ADDRESS rather than an array on the bag, because
`_Tote.dominant_block_key` already resolves a tote's block by majority vote
across its packages — three captain addresses vote exactly the way forty package
addresses do, so one row each means the existing vote works untouched. An array
column would need its own tallying logic beside a vote that already exists.

raw_address and normalised_address are NULLABLE because ADR-219 nulls them 48h
after entry_date, exactly like every other delivery address in the system.
block_key survives that purge and is what the sort actually routes on — a block
key cannot reconstruct a house number, which is what makes retaining it safe.

bag_id is deliberately NOT a foreign key to btr_bags. A captain must be able to
address a tote that is physically on the truck even when the BTR sheet was never
imported or was imported wrong; the sheet is a convenience, not a gate.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c32c9930c584"
down_revision = "a824ffaedeb7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tote_addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("truck_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("bag_id", sa.String(length=50), nullable=False),
        sa.Column("raw_address", sa.String(length=300), nullable=True),
        sa.Column("normalised_address", sa.String(length=200), nullable=True),
        sa.Column("block_key", sa.String(length=100), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("first_cross_street", sa.String(length=120), nullable=True),
        sa.Column("second_cross_street", sa.String(length=120), nullable=True),
        sa.Column("entry_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entered_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entered_by_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["truck_id"], ["trucks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entered_by"], ["employees.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "company_id", "truck_id", "entry_date", "bag_id", "raw_address",
            name="uq_tote_addresses_bag_address",
        ),
    )
    op.create_index("ix_tote_addresses_company_id", "tote_addresses", ["company_id"])
    op.create_index("ix_tote_addresses_truck_id", "tote_addresses", ["truck_id"])
    op.create_index("ix_tote_addresses_entry_date", "tote_addresses", ["entry_date"])
    op.create_index("ix_tote_addresses_bag_id", "tote_addresses", ["bag_id"])
    op.create_index("ix_tote_addresses_block_key", "tote_addresses", ["block_key"])


def downgrade():
    op.drop_table("tote_addresses")
