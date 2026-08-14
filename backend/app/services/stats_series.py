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

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from app.models.assignment_member import AssignmentMember
from app.models.delivery_stop import DeliveryStop
from app.models.rts import DamagedPackage, MissingPackage, RTSPackage
from app.models.shift_roll_call import ShiftRollCall
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import Route
from app.services.constants import TRUCK_SCOPED_ROLES

logger = logging.getLogger(__name__)

# Someone improving their performance is not comparing against three years ago,
# and this bounds the payload at roughly 28 KB.
MAX_LOOKBACK_MONTHS = 24
_MAX_LOOKBACK_DAYS = MAX_LOOKBACK_MONTHS * 31

# Roles whose "damaged" means packages reported on their TRUCK rather than
# packages they personally carried back (ADR-271 F). A captain gets both,
# reported separately.
_TRUCK_DAMAGE_ROLES = ("driver", "captain")

# Reuses the shared constant rather than re-declaring it, so this cannot drift
# from ADR-256 / assignment_history.
_TRUCK_SCOPED_ROLES = tuple(TRUCK_SCOPED_ROLES)
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
    #
    # WHOSE numbers are these? The same rule assignment_history has always used
    # (ADR-268, TRUCK_SCOPED_ROLES):
    #
    #   walker/trainee/trainer  the stops THEY executed (walker_id, ADR-244)
    #   driver/captain          the whole truck's load — they answer for it,
    #                           and they never own a stop, so scoping them by
    #                           walker_id returns ZERO for everything
    #
    # That zero was a real bug: driver.test showed 0 delivered while the trucks
    # they drove had delivered 256,733 packages. Found by opening the page as a
    # driver, not by reading the code.
    truck_wide = role in _TRUCK_SCOPED_ROLES

    stop_q = (
        db.query(
            Route.route_date,
            func.coalesce(func.sum(DeliveryStop.packages_delivered), 0),
            func.coalesce(func.sum(DeliveryStop.packages_total), 0),
            func.coalesce(func.sum(DeliveryStop.rts_count), 0),
            func.coalesce(func.sum(DeliveryStop.missing_count), 0),
        )
        .join(Route, Route.id == DeliveryStop.route_id)
    )
    if truck_wide:
        # Their own assignment is the scope: the stops that rode on a truck
        # they were rostered to that day.
        stop_q = (
            stop_q
            .join(TruckAssignment,
                  TruckAssignment.id == DeliveryStop.truck_assignment_id)
            .join(AssignmentMember,
                  AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                AssignmentMember.company_id == company_id,
                AssignmentMember.employee_id == employee_id,
                TruckAssignment.company_id == company_id,
            )
        )
    else:
        stop_q = stop_q.filter(DeliveryStop.walker_id == employee_id)

    stop_rows = (
        stop_q.filter(
            DeliveryStop.company_id == company_id,
            Route.company_id == company_id,
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
class BlockStat:
    """One block a person worked in the selected period (ADR-271 I).

    `block_key` (W_49_St_200) is on 166k+ stops and is the only geographic
    signal that survives ADR-219's address purge, so it is safe to keep and
    show indefinitely — unlike normalised_address, which is nulled after 48h.

    Ranked by RTS RATE, not by volume: "where do I struggle" is actionable in a
    way that "where do I go most" is not. Volume is still reported so a reader
    can discount a block they barely worked.
    """
    block_key: str
    stops: int = 0
    delivered: int = 0
    rts: int = 0
    rts_rate: Optional[float] = None


@dataclass
class Attendance:
    """Roll-call outcomes for the selected period (ADR-271 I).

    Attendance is self-controlled and fair — unlike peer rating, which is
    opinion — and it appears nowhere else in the product for the person
    themselves: CrewStatus is a dispatch tool for MARKING people, not a
    personal history.
    """
    present: int = 0
    late: int = 0
    ncns: int = 0          # no call, no show
    total: int = 0
    rate: Optional[float] = None    # present / total; None when nothing recorded


@dataclass
class YearStat:
    """One calendar year, all-time.

    Computed server-side rather than folded out of the daily series because the
    series is capped at 24 months (ADR-271 D) and the LIFETIME chart is
    year-over-year — a five-year employee would otherwise see two bars and a
    silent hole where their first three years were.

    Cheap: one grouped query per metric, a handful of rows.
    """
    year: int
    delivered: int = 0
    total: int = 0
    rts: int = 0
    missing: int = 0
    damaged: int = 0
    truck_damaged: int = 0


@dataclass
class LifetimeTotals:
    delivered: int = 0
    rts: int = 0
    missing: int = 0
    damaged: int = 0
    truck_damaged: int = 0
    trips: int = 0
    success_pct: Optional[float] = None


def get_year_stats(
    db: Session, company_id: UUID, employee_id: UUID, role: str
) -> list:
    """Per-calendar-year totals, all time, oldest first.

    Excludes the current in-progress day for consistency with the daily series,
    but DOES include the current year — an in-progress year is still worth
    seeing; it simply carries no trend (ADR-271 D3).
    """
    end = date.today() - timedelta(days=1)
    yr = func.cast(func.strftime("%Y", Route.route_date), Integer) \
        if db.bind and db.bind.dialect.name == "sqlite" \
        else func.extract("year", Route.route_date)

    rows = (
        db.query(
            yr.label("y"),
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
            Route.route_date <= end,
        )
        .group_by(yr)
        .all()
    )
    by_year = {
        int(y): YearStat(
            year=int(y), delivered=int(d or 0), total=int(t or 0),
            rts=int(r or 0), missing=int(m or 0),
        )
        for y, d, t, r, m in rows if y is not None
    }

    if role in _OWN_DAMAGE_ROLES:
        for y, n in (
            db.query(yr, func.count(RTSPackage.id))
            .join(Route, Route.id == RTSPackage.route_id)
            .filter(
                RTSPackage.company_id == company_id,
                Route.company_id == company_id,
                RTSPackage.walker_id == employee_id,
                RTSPackage.rts_type == "package_damaged",
                Route.route_date <= end,
            )
            .group_by(yr)
            .all()
        ):
            if y is not None and int(y) in by_year:
                by_year[int(y)].damaged = int(n or 0)

    return [by_year[k] for k in sorted(by_year)]


def get_period_extras(
    db: Session,
    company_id: UUID,
    employee_id: UUID,
    start: date,
    end: date,
    top_n: int = 5,
) -> tuple:
    """Top blocks + attendance for ONE period. Returns (blocks, attendance).

    SCOPED TO THE PERIOD, deliberately: the operator's requirement was that
    "top 5 for week 1 may not be top 5 for the month". A globally-computed
    top-5 would be the same list at every level, which tells a reader nothing
    about the period they are actually looking at.

    Not exposed at DAY level by the UI — at one day "top blocks" is just "the
    blocks you worked", which belongs in the day detail rather than a ranking.
    The service does not enforce that; it is a presentation choice.
    """
    rows = (
        db.query(
            DeliveryStop.block_key,
            func.count(DeliveryStop.id),
            func.coalesce(func.sum(DeliveryStop.packages_delivered), 0),
            func.coalesce(func.sum(DeliveryStop.rts_count), 0),
        )
        .join(Route, Route.id == DeliveryStop.route_id)
        .filter(
            DeliveryStop.company_id == company_id,
            Route.company_id == company_id,
            DeliveryStop.walker_id == employee_id,
            DeliveryStop.block_key.isnot(None),
            Route.route_date >= start,
            Route.route_date <= end,
        )
        .group_by(DeliveryStop.block_key)
        .all()
    )

    blocks = []
    for bk, stops, delivered, rts in rows:
        attempted = int(delivered or 0) + int(rts or 0)
        blocks.append(BlockStat(
            block_key=bk, stops=int(stops or 0),
            delivered=int(delivered or 0), rts=int(rts or 0),
            # None, not 0.0, when nothing was attempted there: "no packages"
            # and "a perfect record" are different facts.
            rts_rate=round(int(rts or 0) / attempted, 4) if attempted else None,
        ))

    # Worst rate first, but only among blocks with enough volume to mean
    # anything — a single returned package on a one-stop block is not a
    # pattern, and ranking it top would be actively misleading.
    MIN_STOPS = 3
    ranked = [b for b in blocks if b.stops >= MIN_STOPS and b.rts_rate is not None]
    ranked.sort(key=lambda b: (-(b.rts_rate or 0), -b.stops))
    if len(ranked) < top_n:
        # Fall back to volume so a light period still shows where they worked.
        seen = {b.block_key for b in ranked}
        extra = sorted((b for b in blocks if b.block_key not in seen),
                       key=lambda b: -b.stops)
        ranked += extra[: top_n - len(ranked)]

    att = Attendance()
    for status, n in (
        db.query(ShiftRollCall.status, func.count(ShiftRollCall.id))
        .filter(
            ShiftRollCall.company_id == company_id,
            ShiftRollCall.employee_id == employee_id,
            ShiftRollCall.date >= start,
            ShiftRollCall.date <= end,
        )
        .group_by(ShiftRollCall.status)
        .all()
    ):
        n = int(n or 0)
        att.total += n
        if status == "ncns":
            att.ncns = n
        elif status == "late":
            att.late = n
        else:
            att.present += n
    if att.total:
        att.rate = round(att.present / att.total * 100, 1)

    return ranked[:top_n], att


def get_lifetime_totals(
    db: Session, company_id: UUID, employee_id: UUID, role: str
) -> LifetimeTotals:
    """The header figures — all time, not windowed.

    Deliberately NOT derived from the series above: the series is capped at 24
    months, and "lifetime" that silently means "two years" would be a lie.
    """
    out = LifetimeTotals()

    # Same truck-vs-own rule as the series above — a driver's lifetime total
    # must not disagree with the days that make it up.
    truck_wide = role in _TRUCK_SCOPED_ROLES

    if truck_wide:
        base = (
            db.query(func.coalesce(func.sum(DeliveryStop.packages_delivered), 0))
            .join(TruckAssignment,
                  TruckAssignment.id == DeliveryStop.truck_assignment_id)
            .join(AssignmentMember,
                  AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                DeliveryStop.company_id == company_id,
                TruckAssignment.company_id == company_id,
                AssignmentMember.company_id == company_id,
                AssignmentMember.employee_id == employee_id,
            )
        )
        out.delivered = int(base.scalar() or 0)
        out.rts = int(
            db.query(func.coalesce(func.sum(DeliveryStop.rts_count), 0))
            .join(TruckAssignment,
                  TruckAssignment.id == DeliveryStop.truck_assignment_id)
            .join(AssignmentMember,
                  AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                DeliveryStop.company_id == company_id,
                TruckAssignment.company_id == company_id,
                AssignmentMember.company_id == company_id,
                AssignmentMember.employee_id == employee_id,
            ).scalar() or 0
        )
        out.missing = int(
            db.query(func.coalesce(func.sum(DeliveryStop.missing_count), 0))
            .join(TruckAssignment,
                  TruckAssignment.id == DeliveryStop.truck_assignment_id)
            .join(AssignmentMember,
                  AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                DeliveryStop.company_id == company_id,
                TruckAssignment.company_id == company_id,
                AssignmentMember.company_id == company_id,
                AssignmentMember.employee_id == employee_id,
            ).scalar() or 0
        )
    else:
        out.delivered = int(
            db.query(func.coalesce(func.sum(DeliveryStop.packages_delivered), 0))
            .filter(
                DeliveryStop.company_id == company_id,
                DeliveryStop.walker_id == employee_id,
            ).scalar() or 0
        )
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
