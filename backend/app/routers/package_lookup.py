"""Operational package lookup by TBA (ADR-245).

  GET /packages/lookup?tba=...   dispatch, management, admin

Answers "who has this package?" from a TBA alone. Every other package read is
route-scoped, so finding one meant already knowing its route — backwards for the
question dispatch actually asks.

Deliberately separate from /scorecards/packages/search: that one serves appeal
evidence and is Tier 3 (management/admin, per ADR-242). This is operational
tracking, so dispatch is included, and it returns a package's whole timeline
rather than only its exception records.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.delivery_stop import DeliveryStop
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import Route
from app.schemas.package_lookup import (
    AssignmentTrace, DeliveryTrace, ExceptionTrace,
    PackageLookupResponse, PackageTimeline,
)

router = APIRouter(prefix="/packages", tags=["packages"])

# Operational, not performance data — dispatch is in scope here even though it
# is excluded from the Tier 3 appeal-evidence search.
_allow_ops = RoleChecker(["dispatch", "management", "admin"])

# Short suffixes collide; 4 keeps "4" from matching every package ending in 4.
_MIN_SUFFIX = 4
_MAX_RESULTS = 25


def _matches(tba: str, needle: str, exact: bool) -> bool:
    """Python-side confirmation of a match.

    The SQL suffix filter uses array_to_string(...) ILIKE '%needle%', which can
    straddle an element boundary — "…447,TBA9…" would match a needle spanning
    the comma. Re-checking each element individually keeps that out of results.
    """
    return tba == needle if exact else tba.upper().endswith(needle)


@router.get("/lookup", response_model=PackageLookupResponse)
def lookup_package(
    tba: str = Query(..., min_length=_MIN_SUFFIX, max_length=50,
                     description="Full TBA or its last 4+ characters"),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_ops),
):
    """Find a package's full timeline: assignment, delivery, and exceptions.

    Suffix-first (a dispatcher is usually reading the last digits off a label or
    a call), falling back to exact when the suffix finds nothing. A suffix
    matching several distinct TBAs is reported as ambiguous with all of them
    returned, rather than guessing which was meant.
    """
    from app.models.rts import RTSPackage, MissingPackage, DamagedPackage

    cid = caller.company_id
    needle = tba.strip().upper()

    def _collect(exact: bool) -> dict[str, PackageTimeline]:
        timelines: dict[str, PackageTimeline] = {}

        def _tl(t: str) -> PackageTimeline:
            return timelines.setdefault(t, PackageTimeline(tba_number=t))

        # ── assignment: the package is on a route's manifest ──
        if exact:
            route_filter = Route.tba_numbers.any(needle)
        else:
            route_filter = func.array_to_string(Route.tba_numbers, ",").ilike(f"%{needle}%")

        routes = (
            db.query(Route, Truck.name)
            .outerjoin(TruckAssignment, TruckAssignment.id == Route.truck_assignment_id)
            .outerjoin(Truck, Truck.id == TruckAssignment.truck_id)
            .filter(Route.company_id == cid, route_filter)
            .order_by(Route.route_date.desc())
            .limit(_MAX_RESULTS)
            .all()
        )
        exec_ids = {r.executor_id for r, _ in routes if r.executor_id}
        names = {
            e.id: e.name for e in
            db.query(Employee).filter(Employee.id.in_(exec_ids),
                                      Employee.company_id == cid).all()
        } if exec_ids else {}

        for route, truck_name in routes:
            for t in (route.tba_numbers or []):
                if not _matches(t, needle, exact):
                    continue
                _tl(t).assignments.append(AssignmentTrace(
                    route_id=str(route.id), route_number=route.route_number,
                    route_date=route.route_date, route_status=route.status,
                    walker_id=str(route.executor_id) if route.executor_id else None,
                    walker_name=names.get(route.executor_id),
                    truck_name=truck_name,
                ))

        # ── delivery: a stop covering this package ──
        if exact:
            stop_filter = DeliveryStop.tba_numbers.any(needle)
        else:
            stop_filter = func.array_to_string(DeliveryStop.tba_numbers, ",").ilike(f"%{needle}%")

        stops = (
            db.query(DeliveryStop)
            .filter(DeliveryStop.company_id == cid, stop_filter)
            .order_by(DeliveryStop.completed_at.desc().nullslast())
            .limit(_MAX_RESULTS)
            .all()
        )
        for s in stops:
            for t in (s.tba_numbers or []):
                if not _matches(t, needle, exact):
                    continue
                _tl(t).deliveries.append(DeliveryTrace(
                    stop_id=str(s.id), status=s.status,
                    stop_sequence=s.stop_sequence,
                    started_at=s.started_at, completed_at=s.completed_at,
                    walker_id=str(s.walker_id) if s.walker_id else None,
                    walker_name=s.walker_name,
                    recorded_by_name=s.recorded_by_name,
                    packages_delivered=s.packages_delivered,
                ))

        # ── exceptions ──
        def _exc(model, source: str):
            f = (model.tba_number == needle) if exact \
                else model.tba_number.ilike(f"%{needle}")
            return db.query(model).filter(model.company_id == cid, f).limit(_MAX_RESULTS).all()

        for pkg in _exc(RTSPackage, "rts"):
            _tl(pkg.tba_number).exceptions.append(ExceptionTrace(
                source="rts", recorded_at=pkg.recorded_at,
                walker_name=pkg.walker_name, recorded_by_name=pkg.recorded_by_name,
                rts_type=pkg.rts_type, rts_explanation=pkg.rts_explanation,
                is_reattemptable=pkg.is_reattemptable,
            ))
        for pkg in _exc(MissingPackage, "missing"):
            _tl(pkg.tba_number).exceptions.append(ExceptionTrace(
                source="missing", recorded_at=pkg.reported_at,
                walker_name=pkg.walker_name, recorded_by_name=pkg.recorded_by_name,
                resolution_status=pkg.resolution_status, notes=pkg.resolution_notes,
            ))
        for pkg in _exc(DamagedPackage, "damaged"):
            _tl(pkg.tba_number).exceptions.append(ExceptionTrace(
                source="damaged", recorded_at=pkg.reported_at,
                route_date=pkg.route_date, recorded_by_name=pkg.reported_by_name,
                resolution_status=pkg.resolution_status,
                damage_stage=pkg.stage, notes=pkg.damage_notes,
            ))

        return timelines

    timelines = _collect(exact=False)
    matched_on = "suffix"
    if not timelines:
        timelines = _collect(exact=True)
        matched_on = "exact" if timelines else "none"

    # Resolve "who has it" from the most specific trace available.
    for tl in timelines.values():
        completed = next((d for d in tl.deliveries if d.status == "completed"), None)
        in_prog = next((d for d in tl.deliveries if d.status == "in_progress"), None)
        if completed:
            tl.current_holder_name, tl.current_holder_id = completed.walker_name, completed.walker_id
            tl.holder_basis = "delivered"
        elif in_prog:
            tl.current_holder_name, tl.current_holder_id = in_prog.walker_name, in_prog.walker_id
            tl.holder_basis = "in_progress"
        elif tl.assignments:
            a = tl.assignments[0]
            tl.current_holder_name, tl.current_holder_id = a.walker_name, a.walker_id
            tl.holder_basis = "assigned"
        elif tl.exceptions:
            tl.current_holder_name = tl.exceptions[0].walker_name
            tl.holder_basis = "exception"

    return PackageLookupResponse(
        query=needle, matched_on=matched_on,
        ambiguous=matched_on == "suffix" and len(timelines) > 1,
        results=sorted(timelines.values(), key=lambda t: t.tba_number),
    )
