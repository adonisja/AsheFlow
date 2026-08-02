"""Unregistered package intake (ADR-246).

A walker finds a package in their tote that was never registered — not on any
manifest, not on any route. This decides what happens to it.

Ownership is decided BEFORE routing:

    1. in the company zone?   no  -> not ours, becomes a PackageRemoval
    2. best-fit route?
    3. adder on that route?   no  -> warn, or absorb if the best fit has departed

Public module by design: it holds no proprietary routing algorithm. Best-fit is
a straightforward block/stop proximity match, not the clustering that lives in
the gitignored sort services.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import CompanyZone
from app.models.walker_route import Route


# A route that has departed cannot take on a package: its walker may already be
# past the stop, or heading somewhere the package is not (ADR-246).
#
# The model documents the lifecycle as unassigned|assigned|in_progress|completed
# (walker_route.py:63). "locked" also appears in walker_routes.py — a route
# finalised but not yet started — so it is included as still-accepting. The set
# is expressed as what CAN accept rather than what cannot, so an unrecognised
# status fails closed: a route in an unknown state is not handed a package.
_ACCEPTING_STATUSES = {"unassigned", "assigned", "locked"}


@dataclass
class ZoneVerdict:
    """Whether the package is the company's to deliver."""
    in_zone: bool
    decidable: bool                  # False when we lack coords or a boundary
    reason: Optional[str] = None     # no_coords | no_boundary | outside


@dataclass
class RouteCandidate:
    route_id: UUID
    route_number: Optional[int]
    walker_id: Optional[UUID]
    walker_name: Optional[str]
    status: Optional[str]
    can_accept: bool
    match: str                       # block_key | address | none
    is_adders_route: bool = False


@dataclass
class IntakeAssessment:
    """The decision, before anything is written."""
    zone: ZoneVerdict
    best_fit: Optional[RouteCandidate] = None
    adders_route: Optional[RouteCandidate] = None
    candidates: list[RouteCandidate] = field(default_factory=list)
    # Set when the best fit cannot take it and something else absorbed it.
    absorbed_reason: Optional[str] = None


def load_company_boundary(db: Session, company_id: UUID) -> list[dict]:
    """The active top-level company zone as [{lat, lng}], or [].

    Mirrors run_sort._get_company_boundary. Duplicated rather than imported
    because run_sort pulls in the whole sort pipeline, and intake needs only
    this one lookup.
    """
    zone = (
        db.query(CompanyZone)
        .filter(
            CompanyZone.company_id == company_id,
            CompanyZone.parent_zone_id.is_(None),
            CompanyZone.is_active.is_(True),
        )
        .order_by(CompanyZone.created_at.desc())
        .first()
    )
    if zone is None or not zone.bounds:
        return []
    coords = zone.bounds.get("coordinates", [[]])[0]
    return [{"lat": c[1], "lng": c[0]} for c in coords]


def check_zone(
    db: Session,
    company_id: UUID,
    lat: Optional[float],
    lng: Optional[float],
) -> ZoneVerdict:
    """Is this package inside the company's authorised area?

    Reuses membership_boundary (ADR-214), which edge-buffers the polygon — a
    package on the boundary line belongs to us, and a raw polygon would reject
    it on a rounding error.

    `decidable=False` is a distinct answer from `in_zone=False`: without coords
    or a boundary we cannot prove the package is foreign, and declaring it so
    would strand a deliverable package. ADR-246 sends those to dispatch instead.
    """
    if lat is None or lng is None:
        return ZoneVerdict(in_zone=False, decidable=False, reason="no_coords")

    boundary = load_company_boundary(db, company_id)
    if not boundary:
        return ZoneVerdict(in_zone=False, decidable=False, reason="no_boundary")

    from shapely.geometry import Point
    from app.services.cluster_packages import membership_boundary

    poly = membership_boundary(boundary)
    inside = poly.covers(Point(lng, lat))
    return ZoneVerdict(
        in_zone=bool(inside),
        decidable=True,
        reason=None if inside else "outside",
    )


def find_best_fit(
    db: Session,
    company_id: UUID,
    route_date: date,
    block_key: Optional[str],
    normalised_address: Optional[str],
    adder_employee_id: Optional[UUID] = None,
) -> IntakeAssessment:
    """Rank today's routes for this package.

    Match strength, best first:
      1. the address is already a stop on that route  (exact — same building)
      2. the route covers that block_key              (same block)
      3. no match

    Deliberately NOT the truck layer's centroid haversine (ADR-184): routes are
    block-based, and a centroid says nothing about whether a walker actually
    passes the address.
    """
    routes = (
        db.query(Route)
        .filter(Route.company_id == company_id, Route.route_date == route_date)
        .all()
    )

    exec_ids = {r.executor_id for r in routes if r.executor_id}
    names: dict = {}
    if exec_ids:
        from app.models.employee import Employee
        names = {
            e.id: e.name for e in
            db.query(Employee)
            .filter(Employee.id.in_(exec_ids), Employee.company_id == company_id)
            .all()
        }

    ranked: list[tuple[int, RouteCandidate]] = []
    for r in routes:
        if normalised_address and normalised_address in (r.normalised_addresses or []):
            strength, match = 0, "address"
        elif block_key and block_key in (r.block_keys or []):
            strength, match = 1, "block_key"
        else:
            continue

        cand = RouteCandidate(
            route_id=r.id,
            route_number=r.route_number,
            walker_id=r.executor_id,
            walker_name=names.get(r.executor_id),
            status=r.status,
            can_accept=(r.status or "") in _ACCEPTING_STATUSES,
            match=match,
            is_adders_route=bool(adder_employee_id and r.executor_id == adder_employee_id),
        )
        ranked.append((strength, cand))

    ranked.sort(key=lambda t: t[0])
    candidates = [c for _, c in ranked]

    assessment = IntakeAssessment(
        zone=ZoneVerdict(in_zone=True, decidable=True),
        candidates=candidates,
        adders_route=next((c for c in candidates if c.is_adders_route), None),
    )

    if not candidates:
        return assessment

    top = candidates[0]
    if top.can_accept:
        assessment.best_fit = top
        return assessment

    # Best fit has departed. Absorb into the closest route that can still take
    # it — which may well be the adder's own, since they are holding it.
    fallback = next((c for c in candidates if c.can_accept), None)
    assessment.best_fit = fallback
    assessment.absorbed_reason = (
        f"best_fit_in_progress:{top.route_number}" if fallback else "no_accepting_route"
    )
    return assessment


# ── write path ────────────────────────────────────────────────────────────────

@dataclass
class IntakeResult:
    """What a completed intake actually did."""
    outcome: str                     # added | removal | needs_dispatch | duplicate
    route_id: Optional[UUID] = None
    route_number: Optional[int] = None
    walker_name: Optional[str] = None
    stop_id: Optional[UUID] = None
    removal_id: Optional[UUID] = None
    reason: Optional[str] = None
    # Set when the package was already registered — the operator is told WHO has
    # it rather than just being refused (ADR-246).
    existing_holder: Optional[str] = None
    existing_route_number: Optional[int] = None


def _merge_stop(stops: list | None, block_key: str, address: str, tba: str) -> list[dict]:
    """Add a package to a stop list, combining with an existing address entry.

    Returns a NEW list of NEW dicts: JSONB columns need reassignment, not
    in-place mutation, for SQLAlchemy change detection. Mirrors _merge_stops in
    walker_routes (ADR-194); reimplemented rather than imported because that
    module is proprietary and this service is public.
    """
    merged = [dict(s) for s in (stops or [])]
    for entry in merged:
        if entry.get("address") == address:
            entry["tba_numbers"] = list(dict.fromkeys(
                (entry.get("tba_numbers") or []) + [tba]
            ))
            return merged
    merged.append({
        "block_key": block_key,
        "address": address,
        "tba_numbers": [tba],
        # Loose find: it rode in someone's tote, so there is no bag of record.
        "bags": [{"bag_id": "(loose)", "bag_color": None, "tba_numbers": [tba]}],
    })
    return merged


def attach_to_route(
    db: Session,
    route: Route,
    *,
    tba: str,
    block_key: Optional[str],
    normalised_address: Optional[str],
    company_id: UUID,
    executor_id: Optional[UUID],
    executor_name: Optional[str],
    recorded_by: UUID,
    recorded_by_name: Optional[str],
):
    """Attach an unregistered package to a route, and open its stop.

    ARRAY and JSONB columns are REASSIGNED, never appended in place. There is no
    MutableList on these models, so `route.tba_numbers.append(x)` is silently
    discarded at commit — the bug this pattern exists to avoid
    (walker_routes.py:2589 documents the same rule).

    Capacity is deliberately NOT checked: the package is already physically in
    the tote, so its capacity was consumed at load. Re-checking capacity_limit
    would apply a planning rule to a fact on the ground (ADR-246).

    Does NOT commit — the caller owns the transaction so the audit row lands
    with the change.
    """
    from app.models.delivery_stop import DeliveryStop

    route.tba_numbers = list(route.tba_numbers or []) + [tba]
    route.package_count = (route.package_count or 0) + 1

    if block_key and block_key not in (route.block_keys or []):
        route.block_keys = list(route.block_keys or []) + [block_key]
    if normalised_address and normalised_address not in (route.normalised_addresses or []):
        route.normalised_addresses = list(route.normalised_addresses or []) + [normalised_address]
    if block_key and normalised_address:
        route.stops = _merge_stop(route.stops, block_key, normalised_address, tba)

    # DeliveryStop is unique on (route_id, normalised_address) — one stop per
    # building per route. A second unregistered package at an address the route
    # already visits joins the EXISTING stop rather than creating a duplicate;
    # inserting blindly raises IntegrityError.
    existing = None
    if normalised_address:
        existing = (
            db.query(DeliveryStop)
            .filter(DeliveryStop.route_id == route.id,
                    DeliveryStop.company_id == company_id,
                    DeliveryStop.normalised_address == normalised_address)
            .first()
        )
    if existing is not None:
        existing.tba_numbers = list(dict.fromkeys(
            list(existing.tba_numbers or []) + [tba]
        ))
        existing.packages_total = (existing.packages_total or 0) + 1
        # A planned stop that gains a found package stays planned; a COMPLETED
        # stop is not reopened — the walker is already past it, and the package
        # needs its own handling rather than a silent revival.
        db.flush()
        return existing

    # is_unplanned=True (ADR-197) is what keeps this out of Amazon
    # reconciliation: the package was never manifested, so counting it in
    # our_delivered would manufacture a discrepancy against ourselves.
    seq = (
        db.query(DeliveryStop)
        .filter(DeliveryStop.route_id == route.id,
                DeliveryStop.company_id == company_id)
        .count()
    ) + 1

    stop = DeliveryStop(
        company_id=company_id,
        route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        block_key=block_key or "UNKNOWN",
        normalised_address=normalised_address,
        tba_numbers=[tba],
        status="planned",
        is_unplanned=True,
        stop_sequence=seq,
        packages_total=1,
        # ADR-244: the route's executor owns the stop; whoever entered it is
        # recorded separately. A dispatcher adding for a walker is exactly the
        # delegated case that ADR fixed.
        walker_id=executor_id,
        walker_name=executor_name,
        recorded_by=recorded_by,
        recorded_by_name=recorded_by_name,
    )
    db.add(stop)
    db.flush()
    return stop


def create_foreign_removal(
    db: Session,
    *,
    company_id: UUID,
    tba: str,
    removal_date: date,
    removed_by: UUID,
    removed_by_name: Optional[str],
    reason: str = "out_of_zone",
):
    """A package that is not ours becomes a PackageRemoval, not a delivery.

    Reuses ADR-176 exactly: persist_zones writes this same row shape for
    out-of-zone packages found at the station. pull_point='anchor_point'
    distinguishes a field find, and the row carries the
    pending -> handed_over -> received custody chain the operator asked for —
    approval is not custody, so the walker->driver->station legs are recorded
    on this row rather than assumed.

    Does NOT commit.
    """
    from app.models.tote_ops import PackageRemoval

    removal = PackageRemoval(
        company_id=company_id,
        removal_date=removal_date,
        bag_id="(loose)",
        tba=tba,
        tba_numbers=None,
        package_count=1,
        whole_tote=False,
        reason=reason,
        status="flagged",
        pull_point="anchor_point",
        removed_by=removed_by,
        removed_by_name=removed_by_name,
        handoff_status="pending",
    )
    db.add(removal)
    db.flush()
    return removal
