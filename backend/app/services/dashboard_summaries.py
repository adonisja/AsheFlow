"""Dashboard summary calculations — converts operational data into KPI DTOs.

Each summary function:
1. Queries operational tables for the given company & period
2. Derives metrics from timestamps, counts, and relationships
3. Returns a DTO ready for frontend display

All queries are scoped by company_id to enforce multi-tenancy.
All timestamps use UTC; frontend converts to company timezone.
"""

from datetime import datetime, timedelta, date
from uuid import UUID
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.field_ops import Departure, WalkerRating, NoShow
from app.models.delivery_stop import DeliveryStop
from app.models.truck_assignment import TruckAssignment
from app.models.incident import Incident
from app.models.training import TrainingRecord
from app.models.field_ops import VehicleInspection
from app.models.shift_roll_call import ShiftRollCall

from app.schemas.dashboard_summaries import (
    AdminSystemHealthSummary,
    AdminComplianceSummary,
    AdminDashboardSummary,
    ManagementOperationalSummary,
    ManagementCrewSummary,
    ManagementIncidentSummary,
    ManagementFleetSummary,
    ManagementDashboardSummary,
    DispatchFleetSnapshot,
    DispatchActionQueue,
    DispatchPendingRequest,
    DispatchRtsRequest,
    DispatchUrgentIncident,
    DispatchPerformanceSummary,
    DispatchDashboardSummary,
    TrainerTraineeStatus,
    TrainerPerformanceSummary,
    TrainerDashboardSummary,
)


def get_admin_dashboard_summary(
    db: Session, company_id: UUID
) -> AdminDashboardSummary:
    """Admin dashboard: system health + compliance overview."""

    # Placeholder implementations — replaced with actual queries in Phase 2
    system_health = AdminSystemHealthSummary(
        adp_last_sync=datetime.utcnow(),
        adp_status='connected',
        adp_employee_count=0,
        adp_sync_failures_this_week=0,
        flex_last_sync=datetime.utcnow(),
        flex_manifest_count=0,
        flex_misroute_count=0,
        flex_data_freshness_hours=0,
        db_health={'replication_lag_ms': 0, 'backup_ok': True, 'migration_active': False},
        active_alerts=[],
    )

    compliance = AdminComplianceSummary(
        training_completion_pct=0.0,
        days_since_last_crew_training=0,
        overdue_trainees_count=0,
        vehicle_inspection_pass_rate_7d=0.0,
        failed_items_trending=[],
        repeat_failure_count=0,
        incident_7d_count=0,
        incident_30d_trend=[],
        unresolved_incident_count=0,
        critical_incident_count=0,
        timesheets_pending_approval=0,
        hours_variance_flagged=0,
        audit_flags_active=0,
    )

    return AdminDashboardSummary(system_health=system_health, compliance=compliance)


def get_management_dashboard_summary(
    db: Session, company_id: UUID, period: str = 'week'
) -> ManagementDashboardSummary:
    """Management dashboard: efficiency, crew, incidents, fleet."""

    # Placeholder implementations — replaced with actual queries in Phase 2
    operational = ManagementOperationalSummary(
        period=period,
        packages_per_hour=0.0,
        avg_time_per_package_minutes=0.0,
        total_packages_delivered=0,
        total_paid_hours=0.0,
        delivery_success_rate_pct=0.0,
        rework_rate_pct=0.0,
        total_rework_count=0,
        on_time_completion_rate_pct=0.0,
        routes_completed=0,
        routes_dispatched=0,
        crew_utilization_pct=0.0,
        crews_deployed=0,
        crews_total=0,
        trend_packages_per_hour='flat',
        trend_success_rate='flat',
    )

    crew = ManagementCrewSummary(
        active_trainees=0,
        escalated_trainees=0,
        training_completion_pct=0.0,
        no_shows_this_week=[],
        roll_call_completion_pct=0.0,
        top_walkers=[],
        trouble_walkers=[],
        vehicle_inspection_pass_rate_7d=0.0,
        repeat_failure_items=[],
    )

    incidents = ManagementIncidentSummary(
        total_7d=0,
        by_severity={},
        by_category=[],
        unresolved_count=0,
        oldest_unresolved_age_hours=0,
        rts_pending_count=0,
        avg_field_time_hours=0.0,
        patterns=[],
    )

    fleet = ManagementFleetSummary(
        fleet_active=0,
        fleet_completed=0,
        fleet_pending=0,
        fleet_behind_schedule=0,
        route_on_time_rate_pct=0.0,
        route_avg_completion_time_hours=0.0,
        misrouted_7d_count=0,
        misrouted_pct=0.0,
        misrouted_hotspots=[],
    )

    return ManagementDashboardSummary(
        operational=operational, crew=crew, incidents=incidents, fleet=fleet
    )


def get_dispatch_dashboard_summary(
    db: Session, company_id: UUID, date_str: str = None
) -> DispatchDashboardSummary:
    """Dispatch dashboard: real-time fleet snapshot + action queue."""

    if not date_str:
        date_str = datetime.utcnow().date().isoformat()

    # Placeholder implementations — replaced with actual queries in Phase 2
    fleet_snapshot = DispatchFleetSnapshot(
        timestamp=datetime.utcnow(),
        active_truck_count=0,
        avg_deliveries_per_truck=0.0,
        avg_time_per_package_minutes=0.0,
        routes_dispatched_count=0,
        routes_on_time_pct=0.0,
        routes_stopped_count=0,
        manifest_total=0,
        manifest_assigned=0,
        manifest_in_transit=0,
        manifest_completed=0,
    )

    action_queue = DispatchActionQueue(
        pending_requests=[],
        rts_requests=[],
        urgent_incidents=[],
    )

    performance = DispatchPerformanceSummary(
        slowest_routes=[],
        fastest_crew=None,
        slowest_crew=None,
        crew_variance_pct=0.0,
        optimization_suggestions=[],
    )

    return DispatchDashboardSummary(
        fleet_snapshot=fleet_snapshot,
        action_queue=action_queue,
        performance=performance,
    )


def get_trainer_dashboard_summary(
    db: Session, company_id: UUID, trainer_id: UUID
) -> TrainerDashboardSummary:
    """Trainer dashboard: trainee roster + performance."""

    # Placeholder implementations — replaced with actual queries in Phase 2
    trainee_status = TrainerTraineeStatus(
        active_trainees=0,
        by_phase={1: 0, 2: 0, 3: 0, 4: 0},
        escalated_count=0,
        today_sessions_scheduled=0,
        today_sessions_completed=0,
        today_sessions_pending=0,
        graduation_completion_pct=0.0,
        stuck_trainees=[],
    )

    performance = TrainerPerformanceSummary(
        weekly_rating_distribution={},
        problem_areas=[],
        escalations=[],
        ready_for_solo_phase4=[],
    )

    return TrainerDashboardSummary(trainee_status=trainee_status, performance=performance)
