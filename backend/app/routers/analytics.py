"""Operations analytics router.

Four read-only endpoints used by the admin/management analytics dashboard:

1. GET /analytics/dispatch-fill-rate  — algo vs manual placement breakdown
2. GET /analytics/trainer-load        — active trainee count per trainer
3. GET /analytics/ban-override-freq   — ban override events per week
4. GET /analytics/confirmation-times  — median / p90 response time per role

All endpoints are restricted to dispatch, management, and admin.
"""

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee as EmployeeModel
from app.models.assignment_member import AssignmentMember
from app.models.truck_assignment import TruckAssignment
from app.models.dispatch_confirmation import DispatchConfirmation
from app.models.training import TrainingRecord
from app.models.notification import Notification

router = APIRouter(prefix="/analytics", tags=["analytics"])

allow_mgmt = RoleChecker(["dispatch", "management", "admin"])


# ---------------------------------------------------------------------------
# 1. Dispatch fill rate
# ---------------------------------------------------------------------------

@router.get("/dispatch-fill-rate")
def get_dispatch_fill_rate(
    start_date: date = Query(..., description="Start of range (inclusive)"),
    end_date:   date = Query(..., description="End of range (inclusive)"),
    caller: EmployeeModel = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(
            TruckAssignment.date,
            func.count(AssignmentMember.id).label("total"),
            func.sum(case((AssignmentMember.is_manual == False, 1), else_=0)).label("algo"),
            func.sum(case((AssignmentMember.is_manual == True,  1), else_=0)).label("manual"),
        )
        .join(AssignmentMember, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date >= start_date,
            TruckAssignment.date <= end_date,
        )
        .group_by(TruckAssignment.date)
        .order_by(TruckAssignment.date)
        .all()
    )

    by_date = []
    total_slots = algo_slots = manual_slots = 0
    for row in rows:
        algo   = int(row.algo   or 0)
        manual = int(row.manual or 0)
        total  = int(row.total  or 0)
        by_date.append({"date": str(row.date), "total": total, "algo": algo, "manual": manual})
        total_slots  += total
        algo_slots   += algo
        manual_slots += manual

    algo_pct = round(algo_slots / total_slots * 100, 1) if total_slots else 0.0

    return {
        "start_date": str(start_date),
        "end_date":   str(end_date),
        "summary": {
            "total_slots":  total_slots,
            "algo_slots":   algo_slots,
            "manual_slots": manual_slots,
            "algo_pct":     algo_pct,
        },
        "by_date": by_date,
    }


# ---------------------------------------------------------------------------
# 2. Trainer load balancing
# ---------------------------------------------------------------------------

@router.get("/trainer-load")
def get_trainer_load(
    caller: EmployeeModel = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    open_records = (
        db.query(TrainingRecord)
        .filter(
            TrainingRecord.company_id == caller.company_id,
            TrainingRecord.submitted_at.is_(None),
            TrainingRecord.trainer_id.isnot(None),
        )
        .all()
    )

    trainer_ids = list({r.trainer_id for r in open_records})
    trainers = {
        e.id: e
        for e in db.query(EmployeeModel).filter(EmployeeModel.id.in_(trainer_ids), EmployeeModel.company_id == caller.company_id).all()
    }

    # Aggregate
    load: dict[UUID, dict] = {}
    for rec in open_records:
        tid = rec.trainer_id
        if tid not in load:
            t = trainers.get(tid)
            load[tid] = {
                "trainer_id":      str(tid),
                "trainer_name":    t.name if t else str(tid),
                "active_trainees": 0,
                "phases":          {"1": 0, "2": 0, "3": 0, "4": 0},
            }
        load[tid]["active_trainees"] += 1
        phase_key = str(rec.current_day_number) if rec.current_day_number in (1, 2, 3, 4) else "1"
        load[tid]["phases"][phase_key] += 1

    return sorted(load.values(), key=lambda x: x["active_trainees"], reverse=True)


# ---------------------------------------------------------------------------
# 3. Ban override frequency
# ---------------------------------------------------------------------------

@router.get("/ban-override-freq")
def get_ban_override_freq(
    weeks: int = Query(default=8, ge=1, le=52, description="Number of past weeks to include"),
    caller: EmployeeModel = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    today = date.today()
    range_start = today - timedelta(weeks=weeks)

    rows = (
        db.query(Notification)
        .filter(
            Notification.company_id == caller.company_id,
            Notification.type == "ban_override_reassignment",
            Notification.created_at >= datetime.combine(range_start, datetime.min.time()).replace(tzinfo=timezone.utc),
        )
        .all()
    )

    # Bucket by ISO week start (Monday)
    week_counts: dict[date, int] = {}
    for notif in rows:
        event_date = notif.created_at.date() if notif.created_at else today
        # Roll back to Monday of that week
        week_start = event_date - timedelta(days=event_date.weekday())
        week_counts[week_start] = week_counts.get(week_start, 0) + 1

    # Build a complete week series (0 for weeks with no events)
    by_week = []
    for i in range(weeks):
        ws = today - timedelta(weeks=weeks - 1 - i)
        ws = ws - timedelta(days=ws.weekday())
        by_week.append({"week_start": str(ws), "count": week_counts.get(ws, 0)})

    return {
        "weeks":           weeks,
        "total_overrides": sum(week_counts.values()),
        "by_week":         by_week,
    }


# ---------------------------------------------------------------------------
# 4. Confirmation response time
# ---------------------------------------------------------------------------

@router.get("/confirmation-times")
def get_confirmation_times(
    start_date: date = Query(..., description="Start of range (inclusive)"),
    end_date:   date = Query(..., description="End of range (inclusive)"),
    caller: EmployeeModel = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DispatchConfirmation, EmployeeModel)
        .join(EmployeeModel, DispatchConfirmation.employee_id == EmployeeModel.id)
        .filter(
            DispatchConfirmation.company_id == caller.company_id,
            DispatchConfirmation.date >= start_date,
            DispatchConfirmation.date <= end_date,
            DispatchConfirmation.confirmed_at.isnot(None),
            DispatchConfirmation.status.in_(["confirmed", "declined"]),
            DispatchConfirmation.created_at.isnot(None),
        )
        .all()
    )

    def _minutes(conf: DispatchConfirmation) -> float:
        delta = conf.confirmed_at - conf.created_at
        return max(delta.total_seconds() / 60, 0)

    def _percentile(data: list[float], pct: int) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * pct / 100)
        return round(sorted_data[min(idx, len(sorted_data) - 1)], 1)

    # Bucket by employee role
    by_role: dict[str, list[float]] = {}
    all_times: list[float] = []

    for conf, emp in rows:
        mins = _minutes(conf)
        all_times.append(mins)
        role = emp.role  # type: ignore[union-attr]
        by_role.setdefault(role, []).append(mins)

    overall = {
        "median_minutes":  round(median(all_times), 1) if all_times else 0.0,
        "p90_minutes":     _percentile(all_times, 90),
        "total_responses": len(all_times),
    }

    by_role_out = []
    for role, times in sorted(by_role.items()):
        by_role_out.append({
            "role":           role,
            "median_minutes": round(median(times), 1) if times else 0.0,
            "p90_minutes":    _percentile(times, 90),
            "count":          len(times),
        })

    return {
        "start_date": str(start_date),
        "end_date":   str(end_date),
        "overall":    overall,
        "by_role":    by_role_out,
    }
