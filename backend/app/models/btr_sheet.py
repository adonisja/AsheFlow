"""The Amazon BTR sheet — a truck's load structure, with no TBAs and no addresses (ADR-290).

Amazon prints one of these per truck at the station. It is NOT a manifest: it
carries no tracking numbers and no customer addresses, which is precisely why it
survives in workforce mode where the manifest does not.

    Route  Service Type              DSP   Anchor Point         Total Routes
    BTR31  Box Truck Parcel (26ft)   NYCD  40.75643 -73.99744   12

      Name   Package Count  Bag Count  OV Count  OV Sort Zones     Bag Labels
      WE37   56             3          6         A-27.2W | 2 ...   Green 5270, ...

MODE-INDEPENDENT. In workforce mode this is the bag inventory the sort consumes.
In full mode it is a reconciliation source: per-route bag and package counts
checked against the manifest, so a missing bag is caught at the dock rather than
discovered on the street.

Four tables rather than one JSONB blob because every level is queried
independently: bags by id (which truck is this tote on?), routes by name (cross-
checking Flex), OV zones by label (where are the oversized items staged?).

Every table carries `company_id` DIRECTLY rather than reaching it through a join.
A query that starts from BTRBag has no tenant filter otherwise, and is one
forgotten join away from leaking across companies (CLAUDE.md dim 1) — the same
reasoning ScorecardMetric records.
"""
import uuid

from sqlalchemy import (
    Column, String, Integer, Float, Date, DateTime, ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


# How the sheet reached us. Drives whether a human confirmed the values.
BTR_SOURCES = ("csv", "image", "manual")


class BTRSheet(Base):
    """One BTR sheet — one truck, one day.

    The header row of the printed sheet.
    """
    __tablename__ = "btr_sheets"
    __table_args__ = (
        # One sheet per truck per day. A re-import replaces rather than duplicates:
        # the second photo of the same sheet is a correction, not a second truck.
        UniqueConstraint("truck_id", "sheet_date", name="uq_btr_sheets_truck_date"),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id   = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    sheet_date = Column(Date, nullable=False, index=True)

    # "BTR31" — the warehouse loading zone where this truck's totes are staged.
    # Distinct from dock_zone, which is where the DRIVER collects the truck; see
    # ADR-290 D4 and the correction in that ADR's context section.
    btr_loading_zone   = Column(String(50), nullable=True)

    # "Box Truck Parcel (26ft) NYC" — the vehicle class Amazon dispatched for.
    service_type       = Column(String(60), nullable=True)

    # Amazon's own route count for the truck. NOT our route count: Amazon routes
    # are built for a driver delivering by vehicle, ours for a walker on foot,
    # and ADR-291 D7 expects them to differ. Stored as a cross-check, never as a
    # target.
    amazon_route_count = Column(Integer, nullable=True)

    # Amazon's SUGGESTED anchor point. Deliberately separate from
    # Truck.initial_anchor_lat/lng (ADR-290 D5): useful as a cold-start seed and
    # as a comparison signal, but it must never silently replace an anchor the
    # operation chose for itself.
    amazon_anchor_lat  = Column(Float, nullable=True)
    amazon_anchor_lng  = Column(Float, nullable=True)

    source       = Column(String(10), nullable=False)   # csv | image | manual
    ingested_by  = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
                          nullable=True)
    ingested_at  = Column(DateTime(timezone=True), server_default=func.now())


class BTRRoute(Base):
    """One Amazon route on the sheet (WE37, WE38, ...).

    Recorded as REFERENCE, never as the sort unit. A captain cross-checks a
    walker's Flex itinerary against this; the workforce sort ignores it entirely
    and re-partitions the totes freely (ADR-290 D7, ADR-291 D5).
    """
    __tablename__ = "btr_routes"
    __table_args__ = (
        UniqueConstraint("btr_sheet_id", "amazon_route_name",
                         name="uq_btr_routes_sheet_name"),
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id        = Column(UUID(as_uuid=True), nullable=False, index=True)
    btr_sheet_id      = Column(UUID(as_uuid=True),
                               ForeignKey("btr_sheets.id", ondelete="CASCADE"),
                               nullable=False, index=True)

    amazon_route_name = Column(String(30), nullable=False)   # "WE37"

    # Amazon's printed counts. Nullable because a creased photo may not yield
    # every cell, and a missing count must read as "unknown" rather than zero —
    # zero is a measurement and would make the reconciliation lie.
    package_count     = Column(Integer, nullable=True)
    bag_count         = Column(Integer, nullable=True)
    ov_count          = Column(Integer, nullable=True)


class BTRBag(Base):
    """One tote listed under a route's Bag Labels.

    The bag id and colour come from ADR-230's `<Color> <number>` label format,
    parsed by `parse_bag_label` — the same parser the manifest path already uses,
    unchanged.
    """
    __tablename__ = "btr_bags"
    __table_args__ = (
        # A physical tote appears once per sheet. Scoped to the SHEET, not the
        # route: the same bag id can recur across days, and across companies.
        UniqueConstraint("btr_sheet_id", "bag_id", name="uq_btr_bags_sheet_bag"),
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id        = Column(UUID(as_uuid=True), nullable=False, index=True)
    btr_sheet_id      = Column(UUID(as_uuid=True),
                               ForeignKey("btr_sheets.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    btr_route_id      = Column(UUID(as_uuid=True),
                               ForeignKey("btr_routes.id", ondelete="CASCADE"),
                               nullable=False, index=True)

    bag_id            = Column(String(50), nullable=False, index=True)   # "5270"
    # Resolved hex from bag_colors.BAG_COLOR_HEX. Null for an unknown or absent
    # colour word — clients render a neutral pill (ADR-230).
    bag_color         = Column(String(10), nullable=True)

    # Denormalised from the parent route so a captain looking up one tote does
    # not need a join to answer "which Flex route is this on?". Reference only.
    amazon_route_name = Column(String(30), nullable=True)


class BTROVZone(Base):
    """One "zone | count" pair from a route's OV Sort Zones cell.

    "A-27.2W | 2" means two oversized items staged at A-27.2W. These reconcile
    against the route's ov_count — verified on the sample sheet: WE37's
    2+2+1+1 = 6 = its OV Count.
    """
    __tablename__ = "btr_ov_zones"
    __table_args__ = (
        UniqueConstraint("btr_route_id", "zone_label", name="uq_btr_ov_zones_route_zone"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id   = Column(UUID(as_uuid=True), nullable=False, index=True)
    btr_route_id = Column(UUID(as_uuid=True),
                          ForeignKey("btr_routes.id", ondelete="CASCADE"),
                          nullable=False, index=True)

    zone_label   = Column(String(30), nullable=False)   # "A-27.2W"
    ov_count     = Column(Integer, nullable=False)
