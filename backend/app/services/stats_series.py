"""The slim daily series behind My Stats (ADR-271).

WHY A SEPARATE SERVICE FROM assignment_history
`assignment-history` returns everything about a day — crew, RTS rows,
addresses. Measured on staging: 1,978 bytes per day, of which the 32-person
crew roster is the bulk (1,215 crew rows across 37 days). The charts need six
numbers per day and nothing else: 54 bytes, a 37x reduction. Three years of
this is ~41 KB, less than one year of the full payload.

So the client fetches this ONCE and aggregates year/month/week on device — they
are all groupings of the same daily rows. Day DETAIL (crew, RTS explanations)
stays on assignment-history, fetched only when a day is opened.

TODAY IS EXCLUDED, DELIBERATELY
The series ends yesterday. Today's numbers are in flight, so a cached figure
would be wrong within minutes and a refetch would show a number moving under
the reader. Excluding it makes the payload IMMUTABLE once fetched, which is
what makes the cache safe at all — no staleness policy, no partial-day
ambiguity. Completed work is also the right frame for reviewing performance.

DATED BY route_date, NOT completed_at
`DeliveryStop.completed_at` is nullable and is null across existing data — the
bug that made the old 4-week trend report 0 while lifetime showed 379
(ADR-270). `Route.route_date` is always set and is what assignment_history
uses, so the two surfaces cannot disagree about the same packages.

Public by design: read-only aggregation over completed records, no routing
algorithm, nothing proprietary.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.assignment_member import AssignmentMember
from app.models.delivery_stop import DeliveryStop
from app.models.rts import DamagedPackage, MissingPackage, RTSPackage
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import Route

logger = logging.getLogger(__name__)

# Someone improving their performance is not comparing against three years ago,
# and this bounds the payload at roughly 28 KB.
MAX_LOOKBACK_MONTHS = 24
_MAX_LOOKBACK_DAYS = MAX_LOOKBACK_MONTHS * 31

# Roles whose "damaged" means packages reported on their TRUCK rather than
# packages they personally carried back (ADR-271 F). A captain gets both,
# reported separately.
_TRUCK_DAMAGE_ROLES = ("driver", "captain")
_OWN_DAMAGE_ROLES = ("walker", "trainee", "trainer", "captain")


@dataclass
class DayStat:
    """One completed day. Six numbers and a difficulty class — nothing else.

    Field names stay short because this is the payload the client caches for up
    to two years; `packages_delivered` repeated 780 times is 8 KB of key names
    on its own.
    """
    d: date
    delivered: int = 0
    total: int = 0
    rts: int = 0
    missing: int = 0
    # Packages the person brought back DAMAGED (a subset of `rts`, since
    # package_damaged is one of the six RTS_TYPES).
    damaged: int = 0
    # Damage reported on their truck pre-delivery (station_sort/truck_load/
    # in_truck). Separate from `damaged` and never summed with it: they are
    # different events and "3 on route, 2 at load" is actionable where
    # "5 damaged" is not.
    truck_damaged: int = 0
    effort: Optional[str] = None


@dataclass
class StatsSeries:
    start_date: date
    end_date: date            # yesterday, never today
    role: str
    days: list = field(default_factory=list)


def get_stats_series(
    db: Session,
    company_id: UUID,
    employee_id: UUID,
    role: str,
    months: int = MAX_LOOKBACK_MONTHS,
) -> StatsSeries:
    """Completed days for one employee, oldest first, EXCLUDING today.

    Caller is responsible for authorisation — the endpoint decides whether
    `employee_id` may be someone other than the caller.
    """
    today = date.today()
    end = today - timedelta(days=1)
    span = min(max(months, 1), MAX_LOOKBACK_MONTHS) * 31
    start = today - timedelta(days=min(span, _MAX_LOOKBACK_DAYS))

    series = StatsSeries(start_date=start, end_date=end, role=role)
    if end < start:
        return series

    # ── delivered / total / rts / missing, per route_date ────────────────────
    # walker_id is the EXECUTOR (ADR-244): the stops this person actually
    # carried, which is what a personal stats page must count.
    stop_rows = (
        db.query(
            Route.route_date,
            func.coalesce(func.sum(DeliveryStop.packages_delivered), 0),
            func.coalesce(func.sum(DeliveryStop.packages_total), 0),
            func.coalesce(func.sum(DeliveryStop.rts_count), 0),
            func.coalesce(func.sum(DeliveryStop.missing_count), 0),
        )
        .join(Route, Route.id == DeliveryStop.route_id)
        .filter(
            DeliveryStop.company_id == company_id,
            Route.company_id == company_id,
            DeliveryStop.walker_id == employee_id,
            Route.route_date >= start,
            Route.route_date <= end,
        )
        .group_by(Route.route_date)
        .all()
    )

    by_day: dict = {}
    for d, delivered, total, rts, missing in stop_rows:
        by_day[d] = DayStat(
            d=d, delivered=int(delivered or 0), total=int(total or 0),
            rts=int(rts or 0), missing=int(missing or 0),
        )

    # ── effort class per day ─────────────────────────────────────────────────
    # A day can carry several routes; take the first non-null. Difficulty is a
    # property of the work, and mixed-difficulty days are rare enough that a
    # representative value beats inventing an average of categories.
    effort_rows = (
        db.query(Route.route_date, Route.effort_class)
        .filter(
            Route.company_id == company_id,
            Route.route_date >= start,
            Route.route_date <= end,
            Route.effort_class.isnot(None),
            Route.id.in_(
                db.query(DeliveryStop.route_id).filter(
                    DeliveryStop.company_id == company_id,
                    DeliveryStop.walker_id == employee_id,
                )
            ),
        )
        .all()
    )
    for d, effort in effort_rows:
        if d in by_day and by_day[d].effort is None:
            by_day[d].effort = effort

    # ── damaged: OWN (brought back damaged) ──────────────────────────────────
    # package_damaged is one of the six RTS_TYPES, so this is a SUBSET of `rts`,
    # reported separately because damage and undeliverable are different
    # outcomes — ours tracks them apart and Amazon scores them apart.
    if role in _OWN_DAMAGE_ROLES:
        dmg_rows = (
            db.query(Route.route_date, func.count(RTSPackage.id))
            .join(Route, Route.id == RTSPackage.route_id)
            .filter(
                RTSPackage.company_id == company_id,
                Route.company_id == company_id,
                RTSPackage.walker_id == employee_id,
                RTSPackage.rts_type == "package_damaged",
                Route.route_date >= start,
                Route.route_date <= end,
            )
            .group_by(Route.route_date)
            .all()
        )
        for d, n in dmg_rows:
            if d in by_day:
                by_day[d].damaged = int(n or 0)

    # ── damaged: TRUCK (reported on the vehicle, pre-delivery) ───────────────
    # Attributed via the person's OWN assignment for that date, not via
    # DamagedPackage.reported_by — reported_by records who FOUND the damage,
    # not whose work it was, so using it would credit a finder as an owner.
    if role in _TRUCK_DAMAGE_ROLES:
        truck_rows = (
            db.query(DamagedPackage.route_date, func.count(DamagedPackage.id))
            .join(
                TruckAssignment,
                TruckAssignment.id == DamagedPackage.truck_assignment_id,
            )
            .join(
                AssignmentMember,
                AssignmentMember.assignment_id == TruckAssignment.id,
            )
            .filter(
                DamagedPackage.company_id == company_id,
                TruckAssignment.company_id == company_id,
                AssignmentMember.company_id == company_id,
                AssignmentMember.employee_id == employee_id,
                DamagedPackage.route_date >= start,
                DamagedPackage.route_date <= end,
            )
            .group_by(DamagedPackage.route_date)
            .all()
        )
        for d, n in truck_rows:
            # A day with truck damage but no delivered stops is still a real
            # day for a driver, so create the row rather than dropping it.
            if d not in by_day:
                by_day[d] = DayStat(d=d)
            by_day[d].truck_damaged = int(n or 0)

    series.days = [by_day[k] for k in sorted(by_day)]
    return series


@dataclass
class LifetimeTotals:
    delivered: int = 0
    rts: int = 0
    missing: int = 0
    damaged: int = 0
    truck_damaged: int = 0
    trips: int = 0
    success_pct: Optional[float] = None


def get_lifetime_totals(
    db: Session, company_id: UUID, employee_id: UUID, role: str
) -> LifetimeTotals:
    """The header figures — all time, not windowed.

    Deliberately NOT derived from the series above: the series is capped at 24
    months, and "lifetime" that silently means "two years" would be a lie.
    """
    out = LifetimeTotals()

    delivered = (
        db.query(func.coalesce(func.sum(DeliveryStop.packages_delivered), 0))
        .filter(
            DeliveryStop.company_id == company_id,
            DeliveryStop.walker_id == employee_id,
        )
        .scalar()
    ) or 0
    out.delivered = int(delivered)

    out.rts = int(
        db.query(func.count(RTSPackage.id)).filter(
            RTSPackage.company_id == company_id,
            RTSPackage.walker_id == employee_id,
        ).scalar() or 0
    )
    out.missing = int(
        db.query(func.count(MissingPackage.id)).filter(
            MissingPackage.company_id == company_id,
            MissingPackage.walker_id == employee_id,
        ).scalar() or 0
    )

    if role in _OWN_DAMAGE_ROLES:
        out.damaged = int(
            db.query(func.count(RTSPackage.id)).filter(
                RTSPackage.company_id == company_id,
                RTSPackage.walker_id == employee_id,
                RTSPackage.rts_type == "package_damaged",
            ).scalar() or 0
        )

    if role in _TRUCK_DAMAGE_ROLES:
        out.truck_damaged = int(
            db.query(func.count(DamagedPackage.id))
            .join(TruckAssignment,
                  TruckAssignment.id == DamagedPackage.truck_assignment_id)
            .join(AssignmentMember,
                  AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                DamagedPackage.company_id == company_id,
                TruckAssignment.company_id == company_id,
                AssignmentMember.company_id == company_id,
                AssignmentMember.employee_id == employee_id,
            ).scalar() or 0
        )

    # trip_count is per assignment-member row (ADR-199), so summing gives every
    # trip they have run.
    out.trips = int(
        db.query(func.coalesce(func.sum(AssignmentMember.trip_count), 0)).filter(
            AssignmentMember.company_id == company_id,
            AssignmentMember.employee_id == employee_id,
        ).scalar() or 0
    )

    # Null rather than 0.0 when nothing has been attempted: "no data" and "0%
    # success" are different facts and must not render identically.
    attempted = out.delivered + out.rts + out.missing
    if attempted:
        out.success_pct = round(out.delivered / attempted * 100, 1)

    return out
