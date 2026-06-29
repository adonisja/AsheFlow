"""Celery task: async zone-sort pipeline.

Flow:
  1. POST /sort/run → dispatcher validates overrides, dispatches this task, returns task_id
  2. This task calls run_sort() — DBSCAN cluster → tier-1 verify → persist zones
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
from app.models.audit_log import AuditLog
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
    overrides: list[dict],       # [{bag_id, truck_id}]
    created_by: str,
    created_by_name: str,
    force: bool,
) -> dict:
    """Run the full zone-sort pipeline asynchronously.

    Writes result JSON to Redis instead of returning an HTTP response.
    Tier-1 failures are surfaced as status="tier1_failed" (not an exception)
    so the frontend can render the override UI.
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
        from app.services.tier1_verify import BagOverride

        bag_overrides = [
            BagOverride(bag_id=ov["bag_id"], truck_id=UUID(ov["truck_id"]))
            for ov in overrides
        ]
        sort_date_obj = _date.fromisoformat(sort_date)
        company_uuid = UUID(company_id)
        created_by_uuid = UUID(created_by)

        db = SessionLocal()
        try:
            result = run_sort(
                company_id=company_uuid,
                sort_date=sort_date_obj,
                overrides=bag_overrides,
                created_by=created_by_uuid,
                created_by_name=created_by_name,
                db=db,
                force=force,
            )
        except SortError as exc:
            _SORT_ERROR_CODES = {
                "no_manifest":    422,
                "no_trucks":      422,
                "no_packages":    422,
                "tier1_failed":   409,
                "config_missing": 503,
            }
            http_status = _SORT_ERROR_CODES.get(exc.code, 400)

            if exc.code == "tier1_failed" and exc.verification is not None:
                # Tier-1 failure: surface flagged bags so frontend can render override UI
                flagged = [
                    {
                        "bag_id":             b.bag_id,
                        "inferred_truck_id":  str(b.inferred_truck_id) if b.inferred_truck_id else None,
                        "classification":     b.classification,
                        "total_packages":     b.total_packages,
                        "outside_packages":   b.outside_packages,
                        "outside_pct":        b.outside_pct,
                        "outside_tbas":       b.outside_tbas,
                        "outlier_tbas":       b.outlier_tbas,
                        "suggested_truck_id": str(b.suggested_truck_id) if b.suggested_truck_id else None,
                        "unresolvable":       b.unresolvable,
                    }
                    for b in exc.verification.flagged
                ]
                payload = {
                    "status":       "tier1_failed",
                    "http_status":  http_status,
                    "detail":       exc.detail,
                    "flagged_bags": flagged,
                }
            else:
                payload = {
                    "status":      "error",
                    "http_status": http_status,
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

        if result.was_forced:
            import uuid as _uuid_mod
            db.add(AuditLog(
                company_id   = company_uuid,
                actor_id     = created_by_uuid,
                action_type  = "sort.tier1_force_override",
                target_table = "truck_zones",
                target_id    = _uuid_mod.uuid4(),
                after_snapshot = {
                    "sort_date":     sort_date,
                    "flagged_totes": len(result.verification.flagged),
                    "zones_created": len(result.zones_persisted),
                },
            ))

        db.commit()
        db.close()

        assignments_out = [
            {
                "truck_id":       str(a.truck_id),
                "truck_name":     a.truck_name,
                "match_type":     a.match_type,
                "workload_score": a.workload_score,
                "is_overflow":    a.is_overflow,
                "package_count":  len(a.cluster.packages),
            }
            for a in result.proposal.assignments
        ]

        payload = {
            "status":        "done",
            "sort_date":     result.sort_date.isoformat(),
            "package_count": result.package_count,
            "outlier_count": result.outlier_count,
            "cluster_count": result.cluster_count,
            "tier1_passed":  result.tier1_passed,
            "was_forced":    result.was_forced,
            "zones_created": len(result.zones_persisted),
            "assignments":   assignments_out,
            "flagged_bags":  [],
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
                "tier1_passed":  result.tier1_passed,
            },
        )
        return payload

    except Exception as exc:
        logger.error(
            "run_zone_sort unhandled exception: %s",
            type(exc).__name__,
            extra={"company_id": company_id, "sort_date": sort_date, "task_id": task_id},
        )
        r.setex(failk, _RESULT_TTL, json.dumps({"detail": "internal_error"}))
        r.delete(rk)
        raise
