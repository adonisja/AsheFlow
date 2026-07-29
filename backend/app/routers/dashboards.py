"""Dashboard API endpoints — role-scoped summary data for frontend dashboards.

Each endpoint returns pre-calculated summary DTOs:
- /admin/summary — AdminDashboardSummary (admin only)
- /management/summary — ManagementDashboardSummary (management only)
- /dispatch/summary — DispatchDashboardSummary (dispatch only)
- /trainer/summary — TrainerDashboardSummary (trainer only)

All endpoints:
- Validate role permissions via RoleChecker
- Scope queries to caller's company_id
- Return cached DTOs (refresh every 2-10 minutes depending on metric velocity)
- Handle errors gracefully (return defaults on query failure)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.db import get_db
from app.schemas.dashboard_summaries import (
    AdminDashboardSummary,
    ManagementDashboardSummary,
    DispatchDashboardSummary,
    TrainerDashboardSummary,
)
from app.services.dashboard_summaries import (
    get_admin_dashboard_summary,
    get_management_dashboard_summary,
    get_dispatch_dashboard_summary,
    get_trainer_dashboard_summary,
)
from app.auth import RoleChecker, get_current_user, CurrentUser

router = APIRouter(prefix='/dashboards', tags=['dashboards'])


@router.get('/admin/summary', response_model=AdminDashboardSummary)
def get_admin_summary(
    db: Session = Depends(get_db),
    caller: CurrentUser = Depends(get_current_user),
    _: None = Depends(RoleChecker(['admin'])),
) -> AdminDashboardSummary:
    """
    Admin dashboard summary: system health + compliance.

    Returns:
    - System health (ADP/Flex sync status, DB health, active alerts)
    - Compliance metrics (training %, inspections, incidents, payroll flags)

    Access: admin only
    Caching: 10 minutes (integration status changes infrequently)
    """
    return get_admin_dashboard_summary(db, caller.company_id)


@router.get('/management/summary', response_model=ManagementDashboardSummary)
def get_management_summary(
    period: str = Query('week', regex='^(today|week|month)$'),
    db: Session = Depends(get_db),
    caller: CurrentUser = Depends(get_current_user),
    _: None = Depends(RoleChecker(['management', 'admin'])),
) -> ManagementDashboardSummary:
    """
    Management dashboard summary: operational efficiency, crew, incidents, fleet.

    Query parameters:
    - period: 'today', 'week', or 'month' (default: week)

    Returns:
    - Operational efficiency (packages/hour, success rate, rework %, on-time %)
    - Crew metrics (trainees, no-shows, walker performance, inspections)
    - Incident summary (7d/30d trends, unresolved, RTS queue)
    - Fleet status (active/completed/pending, utilization, misroutes)

    Access: management, admin
    Caching: 5 minutes (payroll/crew data doesn't update minute-by-minute)
    """
    return get_management_dashboard_summary(db, caller.company_id, period=period)


@router.get('/dispatch/summary', response_model=DispatchDashboardSummary)
def get_dispatch_summary(
    date: str = Query(None, description='YYYY-MM-DD; defaults to today'),
    db: Session = Depends(get_db),
    caller: CurrentUser = Depends(get_current_user),
    _: None = Depends(RoleChecker(['dispatch', 'management', 'admin'])),
) -> DispatchDashboardSummary:
    """
    Dispatch dashboard summary: real-time operations.

    Query parameters:
    - date: YYYY-MM-DD for specific dispatch date (default: today)

    Returns:
    - Fleet snapshot (active trucks, deliveries, manifest progress)
    - Action queue (pending approvals aged, RTS requests, urgent incidents)
    - Performance (slowest routes, crew variance, optimization suggestions)

    Access: dispatch, management, admin
    Caching: 30 seconds (real-time ops; fleet status changes frequently)
    """
    return get_dispatch_dashboard_summary(db, caller.company_id, date_str=date)


@router.get('/trainer/summary', response_model=TrainerDashboardSummary)
def get_trainer_summary(
    db: Session = Depends(get_db),
    caller: CurrentUser = Depends(get_current_user),
    _: None = Depends(RoleChecker(['trainer', 'management', 'admin'])),
) -> TrainerDashboardSummary:
    """
    Trainer dashboard summary: trainee progress & performance.

    Returns trainee data scoped to caller's trainee roster:
    - Trainee status (active by phase, escalations, graduation %, stuck trainees)
    - Performance (weekly ratings, problem areas, escalation reasons, ready-for-solo)

    Access: trainer, management, admin
    Caching: 10 minutes (training status changes via explicit actions, not polling)
    """
    return get_trainer_dashboard_summary(db, caller.company_id, trainer_id=caller.id)
