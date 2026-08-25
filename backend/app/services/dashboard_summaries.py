"""Dashboard summary calculations.

Every query below reads columns verified to exist via __table__.columns
introspection. See docs/DASHBOARD_FIELD_AVAILABILITY_MAP.md for the audit.

Guarantees:
  * Multi-tenancy — every query filters company_id (CLAUDE.md Dimension 1).
  * No fabrication — a metric that cannot be computed returns None, never 0
    and never a placeholder. Phase 2 shipped 11 hardcoded values; none remain.
  * Right units — rates are package-denominated, not stop-denominated
    (Dimension 5).
  * No PII in output — misroute hotspots group by block_key, never
    normalised_address (Dimension 7 + ADR-219 nulls addresses after 48h).

Reference implementations followed:
  GET /training/pipeline-summary  — active trainee + escalation semantics
  GET /field-ops/no-shows         — no-show is ShiftRollCall.status=='ncns'
  GET /field-ops/walker-stats     — WalkerRating aggregation by ratee_id
"""

from __future__ import annotations

from datetime import datetime, timedelta, date, time, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, and_, or_, case
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.field_ops import Departure, WalkerRating, VehicleInspection
from app.models.delivery_stop import DeliveryStop
from app.models.truck_assignment import TruckAssignment
from app.models.incident import Incident
from app.models.training import TrainingRecord, TrainingTask
from app.models.shift_roll_call import ShiftRollCall
from app.models.rts_clearance import RTSReport
from app.models.walker_route import Route, RouteParticipant, MisroutedPackageFlag
from app.models.package_manifest import PackageManifest
from app.models.flex_timesheets import FlexTimesheet
from app.models.company import CompanyConfig
from app.models.assignment_change_request import AssignmentChangeRequest

from app.schemas.dashboard_summaries import (
    AdminSystemHealthSummary, AdminComplianceSummary, AdminDashboardSummary,
    ManagementOperationalSummary, ManagementCrewSummary,
    ManagementIncidentSummary, ManagementFleetSummary,
    ManagementDashboardSummary,
    NoShowItem, WalkerPerformance, TroubleWalker, IncidentCategory,
    MisroutedHotspot, FailureItem, IncidentTrendItem,
    DispatchFleetSnapshot, DispatchActionQueue, DispatchPendingRequest,
    DispatchRtsRequest, DispatchUrgentIncident, DispatchPerformanceSummary,
    DispatchDashboardSummary, SlowestRoute, CrewPerformance,
    TraineePhaseRow, StuckTrainee, ProblemArea,
    CoverageDepth as CoverageDepthOut,
)
from app.services.outcome_signals import get_coverage_depth

URGENT_AGE_MINUTES = 240
STUCK_PHASE_DAYS = 21
STALE_SYNC_HOURS = 24

PHASE_LABELS = {
    1: "Phase 1", 2: "Phase 2", 3: "Phase 3", 4: "Phase 4 (solo eval)",
    5: "Phase 5 (quiz)",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pct(num: float | int | None, den: float | int | None) -> Optional[float]:
    """Percentage, or None when the denominator is absent/zero.

    Returning None rather than 0.0 is deliberate: "no data" and "zero percent"
    are different facts and must not render identically.
    """
    # ADR-294: a NULL numerator is an absence too. `num or 0` would report 0%
    # for "we do not track this", which reads as a real and alarming figure.
    # Zero itself is still a legitimate measurement and passes through.
    if num is None or not den:
        return None
    return round(num / den * 100, 2)


def _ratio(num: float | int | None, den: float | int | None, digits: int = 2) -> Optional[float]:
    # Same reasoning as _pct: a null numerator is unknown, not zero.
    if num is None or not den:
        return None
    return round(num / den, digits)


def _age_minutes(ts: Optional[datetime]) -> int:
    if ts is None:
        return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, int((_utcnow() - ts).total_seconds() / 60))


def _trend(current: Optional[float], prior: Optional[float],
           tolerance: float = 0.02) -> Optional[str]:
    """up/down/flat, or None when either side is unknown.

    Phase 2 hardcoded 'flat' — that asserted stability it had not measured.
    """
    if current is None or prior is None or prior == 0:
        return None
    delta = (current - prior) / abs(prior)
    if delta > tolerance:
        return "up"
    if delta < -tolerance:
        return "down"
    return "flat"


def _period_bounds(period: str, today: date) -> tuple[date, date]:
    if period == "today":
        return today, today
    if period == "month":
        return today.replace(day=1), today
    start = today - timedelta(days=today.weekday())   # Monday
    return start, today


def _prior_bounds(period: str, start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    prior_end = start - timedelta(days=1)
    return prior_end - timedelta(days=span - 1), prior_end


def _company_today(db: Session, company_id: UUID) -> date:
    """Company-local today, falling back to UTC if the helper is unavailable."""
    try:
        from app.services.local_date import company_today
        return company_today(db, company_id)
    except Exception:
        return _utcnow().date()


def _shift_end(db: Session, company_id: UUID):
    return (
        db.query(CompanyConfig.shift_end)
        .filter(CompanyConfig.company_id == company_id)
        .scalar()
    )


def _ts_window(db: Session, company_id: UUID, start: date, end: date) -> tuple[datetime, datetime]:
    """Half-open [start, end+1day) in the COMPANY'S timezone, as UTC-aware bounds.

    The dates come from _company_today, which is company-local — but the columns
    being filtered are UTC timestamps. Stamping those local dates as UTC drops
    the tail of the final local day: for a UTC-5 company at 22:56 local it is
    already 03:56 UTC the NEXT day, so an inspection submitted "today" lands
    after a window whose end was built as local-midnight-labelled-UTC.

    That is not hypothetical — it is the bug that made
    test_failed_items_read_real_jsonb fail: submitted_at 2026-08-01T02:56Z
    against a win_end of 2026-08-01T00:00Z, for a company whose local date was
    still 2026-07-31.

    Converting through the company's tzinfo makes the boundary mean what the
    caller intends: the start of their day to the start of their next day.
    """
    try:
        from app.services.local_date import company_tz
        tz = company_tz(db, company_id)
    except Exception:
        tz = timezone.utc
    lo = datetime.combine(start, time.min, tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    return lo.astimezone(timezone.utc), hi.astimezone(timezone.utc)


def _employee_names(db: Session, company_id: UUID, ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    rows = (
        db.query(Employee.id, Employee.name, Employee.role)
        .filter(Employee.company_id == company_id, Employee.id.in_(ids))
        .all()
    )
    return {r.id: (r.name, r.role) for r in rows}


# ── package + hour aggregates ─────────────────────────────────────────────────

def _package_totals(db: Session, company_id: UUID, start: date, end: date) -> dict:
    """Delivered / assigned / rework, denominated in PACKAGES.

    DeliveryStop.completed_at is a timestamp, so the upper bound is exclusive
    on end+1 day. All 7 DeliveryStop columns used here were verified present.

    Unplanned stops (ADR-246 field-added packages) are deliberately INCLUDED
    here, unlike in cross_check_scorecard which must exclude them. The two ask
    different questions:

      * the cross-check compares us against AMAZON'S manifest, so a package
        Amazon never manifested would manufacture a discrepancy against
        ourselves;
      * this measures OUR OWN throughput, and a walker who delivered a package
        they found really did deliver it — excluding it understates real work.

    Both packages_total and packages_delivered count it, so the completion
    ratio stays honest. Do not "fix" this to match the scorecard.
    """
    win_start, win_end = _ts_window(db, company_id, start, end)
    row = (
        db.query(
            func.coalesce(func.sum(DeliveryStop.packages_delivered), 0).label("delivered"),
            func.coalesce(func.sum(DeliveryStop.packages_total), 0).label("assigned"),
            func.coalesce(func.sum(DeliveryStop.rts_count), 0).label("rts"),
            func.coalesce(func.sum(DeliveryStop.missing_count), 0).label("missing"),
            func.count(DeliveryStop.id).label("stops"),
        )
        .filter(
            DeliveryStop.company_id == company_id,
            DeliveryStop.completed_at >= win_start,
            DeliveryStop.completed_at < win_end,
        )
        .first()
    )
    avg_stop_minutes = (
        db.query(
            func.avg(
                func.extract("epoch", DeliveryStop.completed_at - DeliveryStop.started_at) / 60.0
            )
        )
        .filter(
            DeliveryStop.company_id == company_id,
            DeliveryStop.completed_at >= win_start,
            DeliveryStop.completed_at < win_end,
            DeliveryStop.started_at.isnot(None),
        )
        .scalar()
    )
    return {
        "delivered": int(row.delivered or 0),
        "assigned": int(row.assigned or 0),
        "rework": int((row.rts or 0) + (row.missing or 0)),
        "stops": int(row.stops or 0),
        "avg_stop_minutes": round(float(avg_stop_minutes), 2) if avg_stop_minutes else None,
        "available": True,
        "reason": None,
    }


# ADR-294 D1/D2. In workforce mode DeliveryStop is never written — there is no
# per-package tracking to aggregate — so every figure above would be a hard
# zero. Zero is a measurement ("your crew delivered nothing"); this is an
# absence ("the question does not apply here"). Returning the first for the
# second is the 2026-07-29 fabricated-field failure, and a dispatcher acts on it.
_NO_PACKAGE_FEED = "no_package_feed"

_UNAVAILABLE_PACKAGE_TOTALS = {
    "delivered": None,
    "assigned": None,
    "rework": None,
    "stops": None,
    "avg_stop_minutes": None,
    "available": False,
    "reason": _NO_PACKAGE_FEED,
}


def _package_totals_for_mode(db: Session, company_id: UUID, start: date, end: date) -> dict:
    """`_package_totals`, or an explicit absence when the company has no feed.

    One shape either way (D3): same keys, nulls where inapplicable. Branching
    the DTO instead would mean two hand-maintained TypeScript interfaces in a
    `types.ts` with no codegen, and they would drift.
    """
    from app.models.company import CompanyConfig
    from app.services.constants import MODE_FULL

    cfg = (
        db.query(CompanyConfig)
        .filter(CompanyConfig.company_id == company_id)
        .first()
    )
    # A missing config is treated as NOT having the feed — the same safe
    # direction RequireMode takes. Reporting real-looking zeros for a company
    # whose configuration never claimed a feed is the worse error.
    if cfg is None or cfg.operating_mode != MODE_FULL:
        return dict(_UNAVAILABLE_PACKAGE_TOTALS)
    return _package_totals(db, company_id, start, end)


def _paid_hours(db: Session, company_id: UUID, start: date, end: date) -> tuple[Optional[float], str]:
    """Paid hours, preferring flex_timesheets (a real payroll clock) over
    Departure (a field-departure stamp). Returns (hours, source).
    """
    rows = (
        db.query(FlexTimesheet.clock_in_at, FlexTimesheet.clock_out_at,
                 FlexTimesheet.break_start_at, FlexTimesheet.break_end_at)
        .filter(
            FlexTimesheet.company_id == company_id,
            FlexTimesheet.work_date >= start,
            FlexTimesheet.work_date <= end,
            FlexTimesheet.clock_in_at.isnot(None),
            FlexTimesheet.clock_out_at.isnot(None),
        )
        .all()
    )
    if rows:
        total = 0.0
        for r in rows:
            worked = (r.clock_out_at - r.clock_in_at).total_seconds()
            if r.break_start_at and r.break_end_at:
                worked -= max(0.0, (r.break_end_at - r.break_start_at).total_seconds())
            total += max(0.0, worked)
        return round(total / 3600.0, 2), "flex_timesheets"

    deps = (
        db.query(Departure.departed_at, Departure.returned_at)
        .filter(
            Departure.company_id == company_id,
            Departure.date >= start,
            Departure.date <= end,
            Departure.returned_at.isnot(None),
        )
        .all()
    )
    if deps:
        total = sum(
            max(0.0, (d.returned_at - d.departed_at).total_seconds())
            for d in deps if d.departed_at
        )
        return round(total / 3600.0, 2), "departures"

    return None, "none"


def _route_timing(db: Session, company_id: UUID, start: date, end: date,
                  shift_end) -> dict:
    """Route duration + on-time, from Route.departed_at/returned_at.

    TruckAssignment has NEITHER created_at NOR updated_at — Phase 2 subtracted
    two columns that do not exist.
    """
    routes = (
        db.query(Route.departed_at, Route.returned_at)
        .filter(
            Route.company_id == company_id,
            Route.route_date >= start,
            Route.route_date <= end,
            Route.departed_at.isnot(None),
            Route.returned_at.isnot(None),
        )
        .all()
    )
    if not routes:
        return {"avg_hours": None, "with_timing": 0, "on_time_pct": None}

    durations = [
        (r.returned_at - r.departed_at).total_seconds() / 3600.0 for r in routes
    ]
    avg_hours = round(sum(durations) / len(durations), 2)

    on_time_pct = None
    if shift_end is not None:
        on_time = sum(1 for r in routes if r.returned_at.time() <= shift_end)
        on_time_pct = _pct(on_time, len(routes))

    return {"avg_hours": avg_hours, "with_timing": len(routes), "on_time_pct": on_time_pct}


def _graduation_pct(db: Session, company_id: UUID) -> Optional[float]:
    """Graduated = has training records but role is no longer 'trainee'.

    There is no graduation timestamp; role transition is the actual end state.

    WALKER TRACK ONLY (ADR-264). Driver trainees have TrainingRecord rows too,
    and their role is not "trainee" — so before this filter they counted as
    ALREADY GRADUATED from the day their first record was written, inflating
    the rate, while also sitting in the denominator. Two parallel tracks with
    different promotion targets cannot share one percentage.

    The exclusion is by the trainee's CURRENT role rather than by the record,
    because a walker trainee who graduated is exactly the case being counted —
    filtering records by track would drop the graduates this measures.
    """
    # Coerce to UUID: SQLite round-trips these as plain strings, which then
    # fail to bind against a UUID-typed IN clause. Postgres returns UUID
    # objects already, so this is a no-op there.
    trainee_ids = []
    for (tid,) in (
        db.query(func.distinct(TrainingRecord.trainee_id))
        .filter(TrainingRecord.company_id == company_id).all()
    ):
        if tid is None:
            continue
        trainee_ids.append(tid if isinstance(tid, UUID) else UUID(str(tid)))
    if not trainee_ids:
        return None
    # Drop anyone currently on the driver track from BOTH sides of the ratio.
    walker_track_ids = [
        eid
        for (eid,) in db.query(Employee.id)
        .filter(
            Employee.company_id == company_id,
            Employee.id.in_(trainee_ids),
            Employee.role != "driver_trainee",
        )
        .all()
    ]
    if not walker_track_ids:
        return None

    graduated = (
        db.query(func.count(Employee.id))
        .filter(
            Employee.company_id == company_id,
            Employee.id.in_(walker_track_ids),
            Employee.role != "trainee",
        )
        .scalar()
    ) or 0
    return _pct(graduated, len(walker_track_ids))


def _escalated_trainee_ids(db: Session, company_id: UUID) -> set:
    """Escalation lives on TrainingTask, not TrainingRecord — mirrors
    /training/pipeline-summary.
    """
    rows = (
        db.query(func.distinct(TrainingRecord.trainee_id))
        .join(TrainingTask, TrainingTask.training_record_id == TrainingRecord.id)
        .filter(
            TrainingRecord.company_id == company_id,
            TrainingTask.is_escalated == True,     # noqa: E712
            TrainingTask.is_completed == False,    # noqa: E712
        )
        .all()
    )
    return {r[0] for r in rows}


def _active_trainee_count(db: Session, company_id: UUID) -> int:
    return (
        db.query(func.count(Employee.id))
        .filter(
            Employee.company_id == company_id,
            Employee.role == "trainee",
            Employee.is_active == True,            # noqa: E712
        )
        .scalar()
    ) or 0


def _training_oversight(db: Session, company_id: UUID) -> dict:
    """Company-wide training roster: phase distribution, stuck trainees, and
    failing task topics.

    Scoped to the COMPANY, not a trainer — this is oversight. Phases are rows,
    not a {1..4} dict, because current_day_number reaches 5 (quiz) and 6+
    (remediation); a fixed map silently drops those trainees.
    """
    today = _company_today(db, company_id)

    active_ids = {
        r[0] for r in
        db.query(Employee.id).filter(
            Employee.company_id == company_id,
            Employee.role == "trainee",
            Employee.is_active == True,        # noqa: E712
        ).all()
    }
    if not active_ids:
        return {"phases": [], "stuck": [], "problem_areas": []}

    records = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.company_id == company_id,
                TrainingRecord.trainee_id.in_(active_ids))
        .order_by(TrainingRecord.record_date)
        .all()
    )

    # Latest record per trainee gives their current phase.
    latest: dict = {}
    for r in records:
        latest[r.trainee_id] = r

    phase_counts: dict[int, int] = {}
    for r in latest.values():
        p = int(r.current_day_number or 0)
        phase_counts[p] = phase_counts.get(p, 0) + 1
    phases = [
        TraineePhaseRow(phase=p,
                        label=PHASE_LABELS.get(p, f"Phase {p} (remediation)"),
                        trainee_count=c)
        for p, c in sorted(phase_counts.items())
    ]

    # Days at current phase, measured from the FIRST record at that phase —
    # one record exists per day, so a single record's timestamp is wrong grain.
    names = _employee_names(db, company_id, latest.keys())
    stuck = []
    for tid, rec in latest.items():
        phase = int(rec.current_day_number or 0)
        first = min((r.record_date for r in records
                     if r.trainee_id == tid and r.current_day_number == phase),
                    default=rec.record_date)
        days = (today - first).days
        if days > STUCK_PHASE_DAYS:
            stuck.append(StuckTrainee(
                trainee_name=names.get(tid, ("Unknown", ""))[0],
                phase=phase, days_in_phase=days,
            ))
    stuck.sort(key=lambda s: s.days_in_phase, reverse=True)

    problem_areas = []
    record_ids = [r.id for r in records]
    if record_ids:
        rows = (
            db.query(
                TrainingTask.topic_title,
                func.sum(case((TrainingTask.is_escalated == True, 1), else_=0)),      # noqa: E712
                func.sum(case((TrainingTask.completed_late == True, 1), else_=0)),    # noqa: E712
                func.sum(case((TrainingTask.is_training_debt == True, 1), else_=0)),  # noqa: E712
            )
            .filter(TrainingTask.company_id == company_id,
                    TrainingTask.training_record_id.in_(record_ids))
            .group_by(TrainingTask.topic_title)
            .all()
        )
        problem_areas = sorted(
            (ProblemArea(topic_title=t, escalated_count=int(e or 0),
                         late_count=int(l or 0), debt_count=int(d or 0))
             for t, e, l, d in rows
             if (e or 0) + (l or 0) + (d or 0) > 0),
            key=lambda p: (p.escalated_count, p.debt_count, p.late_count),
            reverse=True,
        )[:8]

    return {"phases": phases, "stuck": stuck, "problem_areas": problem_areas}


def _inspection_pass_rate(db: Session, company_id: UUID, start: date,
                          end: date) -> tuple[Optional[float], int]:
    win_start, win_end = _ts_window(db, company_id, start, end)
    row = (
        db.query(
            func.count(VehicleInspection.id).label("total"),
            func.sum(case((VehicleInspection.has_failures == False, 1), else_=0)).label("passed"),  # noqa: E712
        )
        .filter(
            VehicleInspection.company_id == company_id,
            VehicleInspection.submitted_at >= win_start,
            VehicleInspection.submitted_at < win_end,
        )
        .first()
    )
    total = int(row.total or 0)
    return _pct(int(row.passed or 0), total), total


def _failed_items(db: Session, company_id: UUID, start: date,
                  end: date, limit: int = 5) -> list[FailureItem]:
    """Real JSONB scan of VehicleInspection.items ({name: bool}).

    Phase 2 returned a hardcoded [{'Tires',3},{'Lights',2}].
    """
    win_start, win_end = _ts_window(db, company_id, start, end)
    rows = (
        db.query(VehicleInspection.items)
        .filter(
            VehicleInspection.company_id == company_id,
            VehicleInspection.submitted_at >= win_start,
            VehicleInspection.submitted_at < win_end,
            VehicleInspection.has_failures == True,   # noqa: E712
        )
        .all()
    )
    counts: dict[str, int] = {}
    for (items,) in rows:
        if not isinstance(items, dict):
            continue
        for name, passed in items.items():
            if passed is False:
                counts[name] = counts.get(name, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [FailureItem(item_name=k, failure_count=v) for k, v in top]


# ── Admin ─────────────────────────────────────────────────────────────────────

def get_admin_dashboard_summary(db: Session, company_id: UUID) -> AdminDashboardSummary:
    today = _company_today(db, company_id)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # ADP integration state — import guarded: the module may be absent on trees
    # without the ADP feature, and a dashboard must not hard-depend on it.
    adp_configured = adp_enabled = False
    last_emp = last_tc = None
    try:
        from app.models.adp_integration import ADPIntegration
        integ = (
            db.query(ADPIntegration)
            .filter(ADPIntegration.company_id == company_id)
            .first()
        )
        if integ:
            adp_configured = True
            adp_enabled = bool(integ.is_enabled)
            last_emp = integ.last_employee_sync_at
            last_tc = integ.last_timecard_sync_at
    except Exception:
        pass

    if not adp_configured:
        adp_status = "not_configured"
    elif not adp_enabled:
        adp_status = "disabled"
    elif last_tc is None and last_emp is None:
        adp_status = "never_synced"
    else:
        newest = max([t for t in (last_tc, last_emp) if t is not None])
        adp_status = "stale" if _age_minutes(newest) > STALE_SYNC_HOURS * 60 else "connected"

    verified_count = (
        db.query(func.count(Employee.id))
        .filter(
            Employee.company_id == company_id,
            Employee.hr_system_id_adp_verified == True,   # noqa: E712
        )
        .scalar()
    ) or 0

    flex_last = (
        db.query(func.max(FlexTimesheet.uploaded_at))
        .filter(FlexTimesheet.company_id == company_id)
        .scalar()
    )
    freshness = round(_age_minutes(flex_last) / 60.0, 1) if flex_last else None

    manifest_today = (
        db.query(func.count(PackageManifest.id))
        .filter(PackageManifest.company_id == company_id,
                PackageManifest.date == today)
        .scalar()
    ) or 0

    misroute_open = (
        db.query(func.count(MisroutedPackageFlag.id))
        .filter(MisroutedPackageFlag.company_id == company_id,
                MisroutedPackageFlag.resolved == False)   # noqa: E712
        .scalar()
    ) or 0

    system_health = AdminSystemHealthSummary(
        adp_configured=adp_configured,
        adp_enabled=adp_enabled,
        adp_last_employee_sync=last_emp,
        adp_last_timecard_sync=last_tc,
        adp_status=adp_status,
        adp_verified_employee_count=int(verified_count),
        flex_last_upload=flex_last,
        flex_data_freshness_hours=freshness,
        manifest_count_today=int(manifest_today),
        unresolved_misroute_count=int(misroute_open),
    )

    pass_rate, insp_total = _inspection_pass_rate(db, company_id, week_ago, today)

    last_record = (
        db.query(func.max(TrainingRecord.record_date))
        .filter(TrainingRecord.company_id == company_id)
        .scalar()
    )
    days_since = (today - last_record).days if last_record else None

    inc_7d = (
        db.query(func.count(Incident.id))
        .filter(Incident.company_id == company_id, Incident.date >= week_ago,
                Incident.date <= today)
        .scalar()
    ) or 0

    # One GROUP BY, not 30 sequential queries in a Python loop (Phase 2).
    trend_rows = (
        db.query(Incident.date, func.count(Incident.id))
        .filter(Incident.company_id == company_id, Incident.date >= month_ago,
                Incident.date <= today)
        .group_by(Incident.date)
        .order_by(Incident.date)
        .all()
    )

    unresolved = (
        db.query(func.count(Incident.id))
        .filter(Incident.company_id == company_id,
                Incident.resolved == False)   # noqa: E712
        .scalar()
    ) or 0
    critical_open = (
        db.query(func.count(Incident.id))
        .filter(Incident.company_id == company_id,
                Incident.severity == "critical",
                Incident.resolved == False)   # noqa: E712
        .scalar()
    ) or 0

    compliance = AdminComplianceSummary(
        graduation_completion_pct=_graduation_pct(db, company_id),
        active_trainee_count=_active_trainee_count(db, company_id),
        escalated_trainee_count=len(_escalated_trainee_ids(db, company_id)),
        days_since_last_training_record=days_since,
        vehicle_inspection_pass_rate_7d=pass_rate,
        inspections_submitted_7d=insp_total,
        failed_items_trending=_failed_items(db, company_id, week_ago, today),
        incident_7d_count=int(inc_7d),
        incident_30d_trend=[IncidentTrendItem(date=d, count=int(c)) for d, c in trend_rows],
        unresolved_incident_count=int(unresolved),
        critical_incident_count=int(critical_open),
    )

    return AdminDashboardSummary(system_health=system_health, compliance=compliance)


# ── Management ────────────────────────────────────────────────────────────────

def get_management_dashboard_summary(db: Session, company_id: UUID,
                                     period: str = "week") -> ManagementDashboardSummary:
    today = _company_today(db, company_id)
    start, end = _period_bounds(period, today)
    prior_start, prior_end = _prior_bounds(period, start, end)
    shift_end = _shift_end(db, company_id)

    pkg = _package_totals_for_mode(db, company_id, start, end)
    hours, hours_source = _paid_hours(db, company_id, start, end)
    timing = _route_timing(db, company_id, start, end, shift_end)

    prior_pkg = _package_totals_for_mode(db, company_id, prior_start, prior_end)
    prior_hours, _ = _paid_hours(db, company_id, prior_start, prior_end)

    pph = _ratio(pkg["delivered"], hours)
    prior_pph = _ratio(prior_pkg["delivered"], prior_hours)
    success = _pct(pkg["delivered"], pkg["assigned"])
    prior_success = _pct(prior_pkg["delivered"], prior_pkg["assigned"])

    routes_dispatched = (
        db.query(func.count(Route.id))
        .filter(Route.company_id == company_id, Route.route_date >= start,
                Route.route_date <= end)
        .scalar()
    ) or 0
    routes_completed = (
        db.query(func.count(Route.id))
        .filter(Route.company_id == company_id, Route.route_date >= start,
                Route.route_date <= end, Route.status == "completed")
        .scalar()
    ) or 0

    crews_total = (
        db.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id,
                Employee.is_active == True,        # noqa: E712
                Employee.role.in_(["walker", "driver", "trainer", "trainee"]))
        .scalar()
    ) or 0
    # Distinct PEOPLE on routes — Phase 2 counted distinct trucks here.
    crews_deployed = (
        db.query(func.count(func.distinct(RouteParticipant.employee_id)))
        .join(Route, Route.id == RouteParticipant.route_id)
        .filter(RouteParticipant.company_id == company_id,
                Route.route_date >= start, Route.route_date <= end)
        .scalar()
    ) or 0

    operational = ManagementOperationalSummary(
        period=period, period_start=start, period_end=end,
        total_packages_delivered=pkg["delivered"],
        total_packages_assigned=pkg["assigned"],
        total_paid_hours=hours,
        paid_hours_source=hours_source,
        packages_per_hour=pph,
        avg_minutes_per_stop=pkg["avg_stop_minutes"],
        delivery_success_rate_pct=success,
        rework_rate_pct=_pct(pkg["rework"], pkg["assigned"]),
        total_rework_count=pkg["rework"],
        # D2: say WHY, rather than leaving the client to infer it from nulls.
        package_metrics_available=pkg["available"],
        package_metrics_unavailable_reason=pkg["reason"],
        routes_dispatched=int(routes_dispatched),
        routes_completed=int(routes_completed),
        completion_rate_pct=_pct(routes_completed, routes_dispatched),
        on_time_rate_pct=timing["on_time_pct"],
        on_time_reference=shift_end.strftime("%H:%M") if shift_end else None,
        crews_total=int(crews_total),
        crews_deployed=int(crews_deployed),
        crew_utilization_pct=_pct(crews_deployed, crews_total),
        trend_packages_per_hour=_trend(pph, prior_pph),
        trend_success_rate=_trend(success, prior_success),
        prior_packages_per_hour=prior_pph,
        prior_success_rate_pct=prior_success,
    )

    # ── crew ──
    roll_rows = (
        db.query(ShiftRollCall.status, ShiftRollCall.confirmed,
                 ShiftRollCall.employee_id)
        .filter(ShiftRollCall.company_id == company_id,
                ShiftRollCall.date >= start, ShiftRollCall.date <= end)
        .all()
    )
    roll_total = len(roll_rows)
    roll_confirmed = sum(1 for r in roll_rows if r.confirmed)

    ncns_counts: dict = {}
    late_counts: dict = {}
    for r in roll_rows:
        if r.status == "ncns":
            ncns_counts[r.employee_id] = ncns_counts.get(r.employee_id, 0) + 1
        elif r.status == "late":
            late_counts[r.employee_id] = late_counts.get(r.employee_id, 0) + 1

    names = _employee_names(db, company_id,
                            set(ncns_counts) | set(late_counts))
    no_shows = [
        NoShowItem(employee_name=names.get(eid, ("Unknown", "unknown"))[0],
                   role=names.get(eid, ("Unknown", "unknown"))[1], count=c)
        for eid, c in sorted(ncns_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    win_start, win_end = _ts_window(db, company_id, start, end)
    rating_rows = (
        db.query(WalkerRating.ratee_id,
                 func.avg(WalkerRating.stars).label("avg_stars"),
                 func.count(WalkerRating.id).label("n"))
        .filter(WalkerRating.company_id == company_id,
                WalkerRating.date >= start, WalkerRating.date <= end)
        .group_by(WalkerRating.ratee_id)
        .all()
    )
    delivered_rows = (
        db.query(DeliveryStop.walker_id,
                 func.coalesce(func.sum(DeliveryStop.packages_delivered), 0))
        .filter(DeliveryStop.company_id == company_id,
                DeliveryStop.completed_at >= win_start,
                DeliveryStop.completed_at < win_end,
                DeliveryStop.walker_id.isnot(None))
        .group_by(DeliveryStop.walker_id)
        .all()
    )
    delivered_map = {w: int(n) for w, n in delivered_rows}
    rating_map = {r.ratee_id: (float(r.avg_stars), int(r.n)) for r in rating_rows}

    perf_names = _employee_names(db, company_id,
                                 set(rating_map) | set(delivered_map))
    top_walkers = sorted(
        (
            WalkerPerformance(
                employee_name=perf_names.get(eid, ("Unknown", ""))[0],
                avg_rating=round(rating_map[eid][0], 2),
                rating_count=rating_map[eid][1],
                packages_delivered=delivered_map.get(eid, 0),
            )
            for eid in rating_map
        ),
        key=lambda w: (w.avg_rating or 0, w.packages_delivered),
        reverse=True,
    )[:5]

    trouble = sorted(
        (
            TroubleWalker(
                employee_name=names.get(eid, ("Unknown", ""))[0],
                ncns_count=ncns_counts.get(eid, 0),
                late_count=late_counts.get(eid, 0),
                avg_rating=round(rating_map[eid][0], 2) if eid in rating_map else None,
            )
            for eid in (set(ncns_counts) | set(late_counts))
        ),
        key=lambda w: (w.ncns_count, w.late_count),
        reverse=True,
    )[:5]

    week_ago = today - timedelta(days=7)
    insp_pass, _ = _inspection_pass_rate(db, company_id, week_ago, today)

    escalated = _escalated_trainee_ids(db, company_id)
    oversight = _training_oversight(db, company_id)
    crew = ManagementCrewSummary(
        active_trainees=_active_trainee_count(db, company_id),
        escalated_trainees=len(escalated),
        graduation_completion_pct=_graduation_pct(db, company_id),
        roll_call_total=roll_total,
        roll_call_confirmed_pct=_pct(roll_confirmed, roll_total),
        no_shows_this_period=no_shows,
        top_walkers=top_walkers,
        trouble_walkers=trouble,
        vehicle_inspection_pass_rate_7d=insp_pass,
        trainee_phases=oversight["phases"],
        stuck_trainees=oversight["stuck"],
        training_problem_areas=oversight["problem_areas"],
        # Coverage depth is a TODAY number, not a period one: "who could I still
        # call" has no meaning averaged over last week. So it uses `today` even
        # though every other field here honours `start`/`end`.
        coverage_depth=CoverageDepthOut.model_validate(
            get_coverage_depth(db, company_id, today), from_attributes=True
        ),
    )

    # ── incidents ──
    sev_rows = (
        db.query(Incident.severity, func.count(Incident.id))
        .filter(Incident.company_id == company_id, Incident.date >= start,
                Incident.date <= end)
        .group_by(Incident.severity).all()
    )
    cat_rows = (
        db.query(Incident.category, func.count(Incident.id))
        .filter(Incident.company_id == company_id, Incident.date >= start,
                Incident.date <= end)
        .group_by(Incident.category).all()
    )
    month_ago = today - timedelta(days=30)
    cat_30d = dict(
        db.query(Incident.category, func.count(Incident.id))
        .filter(Incident.company_id == company_id, Incident.date >= month_ago,
                Incident.date <= today)
        .group_by(Incident.category).all()
    )

    oldest = (
        db.query(func.min(Incident.created_at))
        .filter(Incident.company_id == company_id,
                Incident.resolved == False)   # noqa: E712
        .scalar()
    )
    rts_pending = (
        db.query(func.count(RTSReport.id))
        .filter(RTSReport.company_id == company_id, RTSReport.status == "pending")
        .scalar()
    ) or 0
    rts_review = (
        db.query(func.avg(
            func.extract("epoch", RTSReport.reviewed_at - RTSReport.submitted_at) / 3600.0))
        .filter(RTSReport.company_id == company_id,
                RTSReport.reviewed_at.isnot(None),
                RTSReport.date >= start, RTSReport.date <= end)
        .scalar()
    )

    incidents = ManagementIncidentSummary(
        total_period=sum(int(c) for _, c in sev_rows),
        by_severity={s: int(c) for s, c in sev_rows},
        by_category=[
            IncidentCategory(category=c, count=int(n),
                             avg_per_week_30d=round(cat_30d.get(c, 0) / 4.3, 2))
            for c, n in sorted(cat_rows, key=lambda kv: kv[1], reverse=True)
        ],
        unresolved_count=int(
            db.query(func.count(Incident.id))
            .filter(Incident.company_id == company_id,
                    Incident.resolved == False).scalar() or 0),   # noqa: E712
        oldest_unresolved_age_hours=int(_age_minutes(oldest) / 60) if oldest else None,
        rts_pending_count=int(rts_pending),
        avg_rts_review_hours=round(float(rts_review), 2) if rts_review else None,
    )

    # ── fleet ──
    ta_rows = dict(
        db.query(TruckAssignment.status, func.count(TruckAssignment.id))
        .filter(TruckAssignment.company_id == company_id,
                TruckAssignment.date >= start, TruckAssignment.date <= end)
        .group_by(TruckAssignment.status).all()
    )

    mis_total = (
        db.query(func.count(MisroutedPackageFlag.id))
        .join(Route, Route.id == MisroutedPackageFlag.route_id)
        .filter(MisroutedPackageFlag.company_id == company_id,
                Route.route_date >= start, Route.route_date <= end)
        .scalar()
    ) or 0
    mis_open = (
        db.query(func.count(MisroutedPackageFlag.id))
        .join(Route, Route.id == MisroutedPackageFlag.route_id)
        .filter(MisroutedPackageFlag.company_id == company_id,
                Route.route_date >= start, Route.route_date <= end,
                MisroutedPackageFlag.resolved == False)   # noqa: E712
        .scalar()
    ) or 0
    # block_key only — never normalised_address (Dimension 7 / ADR-219).
    hotspots = (
        db.query(MisroutedPackageFlag.destination_block_key,
                 func.count(MisroutedPackageFlag.id))
        .join(Route, Route.id == MisroutedPackageFlag.route_id)
        .filter(MisroutedPackageFlag.company_id == company_id,
                Route.route_date >= start, Route.route_date <= end,
                MisroutedPackageFlag.destination_block_key.isnot(None))
        .group_by(MisroutedPackageFlag.destination_block_key)
        .order_by(func.count(MisroutedPackageFlag.id).desc())
        .limit(5).all()
    )

    fleet = ManagementFleetSummary(
        fleet_planned=int(ta_rows.get("planned", 0)),
        fleet_active=int(ta_rows.get("active", 0)),
        fleet_completed=int(ta_rows.get("completed", 0)),
        route_avg_duration_hours=timing["avg_hours"],
        routes_with_timing=timing["with_timing"],
        misrouted_count=int(mis_total),
        misrouted_unresolved=int(mis_open),
        misrouted_pct_of_packages=_pct(mis_total, pkg["assigned"]),
        misrouted_hotspots=[
            MisroutedHotspot(block_key=b, count=int(c)) for b, c in hotspots
        ],
    )

    return ManagementDashboardSummary(operational=operational, crew=crew,
                                      incidents=incidents, fleet=fleet)


# ── Dispatch ──────────────────────────────────────────────────────────────────

def get_dispatch_dashboard_summary(db: Session, company_id: UUID,
                                   date_str: Optional[str] = None) -> DispatchDashboardSummary:
    today = _company_today(db, company_id)
    try:
        target = date.fromisoformat(date_str) if date_str else today
    except (TypeError, ValueError):
        target = today

    shift_end = _shift_end(db, company_id)
    next_day = target + timedelta(days=1)

    ta_rows = dict(
        db.query(TruckAssignment.status, func.count(TruckAssignment.id))
        .filter(TruckAssignment.company_id == company_id,
                TruckAssignment.date == target)
        .group_by(TruckAssignment.status).all()
    )
    trucks_active = int(ta_rows.get("active", 0))

    routes_dispatched = (
        db.query(func.count(Route.id))
        .filter(Route.company_id == company_id, Route.route_date == target)
        .scalar()
    ) or 0
    routes_help = (
        db.query(func.count(Route.id))
        .filter(Route.company_id == company_id, Route.route_date == target,
                Route.help_requested_at.isnot(None))
        .scalar()
    ) or 0

    timing = _route_timing(db, company_id, target, target, shift_end)

    manifest = (
        db.query(func.coalesce(func.sum(PackageManifest.tote_count), 0),
                 func.coalesce(func.sum(PackageManifest.ov_count), 0))
        .filter(PackageManifest.company_id == company_id,
                PackageManifest.date == target)
        .first()
    )
    totes, ov = int(manifest[0] or 0), int(manifest[1] or 0)

    stop_rows = dict(
        db.query(DeliveryStop.status, func.count(DeliveryStop.id))
        .filter(DeliveryStop.company_id == company_id,
                DeliveryStop.completed_at >= target,
                DeliveryStop.completed_at < next_day)
        .group_by(DeliveryStop.status).all()
    )
    pkg = _package_totals_for_mode(db, company_id, target, target)

    fleet_snapshot = DispatchFleetSnapshot(
        timestamp=_utcnow(),
        dispatch_date=target,
        trucks_planned=int(ta_rows.get("planned", 0)),
        trucks_active=trucks_active,
        trucks_completed=int(ta_rows.get("completed", 0)),
        routes_dispatched=int(routes_dispatched),
        routes_needing_help=int(routes_help),
        routes_on_time_pct=timing["on_time_pct"],
        manifest_totes=totes,
        manifest_ov=ov,
        manifest_total=totes + ov,
        stops_planned=int(stop_rows.get("planned", 0)),
        stops_in_progress=int(stop_rows.get("in_progress", 0)),
        stops_completed=int(stop_rows.get("completed", 0)),
        packages_delivered=pkg["delivered"],
        # per ACTIVE TRUCK — Phase 2 averaged per stop and mislabelled it.
        avg_packages_per_active_truck=_ratio(pkg["delivered"], trucks_active),
        avg_minutes_per_stop=pkg["avg_stop_minutes"],
        package_metrics_available=pkg["available"],
        package_metrics_unavailable_reason=pkg["reason"],
    )

    # ── action queue: reassignments only (time-off moved to ADP) ──
    acr_rows = (
        db.query(AssignmentChangeRequest)
        .filter(AssignmentChangeRequest.company_id == company_id,
                AssignmentChangeRequest.status == "pending")
        .order_by(AssignmentChangeRequest.created_at)
        .limit(25).all()
    )
    acr_names = _employee_names(db, company_id, [r.employee_id for r in acr_rows])
    pending = []
    for r in acr_rows:
        age = _age_minutes(r.created_at)
        pending.append(DispatchPendingRequest(
            id=str(r.id),
            employee_name=acr_names.get(r.employee_id, ("Unknown", ""))[0],
            requested_date=r.requested_date,
            reason=r.reason,
            created_at=r.created_at,
            age_minutes=age,
            is_urgent=age > URGENT_AGE_MINUTES,
        ))

    rts_rows = (
        db.query(RTSReport)
        .filter(RTSReport.company_id == company_id,
                RTSReport.status == "pending")
        .order_by(RTSReport.submitted_at).limit(25).all()
    )
    rts_names = _employee_names(db, company_id, [r.driver_id for r in rts_rows])
    rts_requests = []
    for r in rts_rows:
        rt = (
            db.query(Route.package_count, Route.departed_at, Route.id)
            .join(RouteParticipant, RouteParticipant.route_id == Route.id)
            .filter(Route.company_id == company_id,
                    Route.route_date == r.date,
                    RouteParticipant.employee_id == r.driver_id)
            .first()
        )
        completion = remaining = field_hours = None
        if rt and rt.package_count:
            delivered = (
                db.query(func.coalesce(func.sum(DeliveryStop.packages_delivered), 0))
                .filter(DeliveryStop.company_id == company_id,
                        DeliveryStop.route_id == rt.id).scalar()
            ) or 0
            completion = _pct(delivered, rt.package_count)
            remaining = max(0, int(rt.package_count) - int(delivered))
            if rt.departed_at:
                field_hours = round(_age_minutes(rt.departed_at) / 60.0, 2)
        rts_requests.append(DispatchRtsRequest(
            report_id=str(r.id),
            driver_name=rts_names.get(r.driver_id, ("Unknown", ""))[0],
            total_rts=int(r.total_rts or 0),
            crew_confirmed=bool(r.crew_confirmed),
            submitted_at=r.submitted_at,
            age_minutes=_age_minutes(r.submitted_at),
            route_completion_pct=completion,
            packages_remaining=remaining,
            time_in_field_hours=field_hours,
        ))

    inc_rows = (
        db.query(Incident)
        .filter(Incident.company_id == company_id,
                Incident.resolved == False,               # noqa: E712
                Incident.severity.in_(["warning", "critical"]))
        .order_by(Incident.created_at).limit(25).all()
    )
    urgent = [
        DispatchUrgentIncident(
            incident_id=str(i.id), severity=i.severity, category=i.category,
            truck_id=str(i.truck_id) if i.truck_id else None,
            reported_at=i.created_at, age_minutes=_age_minutes(i.created_at),
        )
        for i in inc_rows
    ]

    action_queue = DispatchActionQueue(
        pending_reassignments=pending, rts_requests=rts_requests,
        urgent_incidents=urgent,
    )

    # ── performance: baseline = historical mean minutes-per-package ──
    hist_start = target - timedelta(days=30)
    hist = (
        db.query(Route.departed_at, Route.returned_at, Route.package_count)
        .filter(Route.company_id == company_id,
                Route.route_date >= hist_start, Route.route_date < target,
                Route.departed_at.isnot(None), Route.returned_at.isnot(None),
                Route.package_count > 0)
        .all()
    )
    per_pkg = [
        (r.returned_at - r.departed_at).total_seconds() / 60.0 / r.package_count
        for r in hist
    ]
    baseline = round(sum(per_pkg) / len(per_pkg), 3) if per_pkg else None

    todays = (
        db.query(Route.id, Route.route_number, Route.departed_at,
                 Route.returned_at, Route.package_count)
        .filter(Route.company_id == company_id, Route.route_date == target,
                Route.departed_at.isnot(None), Route.returned_at.isnot(None))
        .all()
    )
    slowest = []
    for r in todays:
        actual_h = (r.returned_at - r.departed_at).total_seconds() / 3600.0
        pc = int(r.package_count or 0)
        actual_ppm = round(actual_h * 60 / pc, 3) if pc else None
        expected_h = round(baseline * pc / 60.0, 2) if (baseline and pc) else None
        variance = (
            round((actual_h - expected_h) / expected_h * 100, 2)
            if expected_h else None
        )
        slowest.append(SlowestRoute(
            route_id=str(r.id), route_number=r.route_number,
            actual_hours=round(actual_h, 2), package_count=pc,
            actual_minutes_per_package=actual_ppm,
            expected_hours=expected_h, variance_pct=variance,
        ))
    slowest.sort(key=lambda s: s.variance_pct if s.variance_pct is not None else -999,
                 reverse=True)
    slowest = slowest[:5]

    crew_rows = (
        db.query(RouteParticipant.employee_id,
                 func.coalesce(func.sum(DeliveryStop.packages_delivered), 0))
        .join(Route, Route.id == RouteParticipant.route_id)
        .join(DeliveryStop, DeliveryStop.route_id == Route.id)
        .filter(RouteParticipant.company_id == company_id,
                Route.route_date == target)
        .group_by(RouteParticipant.employee_id).all()
    )
    crew_names = _employee_names(db, company_id, [c[0] for c in crew_rows])
    crews = [
        CrewPerformance(
            employee_name=crew_names.get(eid, ("Unknown", ""))[0],
            packages_delivered=int(n), hours=None, packages_per_hour=None,
        )
        for eid, n in crew_rows
    ]
    crews.sort(key=lambda c: c.packages_delivered, reverse=True)

    performance = DispatchPerformanceSummary(
        baseline_minutes_per_package=baseline,
        baseline_sample_size=len(per_pkg),
        slowest_routes=slowest,
        fastest_crew=crews[0] if crews else None,
        slowest_crew=crews[-1] if len(crews) > 1 else None,
    )

    return DispatchDashboardSummary(fleet_snapshot=fleet_snapshot,
                                    action_queue=action_queue,
                                    performance=performance)
