"""Celery task: async zone-sort pipeline.

Flow:
  1. POST /sort/run → dispatcher dispatches this task, returns task_id
  2. This task calls run_sort() — anchored tote assignment → tier-1 verify → persist zones
  3. Result written to Redis: sort_result:{company_id}:{date}:{task_id} (TTL 24h)
  4. Frontend polls GET /sort/run/status/{task_id} until status != "running"

Redis keys
  sort_running:{company_id}:{date}:{task_id}  — sentinel (TTL 5 min); deleted on completion
  sort_result:{company_id}:{date}:{task_id}   — result JSON (TTL 24h)
  sort_failed:{company_id}:{date}:{task_id}   — error JSON on unhandled exception (TTL 24h)
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date, datetime, timezone
from uuid import UUID

import redis as redis_lib

from app.celery_app import celery_app
from app.core.config import settings
from app.database import SessionLocal
from app.models.notification import Notification
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import RouteClusterCentroid

logger = logging.getLogger(__name__)

_RESULT_TTL = 86_400   # 24 h — matches manifest cache TTL
_RUNNING_TTL = 300     # 5 min sentinel


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def _running_key(company_id: str, sort_date: str, task_id: str) -> str:
    return f"sort_running:{company_id}:{sort_date}:{task_id}"


def _result_key(company_id: str, sort_date: str, task_id: str) -> str:
    return f"sort_result:{company_id}:{sort_date}:{task_id}"


def _failed_key(company_id: str, sort_date: str, task_id: str) -> str:
    return f"sort_failed:{company_id}:{sort_date}:{task_id}"


@celery_app.task(
    name="app.tasks.run_sort_task.run_zone_sort",
    bind=True,
    max_retries=0,
)
def run_zone_sort(
    self,
    company_id: str,
    sort_date: str,
    task_id: str,
    created_by: str,
    created_by_name: str,
) -> dict:
    """Run the full zone-sort pipeline asynchronously.

    Writes result JSON to Redis instead of returning an HTTP response. The
    sort persists directly (ADR-177 — no review gate); out-of-zone freight
    and unplaced totes surface through the station panels, not here.
    """
    r = _redis()
    rk = _running_key(company_id, sort_date, task_id)
    resk = _result_key(company_id, sort_date, task_id)
    failk = _failed_key(company_id, sort_date, task_id)

    # Extend the running sentinel each time the task starts — guards against
    # a worker crash leaving status stuck on "running" forever.
    r.setex(rk, _RUNNING_TTL, "1")

    try:
        from app.services.run_sort import run_sort, SortError

        sort_date_obj = _date.fromisoformat(sort_date)
        company_uuid = UUID(company_id)
        created_by_uuid = UUID(created_by)

        db = SessionLocal()
        try:
            result = run_sort(
                company_id=company_uuid,
                sort_date=sort_date_obj,
                created_by=created_by_uuid,
                created_by_name=created_by_name,
                db=db,
            )
        except SortError as exc:
            _SORT_ERROR_CODES = {
                "no_manifest":    422,
                "no_trucks":      422,
                "no_packages":    422,
                "config_missing": 503,
            }
            payload = {
                "status":      "error",
                "http_status": _SORT_ERROR_CODES.get(exc.code, 400),
                "detail":      exc.detail,
            }
            r.setex(resk, _RESULT_TTL, json.dumps(payload))
            r.delete(rk)
            db.close()
            return payload

        # zones were persisted — stamp sort actor on TruckAssignments
        if result.zones_persisted:
            db.query(TruckAssignment).filter(
                TruckAssignment.company_id == company_uuid,
                TruckAssignment.date == sort_date_obj,
            ).update(
                {
                    "sort_initiated_by": created_by_uuid,
                    "sort_committed_at": datetime.now(timezone.utc),
                },
                synchronize_session="fetch",
            )

        # Write RouteClusterCentroid rows (idempotent: delete stale rows first)
        if result.zones_persisted:
            db.query(RouteClusterCentroid).filter(
                RouteClusterCentroid.company_id == company_uuid,
                RouteClusterCentroid.route_date == sort_date_obj,
            ).delete(synchronize_session="fetch")

            ta_by_truck: dict = {
                ta.truck_id: ta.id
                for ta in db.query(TruckAssignment).filter(
                    TruckAssignment.company_id == company_uuid,
                    TruckAssignment.date == sort_date_obj,
                ).all()
            }

            for assignment in result.proposal.assignments:
                c = assignment.cluster
                db.add(RouteClusterCentroid(
                    company_id          = company_uuid,
                    truck_assignment_id = ta_by_truck.get(assignment.truck_id),
                    route_date          = sort_date_obj,
                    centroid_lat        = c.centroid["lat"],
                    centroid_lng        = c.centroid["lng"],
                    package_count       = len(c.packages),
                    truck_zone_label    = assignment.truck_name,
                ))

        db.commit()

        # Notify the dispatcher who triggered the sort so the SSE stream wakes
        # them up regardless of which page they're on when the task finishes.
        try:
            db.add(Notification(
                company_id  = company_uuid,
                employee_id = created_by_uuid,
                type        = "zone_sort_complete",
                message     = (
                    f"Zone assignment for {sort_date} finished — "
                    f"{len(result.zones_persisted)} zone(s) created."
                ),
            ))
            db.commit()
        except Exception:
            pass  # notification failure must never crash the sort task

        db.close()

        assignments_out = [
            {
                "truck_id":       str(a.truck_id),
                "truck_name":     a.truck_name,
                "anchor_source":  a.anchor_source,
                "workload_score": a.workload_score,
                "package_count":  len(a.cluster.packages),
            }
            for a in result.proposal.assignments
        ]

        payload = {
            "status":            "done",
            "sort_date":         result.sort_date.isoformat(),
            "package_count":     result.package_count,
            "outlier_count":     result.outlier_count,
            "cluster_count":     result.cluster_count,
            "zones_created":     len(result.zones_persisted),
            "assignments":       assignments_out,
            "station_removals":  len(result.analysis.station_removals),
            "ap_flags":          len(result.analysis.ap_flags),
            "unplaced_totes":    len(result.analysis.unplaced_bags),
            "volume_alert":      result.volume_alert,
            "volume_alert_msg":  result.volume_alert_msg,
        }
        r.setex(resk, _RESULT_TTL, json.dumps(payload))
        r.delete(rk)

        logger.info(
            "run_zone_sort complete",
            extra={
                "company_id":    company_id,
                "sort_date":     sort_date,
                "task_id":       task_id,
                "zones_created": len(result.zones_persisted),
            },
        )
        return payload

    except Exception as exc:
        logger.exception(
            "run_zone_sort unhandled exception: %s — company=%s sort_date=%s task_id=%s",
            type(exc).__name__,
            company_id,
            sort_date,
            task_id,
        )
        r.setex(failk, _RESULT_TTL, json.dumps({"detail": "internal_error"}))
        r.delete(rk)
        raise
