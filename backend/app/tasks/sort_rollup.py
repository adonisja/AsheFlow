"""Nightly rollup of sort decisions into daily metrics (ADR-273).

Registered in celery_app.py beat_schedule; runs at 03:15 — after the 03:00
invite expiry and before the 03:30 monthly operational purge.

COMPLETED DAYS ONLY
The rollup targets *yesterday* in each company's own timezone, never today.
Today's numbers are in flight, so a row written for today would be wrong within
minutes and would have to be invalidated. Excluding it makes each row immutable
once written — the same rule stats_series (ADR-271) follows, and the reason its
payload is safe to cache with no staleness policy.

WEEKLY / MONTHLY / ANNUAL ARE GROUPINGS, NOT TABLES
Only this daily grain is stored. Three pre-aggregated tables would need three
invalidation paths and would disagree with each other inside a quarter.

IDEMPOTENT
Re-running for a date updates the existing row rather than duplicating it, so a
retried task or a manual backfill is safe.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.local_date import company_today

logger = logging.getLogger(__name__)


def _percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile. Small n by design (routes per truck-day)."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return round(ordered[idx], 1)


def roll_up_company_day(db: Session, company_id: UUID, day: date) -> int:
    """Write/refresh route_sort_daily rows for one company and one date.

    Returns the number of rows written. Groups by truck, because tuning is
    judged per truck-day: trucks differ in crew size, territory, and anchor
    configuration, so pooling them hides the variance that matters.
    """
    from app.models.route_sort_run import RouteSortRun, RouteSortDaily
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment
    from app.models.walker_route import Route
    from app.models.delivery_stop import DeliveryStop

    assignments = (
        db.query(TruckAssignment, Truck)
        .join(Truck, Truck.id == TruckAssignment.truck_id)
        .filter(
            TruckAssignment.company_id == company_id,
            TruckAssignment.date == day,
        )
        .all()
    )
    if not assignments:
        return 0

    written = 0
    for ta, truck in assignments:
        runs = (
            db.query(RouteSortRun)
            .filter(
                RouteSortRun.company_id == company_id,
                RouteSortRun.truck_assignment_id == ta.id,
                RouteSortRun.route_date == day,
            )
            .order_by(RouteSortRun.run_seq)
            .all()
        )
        routes = (
            db.query(Route)
            .filter(
                Route.company_id == company_id,
                Route.truck_assignment_id == ta.id,
                Route.route_date == day,
            )
            .all()
        )
        if not runs and not routes:
            continue

        # The LAST run is the one the crew actually worked; earlier runs are
        # superseded drafts. Their count is still meaningful (re-sort frequency).
        final = runs[-1] if runs else None

        # ── plan vs actual ───────────────────────────────────────────────────
        durations: list[float] = []
        by_class: dict[str, dict] = {}
        for r in routes:
            cls = r.effort_class or "unknown"
            slot = by_class.setdefault(
                cls, {"routes": 0, "packages": 0, "minutes": [], "rts": 0, "missing": 0}
            )
            slot["routes"] += 1
            slot["packages"] += r.package_count or 0
            if r.departed_at and r.returned_at and r.returned_at > r.departed_at:
                mins = (r.returned_at - r.departed_at).total_seconds() / 60.0
                durations.append(mins)
                slot["minutes"].append(mins)

        route_ids = [r.id for r in routes]
        stops = rts_total = missing_total = 0
        if route_ids:
            rows = (
                db.query(DeliveryStop)
                .filter(
                    DeliveryStop.company_id == company_id,
                    DeliveryStop.route_id.in_(route_ids),
                )
                .all()
            )
            stops = len(rows)
            rts_total = sum(s.rts_count or 0 for s in rows)
            missing_total = sum(s.missing_count or 0 for s in rows)
            for s in rows:
                cls = s.effort_class or "unknown"
                if cls in by_class:
                    by_class[cls]["rts"] += s.rts_count or 0
                    by_class[cls]["missing"] += s.missing_count or 0

        # Collapse minute lists to summary stats — the daily row stays slim.
        for slot in by_class.values():
            mins = slot.pop("minutes")
            slot["minutes_avg"] = round(sum(mins) / len(mins), 1) if mins else None
            slot["routes_timed"] = len(mins)

        blocks_per_route_avg = (
            round(sum(len(set(r.block_keys or [])) for r in routes) / len(routes), 2)
            if routes else None
        )

        existing = (
            db.query(RouteSortDaily)
            .filter(
                RouteSortDaily.company_id == company_id,
                RouteSortDaily.truck_id == truck.id,
                RouteSortDaily.route_date == day,
            )
            .first()
        )
        row = existing or RouteSortDaily(
            company_id=company_id, truck_id=truck.id, route_date=day
        )

        row.truck_name = truck.name
        row.algorithm_version = final.algorithm_version if final else None
        row.sort_runs = len(runs)
        row.routes = final.routes_out if final else len(routes)
        row.blocks_split = final.blocks_split if final else 0
        row.orphan_blocks = final.orphan_blocks if final else 0
        row.runt_routes = final.runt_routes if final else 0
        row.blocks_per_route_hist = final.blocks_per_route_hist if final else None
        row.capacity_util_pct = final.capacity_util_pct if final else None
        row.blocks_per_route_avg = blocks_per_route_avg
        row.packages = sum(r.package_count or 0 for r in routes)
        row.stops = stops
        row.route_minutes_avg = (
            round(sum(durations) / len(durations), 1) if durations else None
        )
        row.route_minutes_p90 = _percentile(durations, 0.9)
        row.routes_timed = len(durations)
        row.by_effort_class = by_class or None
        row.rts_total = rts_total
        row.missing_total = missing_total
        row.help_requests = sum(1 for r in routes if r.help_requested_at is not None)

        if existing is None:
            db.add(row)
        written += 1

    return written


@celery_app.task(name="app.tasks.sort_rollup.roll_up_sort_metrics")
def roll_up_sort_metrics(target_date: str | None = None) -> dict:
    """Roll up yesterday's sort metrics for every active company.

    Args:
        target_date: optional ISO date for a manual backfill. When omitted each
            company rolls up ITS OWN yesterday — companies may sit in different
            timezones, so a single server-side date would silently roll up a
            still-running day for some of them.

    Returns a summary dict for observability.
    """
    from app.models.company import Company

    db = SessionLocal()
    counts: dict[str, int] = {}
    try:
        companies = db.query(Company).filter(Company.is_active.is_(True)).all()
        for c in companies:
            try:
                if target_date:
                    day = date.fromisoformat(target_date)
                else:
                    day = company_today(db, c.id) - timedelta(days=1)
                counts[str(c.id)] = roll_up_company_day(db, c.id, day)
            except Exception:
                # One tenant's bad data must not stop the rest.
                logger.exception("sort rollup failed for company %s", c.id)
                counts[str(c.id)] = -1
        db.commit()
        logger.info("roll_up_sort_metrics: %s", counts)
        return {"companies": len(companies), "written": counts}
    except Exception:
        db.rollback()
        logger.exception("roll_up_sort_metrics failed")
        raise
    finally:
        db.close()
