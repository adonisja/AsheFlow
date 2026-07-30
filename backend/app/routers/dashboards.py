"""Role-scoped dashboard summary endpoints.

  GET /dashboards/admin/summary       admin
  GET /dashboards/management/summary  management, admin
  GET /dashboards/dispatch/summary    dispatch, management, admin

The trainer endpoint was removed: its roster fields (phases, stuck trainees,
problem areas) are management oversight and moved to /management/summary, and
everything else it returned is already covered better by the mobile trainer
screens (TrainerPerformanceScreen, TrainerHistoryScreen, TrainerTodayScreen).
Field staff are mobile-first.

Read-only aggregations. Every query is company-scoped inside the service layer
(CLAUDE.md Dimension 1).

Imports follow the established router convention — app.database for get_db and
app.api.deps for auth. The previous revision imported a non-existent app.db and
app.auth, which raised ImportError at module load and prevented uvicorn from
starting at all (502 on every route, including /health).
"""

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.schemas.dashboard_summaries import (
    AdminDashboardSummary,
    ManagementDashboardSummary,
    DispatchDashboardSummary,
)
from app.services.dashboard_summaries import (
    get_admin_dashboard_summary,
    get_management_dashboard_summary,
    get_dispatch_dashboard_summary,
)

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

allow_admin      = RoleChecker(["admin"])
allow_management = RoleChecker(["management", "admin"])
allow_dispatch   = RoleChecker(["dispatch", "management", "admin"])


@router.get("/admin/summary", response_model=AdminDashboardSummary)
def admin_summary(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
):
    """Integration freshness (ADP/Flex) + compliance posture.

    Suggested client refresh: 10 minutes — sync state moves slowly.
    """
    return get_admin_dashboard_summary(db, caller.company_id)


@router.get("/management/summary", response_model=ManagementDashboardSummary)
def management_summary(
    period: str = Query("week", pattern="^(today|week|month)$"),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
):
    """Operational efficiency, crew, incidents, fleet.

    Rates are package-denominated. Metrics with no available data return null,
    never 0 — the client must render those as "—".

    Suggested client refresh: 5 minutes.
    """
    return get_management_dashboard_summary(db, caller.company_id, period=period)


@router.get("/dispatch/summary", response_model=DispatchDashboardSummary)
def dispatch_summary(
    target_date: Optional[_date] = Query(
        None, alias="date", description="YYYY-MM-DD; defaults to company-local today"
    ),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    """Live fleet snapshot, action queue, route performance.

    The action queue carries reassignments only — time-off is a manager concern
    owned by ADP, not a dispatch queue.

    Suggested client refresh: 30 seconds.
    """
    return get_dispatch_dashboard_summary(
        db, caller.company_id,
        date_str=target_date.isoformat() if target_date else None,
    )
