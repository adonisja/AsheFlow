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
