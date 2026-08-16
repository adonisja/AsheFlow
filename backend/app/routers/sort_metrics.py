"""Read the sort-decision telemetry series (ADR-273).

WHY THE SERIES IS RETURNED RAW
Weekly / monthly / annual are GROUPINGS of the same daily rows, not separate
stores — the stats_series (ADR-271) shape. The endpoint returns daily rows plus
a server-computed summary for the requested window; a client that wants a
different bucketing regroups the same payload rather than issuing a new query
shape.

ACCESS
Management and admin. Dispatch is deliberately excluded, matching ADR-242's
finding that dispatch is not management: these are cross-run algorithm metrics
used to justify a tenant-wide tuning change, not a daily operational surface.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee, require_configured
from app.database import get_db
from app.models.employee import Employee

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sort-metrics",
    tags=["sort-metrics"],
    dependencies=[Depends(require_configured)],
)

allow_oversight = RoleChecker(["management", "admin"])

# A window longer than this is a report, not a dashboard read, and would scan
# an unbounded slice of the table.
MAX_WINDOW_DAYS = 400


class SortDailyOut(BaseModel):
    """One truck-day of sort metrics. No PII: block counts and durations only."""
    model_config = ConfigDict(from_attributes=True)

    route_date: date
    truck_id: Optional[UUID] = None
    truck_name: Optional[str] = None
    algorithm_version: Optional[str] = None
    sort_runs: int = 0

    routes: int = 0
    blocks_split: int = 0
    orphan_blocks: int = 0
    runt_routes: int = 0
    blocks_per_route_avg: Optional[float] = None
    blocks_per_route_hist: Optional[dict] = None
    capacity_util_pct: Optional[float] = None

    packages: int = 0
    stops: int = 0
    route_minutes_avg: Optional[float] = None
    route_minutes_p90: Optional[float] = None
    routes_timed: int = 0
    by_effort_class: Optional[dict] = None

    rts_total: int = 0
    missing_total: int = 0
    help_requests: int = 0


class SortMetricsSummary(BaseModel):
    """Window totals. Rates are reported per effort class, never pooled.

    Pooling an RTS rate across effort classes ranks whoever drew the hard work
    as worst — outcome_signals measured 2.10% easy against 10.81% heavy.
    """
    days: int
    trucks: int
    routes: int
    packages: int
    blocks_split: int
    orphan_blocks: int
    runt_routes: int
    help_requests: int
    blocks_per_route_avg: Optional[float] = None
    capacity_util_pct: Optional[float] = None
    route_minutes_avg: Optional[float] = None
    # {"block_completion_v1": 42, "group_first_v1": 18} — truck-days per version.
    # A window spanning a switch has both; compare within a version, not across.
    truck_days_by_version: dict[str, int] = Field(default_factory=dict)
    # {"1": 120, "2": 61, "3": 4} — the ADR-272 acceptance criterion.
    blocks_per_route_hist: dict[str, int] = Field(default_factory=dict)


class SortMetricsResponse(BaseModel):
    start: date
    end: date
    summary: SortMetricsSummary
    series: list[SortDailyOut]


@router.get("", response_model=SortMetricsResponse)
def get_sort_metrics(
    start: Optional[date] = Query(None, description="Inclusive start date (default: 28 days back)."),
    end: Optional[date] = Query(None, description="Inclusive end date (default: yesterday)."),
    truck_id: Optional[UUID] = Query(None, description="Restrict to one truck."),
    caller: Employee = Depends(get_caller_employee),
    _: None = Depends(allow_oversight),
    db: Session = Depends(get_db),
) -> SortMetricsResponse:
    """Daily sort metrics for the caller's company, plus a window summary.

    The series ends yesterday by default: today's sort is still in flight and
    the rollup only writes completed days (ADR-273).
    """
    from app.models.route_sort_run import RouteSortDaily
    from app.services.local_date import company_today

    today = company_today(db, caller.company_id)
    end = end or (today - timedelta(days=1))
    start = start or (end - timedelta(days=27))

    if start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start must be on or before end.",
        )
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Window cannot exceed {MAX_WINDOW_DAYS} days.",
        )

    q = (
        db.query(RouteSortDaily)
        .filter(
            RouteSortDaily.company_id == caller.company_id,
            RouteSortDaily.route_date >= start,
            RouteSortDaily.route_date <= end,
        )
    )
    if truck_id is not None:
        q = q.filter(RouteSortDaily.truck_id == truck_id)
    rows = q.order_by(RouteSortDaily.route_date, RouteSortDaily.truck_name).all()

    hist: dict[str, int] = {}
    versions: dict[str, int] = {}
    bpr_weighted = 0.0
    bpr_routes = 0
    util_weighted = 0.0
    util_routes = 0
    minutes_weighted = 0.0
    minutes_timed = 0

    for r in rows:
        for k, v in (r.blocks_per_route_hist or {}).items():
            hist[k] = hist.get(k, 0) + int(v)
        if r.algorithm_version:
            versions[r.algorithm_version] = versions.get(r.algorithm_version, 0) + 1
        # Weight by route count: a truck-day with 30 routes should not average
        # equally against one with 6.
        if r.blocks_per_route_avg is not None and r.routes:
            bpr_weighted += r.blocks_per_route_avg * r.routes
            bpr_routes += r.routes
        if r.capacity_util_pct is not None and r.routes:
            util_weighted += r.capacity_util_pct * r.routes
            util_routes += r.routes
        if r.route_minutes_avg is not None and r.routes_timed:
            minutes_weighted += r.route_minutes_avg * r.routes_timed
            minutes_timed += r.routes_timed

    summary = SortMetricsSummary(
        days=len({r.route_date for r in rows}),
        trucks=len({r.truck_id for r in rows if r.truck_id}),
        routes=sum(r.routes for r in rows),
        packages=sum(r.packages for r in rows),
        blocks_split=sum(r.blocks_split for r in rows),
        orphan_blocks=sum(r.orphan_blocks for r in rows),
        runt_routes=sum(r.runt_routes for r in rows),
        help_requests=sum(r.help_requests for r in rows),
        blocks_per_route_avg=round(bpr_weighted / bpr_routes, 2) if bpr_routes else None,
        capacity_util_pct=round(util_weighted / util_routes, 2) if util_routes else None,
        route_minutes_avg=round(minutes_weighted / minutes_timed, 1) if minutes_timed else None,
        truck_days_by_version=versions,
        blocks_per_route_hist=dict(sorted(hist.items(), key=lambda kv: int(kv[0]))),
    )

    return SortMetricsResponse(
        start=start,
        end=end,
        summary=summary,
        series=[SortDailyOut.model_validate(r) for r in rows],
    )
