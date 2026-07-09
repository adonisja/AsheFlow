import uuid
from datetime import time
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func
from app.models.base import Base

RTS_TYPES = (
    "no_access",
    "business_closed",
    "package_damaged",
    "inclement_weather",
    "customer_requested_future_delivery",
    "customer_cancelled_order",
)

# Server-derived: only these types allow a same-day reattempt
_REATTEMPTABLE_TYPES = {"no_access", "business_closed", "inclement_weather"}

REATTEMPT_STATUSES = ("pending", "assigned", "attempted", "delivered", "failed_again")


def is_reattemptable(rts_type: str) -> bool:
    return rts_type in _REATTEMPTABLE_TYPES


class RTSPackage(Base):
    """One undeliverable package recorded by the walker mid-route.

    rts_type is from the fixed enum; rts_explanation is required free text.
    is_reattemptable is derived server-side from rts_type — never client-supplied.
    normalised_address is resolved from the enriched Redis manifest at record time
    and stored here so it survives Redis TTL expiry (management needs it for
    troublesome-address analysis days or weeks later).
    """
    __tablename__ = "rts_packages"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_id            = Column(UUID(as_uuid=True), ForeignKey("routes.id",            ondelete="CASCADE"), nullable=False, index=True)
    truck_assignment_id = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    tba_number          = Column(String(50),  nullable=False)
    normalised_address  = Column(String(200), nullable=True, index=True)
    rts_type            = Column(String(50),  nullable=False)
    rts_explanation     = Column(Text,        nullable=False)
    is_reattemptable    = Column(Boolean,     nullable=False, server_default="false")
    walker_id           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    walker_name         = Column(String(100), nullable=True)
    recorded_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    delivery_stop_id    = Column(UUID(as_uuid=True), ForeignKey("delivery_stops.id", ondelete="SET NULL"), nullable=True)


class MissingPackage(Base):
    """Package the walker cannot locate in their tote at delivery time.

    Separate from RTS — missing packages have their own resolution lifecycle.
    The driver still receives missing package detail at hand-off, but they are
    excluded from the physical receipt count.

    Resolution path:
      found_misroute   → misroute_flag_id linked; resolved when misroute is resolved
      found_other      → package located elsewhere; resolution_notes required
      confirmed_missing → package is genuinely unaccounted for; resolution_notes required
    """
    __tablename__ = "missing_packages"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_id            = Column(UUID(as_uuid=True), ForeignKey("routes.id",            ondelete="CASCADE"), nullable=False, index=True)
    truck_assignment_id = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    tba_number          = Column(String(50),  nullable=False)
    normalised_address  = Column(String(200), nullable=True, index=True)
    walker_id           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    walker_name         = Column(String(100), nullable=True)
    reported_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolution_status   = Column(String(30),  nullable=False, server_default="unresolved", index=True)
    misroute_flag_id    = Column(UUID(as_uuid=True), ForeignKey("misrouted_package_flags.id", ondelete="SET NULL"), nullable=True)
    resolution_notes    = Column(Text,        nullable=True)
    resolved_by         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_by_name    = Column(String(100), nullable=True)
    resolved_at         = Column(DateTime(timezone=True), nullable=True)
    delivery_stop_id    = Column(UUID(as_uuid=True), ForeignKey("delivery_stops.id", ondelete="SET NULL"), nullable=True)


class RouteHandoff(Base):
    """Walker → driver confirmation event, created as a side effect of back_at_truck.

    One row per route (unique constraint on route_id). The walker declares what
    they're returning; the driver confirms or flags a discrepancy.

    rts_count excludes missing packages. missing_count is separate.
    discrepancy_flagged does NOT block driver_confirmed_at — the driver can confirm
    receipt and flag a problem simultaneously. Dispatch resolves discrepancies.
    """
    __tablename__ = "route_handoffs"
    __table_args__ = (
        UniqueConstraint("route_id", name="uq_route_handoffs_route_id"),
    )

    id                          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id                  = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_id                    = Column(UUID(as_uuid=True), ForeignKey("routes.id",            ondelete="CASCADE"), nullable=False)
    truck_assignment_id         = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    walker_id                   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    walker_name                 = Column(String(100), nullable=True)
    driver_id                   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    driver_name                 = Column(String(100), nullable=True)
    rts_count                   = Column(Integer, nullable=False, server_default="0")
    missing_count               = Column(Integer, nullable=False, server_default="0")
    rts_package_ids             = Column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}")
    driver_confirmed_at         = Column(DateTime(timezone=True), nullable=True)
    discrepancy_flagged         = Column(Boolean, nullable=False, server_default="false")
    discrepancy_notes           = Column(Text,    nullable=True)
    discrepancy_resolved_by     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    discrepancy_resolved_by_name = Column(String(100), nullable=True)
    discrepancy_resolved_at     = Column(DateTime(timezone=True), nullable=True)
    created_at                  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


DAMAGE_STAGES = ("station_sort", "truck_load", "in_truck")


class DamagedPackage(Base):
    """Damage discovered BEFORE a route exists — station sort, truck load, or
    loose in the truck mid-day (ADR-190).

    On-route damage stays in the RTS flow (rts_type='package_damaged'); this
    table covers the pre-route window where RTSPackage can't reach (route_id
    is non-nullable there by design).

    truck_assignment_id is SET NULL, not CASCADE: a damage report is a record
    of a physical event (like an RTS row or audit entry), so clearing and
    re-running dispatch must not erase it — deliberate ADR-182 divergence.

    normalised_address is resolved best-effort from the enriched Redis manifest
    at record time (RTSPackage precedent) so it survives Redis TTL for
    troublesome-shipper/address analysis.
    """
    __tablename__ = "damaged_packages"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    route_date          = Column(Date,        nullable=False, index=True)
    tba_number          = Column(String(50),  nullable=False)
    bag_id              = Column(String(50),  nullable=True)
    truck_assignment_id = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="SET NULL"), nullable=True)
    stage               = Column(String(20),  nullable=False)   # station_sort | truck_load | in_truck
    damage_notes        = Column(Text,        nullable=False)
    normalised_address  = Column(String(200), nullable=True, index=True)
    reported_by         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    reported_by_name    = Column(String(100), nullable=True)
    reported_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolution_status   = Column(String(20),  nullable=False, server_default="open", index=True)   # open | resolved
    resolution_notes    = Column(Text,        nullable=True)
    resolved_by         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_by_name    = Column(String(100), nullable=True)
    resolved_at         = Column(DateTime(timezone=True), nullable=True)


class ReattemptAssignment(Base):
    """Same-day reattempt lifecycle for a single reattemptable RTS package.

    Created by the driver or captain from the reattemptable pool after hand-off.
    The system suggests bundles by block_key proximity after 15:00; the captain
    or driver can split, merge, or reassign the bundle freely.

    cutoff_at is set server-side to 18:30 on the route_date. No reattempts after
    that time.

    original_walker_id is surfaced to the assignor so they can decide whether to
    send the same walker (knows the building) or someone different.

    route_id is set when the reattempt is bundled into a second-wave Route.
    """
    __tablename__ = "reattempt_assignments"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id            = Column(UUID(as_uuid=True), nullable=False, index=True)
    rts_package_id        = Column(UUID(as_uuid=True), ForeignKey("rts_packages.id",       ondelete="CASCADE"), nullable=False, index=True)
    truck_assignment_id   = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id",  ondelete="CASCADE"), nullable=False, index=True)
    assigned_by           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    assigned_by_name      = Column(String(100), nullable=True)
    original_walker_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    original_walker_name  = Column(String(100), nullable=True)
    assigned_to           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    assigned_to_name      = Column(String(100), nullable=True)
    route_id              = Column(UUID(as_uuid=True), ForeignKey("routes.id",             ondelete="SET NULL"), nullable=True)
    status                = Column(String(20),  nullable=False, server_default="pending", index=True)
    bundle_suggested_at   = Column(DateTime(timezone=True), nullable=True)
    cutoff_at             = Column(DateTime(timezone=True), nullable=False)
    outcome_notes         = Column(Text,        nullable=True)
    created_at            = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
