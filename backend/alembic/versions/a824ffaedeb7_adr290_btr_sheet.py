"""ADR-290 — BTR sheet ingestion: four tables, two additive columns

Revision ID: a824ffaedeb7
Revises: a35e323d69f5
Create Date: 2026-08-24

Purely additive. No backfill, no constraint changes, nothing to migrate:

  companies.amazon_dsp_name      — ADR-289 D8, the DSP label as Amazon prints it
                                   ("NYCD"), used to validate an imported sheet
                                   belongs to this company.
  truck_assignments.btr_loading_zone
                                 — the warehouse zone the truck's totes are
                                   staged in ("BTR31"). A DIFFERENT PLACE from
                                   dock_zone, which is where the driver collects
                                   the vehicle. An earlier ADR draft proposed
                                   splitting dock_zone on the theory it
                                   conflated the two; reading the code showed it
                                   does not, so this ADDS rather than splits and
                                   the six existing dock_zone readers are
                                   untouched.
  btr_sheets / btr_routes / btr_bags / btr_ov_zones
                                 — the sheet, its Amazon routes, their bag
                                   labels, and their OV sort zones.

Every BTR table carries company_id directly rather than reaching it through a
join: a query starting from btr_bags would otherwise have no tenant filter and
be one forgotten join away from crossing companies (CLAUDE.md dim 1).

Counts are nullable on btr_routes. A creased photo may not yield every cell, and
a missing count must read as unknown rather than zero — zero is a measurement,
and would make the full-mode reconciliation report a discrepancy that is really
just an unread cell.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a824ffaedeb7"
down_revision = "a35e323d69f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("companies", sa.Column("amazon_dsp_name", sa.String(length=100), nullable=True))
    op.add_column(
        "truck_assignments",
        sa.Column("btr_loading_zone", sa.String(length=50), nullable=True),
    )

    op.create_table(
        "btr_sheets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("truck_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sheet_date", sa.Date(), nullable=False),
        sa.Column("btr_loading_zone", sa.String(length=50), nullable=True),
        sa.Column("service_type", sa.String(length=60), nullable=True),
        sa.Column("amazon_route_count", sa.Integer(), nullable=True),
        sa.Column("amazon_anchor_lat", sa.Float(), nullable=True),
        sa.Column("amazon_anchor_lng", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("ingested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["truck_id"], ["trucks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingested_by"], ["employees.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("truck_id", "sheet_date", name="uq_btr_sheets_truck_date"),
    )
    op.create_index("ix_btr_sheets_company_id", "btr_sheets", ["company_id"])
    op.create_index("ix_btr_sheets_truck_id", "btr_sheets", ["truck_id"])
    op.create_index("ix_btr_sheets_sheet_date", "btr_sheets", ["sheet_date"])

    op.create_table(
        "btr_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("btr_sheet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amazon_route_name", sa.String(length=30), nullable=False),
        sa.Column("package_count", sa.Integer(), nullable=True),
        sa.Column("bag_count", sa.Integer(), nullable=True),
        sa.Column("ov_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["btr_sheet_id"], ["btr_sheets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("btr_sheet_id", "amazon_route_name", name="uq_btr_routes_sheet_name"),
    )
    op.create_index("ix_btr_routes_company_id", "btr_routes", ["company_id"])
    op.create_index("ix_btr_routes_btr_sheet_id", "btr_routes", ["btr_sheet_id"])

    op.create_table(
        "btr_bags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("btr_sheet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("btr_route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bag_id", sa.String(length=50), nullable=False),
        sa.Column("bag_color", sa.String(length=10), nullable=True),
        sa.Column("amazon_route_name", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["btr_sheet_id"], ["btr_sheets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["btr_route_id"], ["btr_routes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("btr_sheet_id", "bag_id", name="uq_btr_bags_sheet_bag"),
    )
    op.create_index("ix_btr_bags_company_id", "btr_bags", ["company_id"])
    op.create_index("ix_btr_bags_btr_sheet_id", "btr_bags", ["btr_sheet_id"])
    op.create_index("ix_btr_bags_btr_route_id", "btr_bags", ["btr_route_id"])
    op.create_index("ix_btr_bags_bag_id", "btr_bags", ["bag_id"])

    op.create_table(
        "btr_ov_zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("btr_route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("zone_label", sa.String(length=30), nullable=False),
        sa.Column("ov_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["btr_route_id"], ["btr_routes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("btr_route_id", "zone_label", name="uq_btr_ov_zones_route_zone"),
    )
    op.create_index("ix_btr_ov_zones_company_id", "btr_ov_zones", ["company_id"])
    op.create_index("ix_btr_ov_zones_btr_route_id", "btr_ov_zones", ["btr_route_id"])


def downgrade():
    op.drop_table("btr_ov_zones")
    op.drop_table("btr_bags")
    op.drop_table("btr_routes")
    op.drop_table("btr_sheets")
    op.drop_column("truck_assignments", "btr_loading_zone")
    op.drop_column("companies", "amazon_dsp_name")
