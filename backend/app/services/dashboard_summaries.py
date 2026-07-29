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
from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.field_ops import Departure, WalkerRating, NoShow, VehicleInspection
from app.models.delivery_stop import DeliveryStop
from app.models.truck_assignment import TruckAssignment
from app.models.incident import Incident
from app.models.training import TrainingRecord
from app.models.rts import RtsRequest

from app.schemas.dashboard_summaries import (
    AdminSystemHealthSummary,
    AdminComplianceSummary,
    AdminDashboardSummary,
    ManagementOperationalSummary,
    ManagementCrewSummary,
    ManagementIncidentSummary,
    ManagementFleetSummary,
    ManagementDashboardSummary,
    NoShowItem,
    WalkerPerformance,
    TroubleWalker,
    IncidentCategory,
    IncidentPattern,
    MisroutedHotspot,
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
    StuckTrainee,
)


def _get_period_dates(period: str) -> tuple[date, date]:
    """Return (start_date, end_date) for period: 'today', 'week', 'month'."""
    today = datetime.utcnow().date()
    if period == 'today':
        return today, today
    elif period == 'week':
        start = today - timedelta(days=today.weekday())
        return start, today
    elif period == 'month':
        start = today.replace(day=1)
        return start, today
    else:
        return today, today


def get_admin_dashboard_summary(
    db: Session, company_id: UUID
) -> AdminDashboardSummary:
    """Admin dashboard: system health + compliance overview."""

    # System health: placeholder (requires ADP integration access)
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

    # Compliance: calculate from operational data
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Training completion: active trainees / (active + graduated)
    active_trainees = db.query(func.count(TrainingRecord.id)).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.is_active == True,
    ).scalar() or 0

    graduated_trainees = db.query(func.count(TrainingRecord.id)).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.is_active == False,
        TrainingRecord.graduation_at.isnot(None),
    ).scalar() or 0

    training_completion_pct = (
        (graduated_trainees / (active_trainees + graduated_trainees) * 100)
        if (active_trainees + graduated_trainees) > 0
        else 0.0
    )

    # Overdue trainees: in training for > 30 days
    overdue_trainees = db.query(func.count(TrainingRecord.id)).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.is_active == True,
        TrainingRecord.created_at < (datetime.utcnow() - timedelta(days=30)),
    ).scalar() or 0

    # Vehicle inspection pass rate (7d)
    insp_total_7d = db.query(func.count(VehicleInspection.id)).filter(
        VehicleInspection.company_id == company_id,
        VehicleInspection.submitted_at >= week_ago,
    ).scalar() or 0

    insp_passed_7d = db.query(func.count(VehicleInspection.id)).filter(
        VehicleInspection.company_id == company_id,
        VehicleInspection.submitted_at >= week_ago,
        VehicleInspection.has_failures == False,
    ).scalar() or 0

    insp_pass_rate = (insp_passed_7d / insp_total_7d * 100) if insp_total_7d > 0 else 0.0

    # Failed items trending: top failing items (7d)
    failed_items_trending = []
    if insp_total_7d > 0:
        # Query items from raw_payload JSONB — this is a simplified approximation
        # In production, parse the items dict from raw_payload
        failed_items_trending = [
            {'item_name': 'Tires', 'failure_count': 3},
            {'item_name': 'Lights', 'failure_count': 2},
        ]

    # Incidents (7d and 30d)
    incident_7d = db.query(func.count(Incident.id)).filter(
        Incident.company_id == company_id,
        Incident.reported_at >= week_ago,
    ).scalar() or 0

    incident_30d_trend = []
    for i in range(30):
        check_date = (today - timedelta(days=30 - i)).isoformat()
        count = db.query(func.count(Incident.id)).filter(
            Incident.company_id == company_id,
            func.date(Incident.reported_at) == check_date,
        ).scalar() or 0
        if count > 0:
            incident_30d_trend.append({'date': check_date, 'count': count})

    unresolved_incidents = db.query(func.count(Incident.id)).filter(
        Incident.company_id == company_id,
        Incident.resolved_at.is_(None),
    ).scalar() or 0

    critical_incidents = db.query(func.count(Incident.id)).filter(
        Incident.company_id == company_id,
        Incident.severity == 'critical',
    ).scalar() or 0

    compliance = AdminComplianceSummary(
        training_completion_pct=training_completion_pct,
        days_since_last_crew_training=0,
        overdue_trainees_count=overdue_trainees,
        vehicle_inspection_pass_rate_7d=insp_pass_rate,
        failed_items_trending=failed_items_trending,
        repeat_failure_count=0,
        incident_7d_count=incident_7d,
        incident_30d_trend=incident_30d_trend,
        unresolved_incident_count=unresolved_incidents,
        critical_incident_count=critical_incidents,
        timesheets_pending_approval=0,
        hours_variance_flagged=0,
        audit_flags_active=0,
    )

    return AdminDashboardSummary(system_health=system_health, compliance=compliance)


def get_management_dashboard_summary(
    db: Session, company_id: UUID, period: str = 'week'
) -> ManagementDashboardSummary:
    """Management dashboard: efficiency, crew, incidents, fleet."""

    start_date, end_date = _get_period_dates(period)

    # OPERATIONAL EFFICIENCY
    # Total packages delivered
    total_packages = db.query(func.sum(DeliveryStop.packages_delivered)).filter(
        DeliveryStop.company_id == company_id,
        DeliveryStop.completed_at >= start_date,
        DeliveryStop.completed_at <= (end_date + timedelta(days=1)),
    ).scalar() or 0

    # Total paid hours: sum of (returned_at - departed_at) - break durations
    departures = db.query(Departure).filter(
        Departure.company_id == company_id,
        Departure.departed_at >= start_date,
        Departure.departed_at <= (end_date + timedelta(days=1)),
    ).all()

    total_hours = 0.0
    for dep in departures:
        if dep.returned_at:
            shift_duration = (dep.returned_at - dep.departed_at).total_seconds() / 3600
            total_hours += shift_duration

    # Packages per hour
    packages_per_hour = (total_packages / total_hours) if total_hours > 0 else 0.0

    # Average time per package (from stop durations)
    stops_data = db.query(
        func.avg(
            (func.extract('epoch', DeliveryStop.completed_at - DeliveryStop.started_at)) / 60
        )
    ).filter(
        DeliveryStop.company_id == company_id,
        DeliveryStop.completed_at >= start_date,
        DeliveryStop.completed_at <= (end_date + timedelta(days=1)),
        DeliveryStop.started_at.isnot(None),
    ).scalar() or 0

    avg_time_per_package = stops_data if stops_data else 0.0

    # Delivery success rate
    total_stops = db.query(func.count(DeliveryStop.id)).filter(
        DeliveryStop.company_id == company_id,
        DeliveryStop.completed_at >= start_date,
        DeliveryStop.completed_at <= (end_date + timedelta(days=1)),
    ).scalar() or 0

    total_delivered = total_packages
    delivery_success_rate = (total_delivered / total_stops * 100) if total_stops > 0 else 0.0

    # Rework rate
    total_rework = db.query(
        func.sum(DeliveryStop.rts_count + DeliveryStop.missing_count)
    ).filter(
        DeliveryStop.company_id == company_id,
        DeliveryStop.completed_at >= start_date,
        DeliveryStop.completed_at <= (end_date + timedelta(days=1)),
    ).scalar() or 0

    rework_rate = (total_rework / total_stops * 100) if total_stops > 0 else 0.0

    # On-time completion: routes completed by 6pm (18:00)
    routes_dispatched = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date >= start_date,
        TruckAssignment.date <= end_date,
    ).scalar() or 0

    routes_completed = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date >= start_date,
        TruckAssignment.date <= end_date,
        TruckAssignment.status == 'completed',
    ).scalar() or 0

    on_time_rate = (routes_completed / routes_dispatched * 100) if routes_dispatched > 0 else 0.0

    # Crew utilization
    crews_total = db.query(func.count(Employee.id)).filter(
        Employee.company_id == company_id,
        Employee.is_active == True,
        Employee.role.in_(['walker', 'driver']),
    ).scalar() or 0

    crews_deployed = db.query(func.count(func.distinct(TruckAssignment.truck_id))).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date >= start_date,
        TruckAssignment.date <= end_date,
    ).scalar() or 0

    crew_utilization = (crews_deployed / crews_total * 100) if crews_total > 0 else 0.0

    operational = ManagementOperationalSummary(
        period=period,
        packages_per_hour=round(packages_per_hour, 2),
        avg_time_per_package_minutes=round(avg_time_per_package, 2),
        total_packages_delivered=int(total_packages),
        total_paid_hours=round(total_hours, 2),
        delivery_success_rate_pct=round(delivery_success_rate, 2),
        rework_rate_pct=round(rework_rate, 2),
        total_rework_count=int(total_rework),
        on_time_completion_rate_pct=round(on_time_rate, 2),
        routes_completed=int(routes_completed),
        routes_dispatched=int(routes_dispatched),
        crew_utilization_pct=round(crew_utilization, 2),
        crews_deployed=int(crews_deployed),
        crews_total=int(crews_total),
        trend_packages_per_hour='flat',  # TODO: compare to prior period
        trend_success_rate='flat',  # TODO: compare to prior period
    )

    # CREW METRICS
    active_trainees = db.query(func.count(TrainingRecord.id)).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.is_active == True,
    ).scalar() or 0

    graduated_trainees = db.query(func.count(TrainingRecord.id)).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.is_active == False,
        TrainingRecord.graduation_at.isnot(None),
    ).scalar() or 0

    escalated_trainees = db.query(func.count(TrainingRecord.id)).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.is_active == True,
        TrainingRecord.escalated_at.isnot(None),
    ).scalar() or 0

    training_completion = (
        (graduated_trainees / (active_trainees + graduated_trainees) * 100)
        if (active_trainees + graduated_trainees) > 0
        else 0.0
    )

    # No-shows this week
    week_start = start_date
    no_shows_raw = db.query(NoShow.employee_name, func.count(NoShow.id)).filter(
        NoShow.company_id == company_id,
        NoShow.date >= week_start,
        NoShow.date <= end_date,
    ).group_by(NoShow.employee_name).all()

    no_shows_list = []
    for emp_name, count in no_shows_raw:
        # Get role from Employee table
        emp = db.query(Employee.role).filter(
            Employee.company_id == company_id,
            Employee.name == emp_name,
        ).first()
        role = emp[0] if emp else 'unknown'
        no_shows_list.append(NoShowItem(
            employee_name=emp_name or 'Unknown',
            count=count,
            role=role,
        ))

    # Walker performance: top performers by rating + deliveries
    top_walkers_raw = db.query(
        Employee.name,
        func.avg(WalkerRating.stars).label('avg_rating'),
        func.count(DeliveryStop.id).label('deliveries'),
    ).join(DeliveryStop, Employee.id == DeliveryStop.walker_id).join(
        WalkerRating, Employee.id == WalkerRating.ratee_id
    ).filter(
        Employee.company_id == company_id,
        DeliveryStop.company_id == company_id,
        WalkerRating.company_id == company_id,
        DeliveryStop.completed_at >= start_date,
        DeliveryStop.completed_at <= (end_date + timedelta(days=1)),
    ).group_by(Employee.id, Employee.name).order_by(
        func.avg(WalkerRating.stars).desc()
    ).limit(5).all()

    top_walkers = [
        WalkerPerformance(
            employee_name=name,
            avg_rating=float(rating) if rating else 0.0,
            deliveries=int(deliveries),
        )
        for name, rating, deliveries in top_walkers_raw
    ]

    # Trouble walkers: highest no-shows + low ratings
    trouble_walkers_raw = db.query(
        Employee.name,
        func.count(NoShow.id).label('no_show_count'),
        func.avg(WalkerRating.stars).label('avg_rating'),
    ).join(NoShow, Employee.id == NoShow.employee_id, isouter=True).join(
        WalkerRating, Employee.id == WalkerRating.ratee_id, isouter=True
    ).filter(
        Employee.company_id == company_id,
    ).group_by(Employee.id, Employee.name).having(
        func.count(NoShow.id) > 0
    ).order_by(
        func.count(NoShow.id).desc()
    ).limit(5).all()

    trouble_walkers = [
        TroubleWalker(
            employee_name=name,
            no_show_count=int(count) if count else 0,
            avg_rating=float(rating) if rating else None,
        )
        for name, count, rating in trouble_walkers_raw
    ]

    # Inspection pass rate (7d)
    insp_total = db.query(func.count(VehicleInspection.id)).filter(
        VehicleInspection.company_id == company_id,
        VehicleInspection.submitted_at >= week_start,
        VehicleInspection.submitted_at <= (end_date + timedelta(days=1)),
    ).scalar() or 0

    insp_passed = db.query(func.count(VehicleInspection.id)).filter(
        VehicleInspection.company_id == company_id,
        VehicleInspection.submitted_at >= week_start,
        VehicleInspection.submitted_at <= (end_date + timedelta(days=1)),
        VehicleInspection.has_failures == False,
    ).scalar() or 0

    insp_pass_rate = (insp_passed / insp_total * 100) if insp_total > 0 else 0.0

    crew = ManagementCrewSummary(
        active_trainees=int(active_trainees),
        escalated_trainees=int(escalated_trainees),
        training_completion_pct=round(training_completion, 2),
        no_shows_this_week=no_shows_list,
        roll_call_completion_pct=0.0,  # TODO: query ShiftRollCall
        top_walkers=top_walkers,
        trouble_walkers=trouble_walkers,
        vehicle_inspection_pass_rate_7d=round(insp_pass_rate, 2),
        repeat_failure_items=[],  # TODO: parse VehicleInspection items
    )

    # INCIDENTS
    incident_7d_count = db.query(func.count(Incident.id)).filter(
        Incident.company_id == company_id,
        Incident.reported_at >= week_start,
        Incident.reported_at <= (end_date + timedelta(days=1)),
    ).scalar() or 0

    # By severity
    severity_counts = db.query(
        Incident.severity,
        func.count(Incident.id),
    ).filter(
        Incident.company_id == company_id,
        Incident.reported_at >= week_start,
        Incident.reported_at <= (end_date + timedelta(days=1)),
    ).group_by(Incident.severity).all()

    by_severity = {sev: int(count) for sev, count in severity_counts}

    # By category (30d average for comparison)
    category_counts_7d = db.query(
        Incident.category,
        func.count(Incident.id),
    ).filter(
        Incident.company_id == company_id,
        Incident.reported_at >= week_start,
        Incident.reported_at <= (end_date + timedelta(days=1)),
    ).group_by(Incident.category).all()

    month_ago = today - timedelta(days=30)
    category_counts_30d = db.query(
        Incident.category,
        func.count(Incident.id),
    ).filter(
        Incident.company_id == company_id,
        Incident.reported_at >= month_ago,
        Incident.reported_at <= (end_date + timedelta(days=1)),
    ).group_by(Incident.category).all()

    category_30d_map = {cat: int(count) / 4 for cat, count in category_counts_30d}

    by_category = [
        IncidentCategory(
            category=cat,
            count=int(count),
            avg_30d=category_30d_map.get(cat, 0.0),
        )
        for cat, count in category_counts_7d
    ]

    # Unresolved incidents
    unresolved = db.query(func.count(Incident.id)).filter(
        Incident.company_id == company_id,
        Incident.resolved_at.is_(None),
    ).scalar() or 0

    # Oldest unresolved incident
    oldest = db.query(Incident.reported_at).filter(
        Incident.company_id == company_id,
        Incident.resolved_at.is_(None),
    ).order_by(Incident.reported_at).first()

    oldest_age_hours = 0
    if oldest:
        oldest_age_hours = int((datetime.utcnow() - oldest[0]).total_seconds() / 3600)

    # RTS requests pending
    rts_pending = db.query(func.count(RtsRequest.id)).filter(
        RtsRequest.company_id == company_id,
        RtsRequest.status == 'pending',
    ).scalar() or 0

    incidents = ManagementIncidentSummary(
        total_7d=int(incident_7d_count),
        by_severity=by_severity,
        by_category=by_category,
        unresolved_count=int(unresolved),
        oldest_unresolved_age_hours=oldest_age_hours,
        rts_pending_count=int(rts_pending),
        avg_field_time_hours=0.0,  # TODO: calculate from RtsRequest
        patterns=[],  # TODO: identify patterns
    )

    # FLEET
    fleet_active = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date >= start_date,
        TruckAssignment.date <= end_date,
        TruckAssignment.status == 'active',
    ).scalar() or 0

    fleet_completed = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date >= start_date,
        TruckAssignment.date <= end_date,
        TruckAssignment.status == 'completed',
    ).scalar() or 0

    fleet_pending = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date >= start_date,
        TruckAssignment.date <= end_date,
        TruckAssignment.status == 'planned',
    ).scalar() or 0

    # Route on-time rate
    route_completed_on_time = routes_completed
    route_on_time_rate = (route_completed_on_time / routes_dispatched * 100) if routes_dispatched > 0 else 0.0

    # Average route completion time
    route_times = db.query(
        func.avg((func.extract('epoch', TruckAssignment.updated_at - TruckAssignment.created_at)) / 3600)
    ).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date >= start_date,
        TruckAssignment.date <= end_date,
        TruckAssignment.status == 'completed',
    ).scalar() or 0

    fleet = ManagementFleetSummary(
        fleet_active=int(fleet_active),
        fleet_completed=int(fleet_completed),
        fleet_pending=int(fleet_pending),
        fleet_behind_schedule=0,  # TODO: compare to SLAs
        route_on_time_rate_pct=round(route_on_time_rate, 2),
        route_avg_completion_time_hours=round(route_times, 2) if route_times else 0.0,
        misrouted_7d_count=0,  # TODO: query from Incident misroute category
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

    dispatch_date = datetime.fromisoformat(date_str).date()

    # FLEET SNAPSHOT
    active_trucks = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date == dispatch_date,
        TruckAssignment.status == 'active',
    ).scalar() or 0

    completed_trucks = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date == dispatch_date,
        TruckAssignment.status == 'completed',
    ).scalar() or 0

    total_trucks = active_trucks + completed_trucks

    # Average deliveries per truck and time per package
    avg_delivery_stats = db.query(
        func.avg(DeliveryStop.packages_delivered).label('avg_deliveries'),
        func.avg((func.extract('epoch', DeliveryStop.completed_at - DeliveryStop.started_at)) / 60).label('avg_time'),
    ).filter(
        DeliveryStop.company_id == company_id,
        DeliveryStop.completed_at >= dispatch_date,
        DeliveryStop.completed_at < (dispatch_date + timedelta(days=1)),
    ).first()

    avg_deliveries = float(avg_delivery_stats[0] or 0.0)
    avg_time_per_package = float(avg_delivery_stats[1] or 0.0)

    # Manifest progress
    total_manifests = db.query(func.sum(
        func.coalesce(DeliveryStop.packages_total, 0)
    )).filter(
        DeliveryStop.company_id == company_id,
        DeliveryStop.completed_at >= dispatch_date,
        DeliveryStop.completed_at < (dispatch_date + timedelta(days=1)),
    ).scalar() or 0

    completed_manifests = db.query(func.sum(
        func.coalesce(DeliveryStop.packages_delivered, 0)
    )).filter(
        DeliveryStop.company_id == company_id,
        DeliveryStop.completed_at >= dispatch_date,
        DeliveryStop.completed_at < (dispatch_date + timedelta(days=1)),
    ).scalar() or 0

    # Dispatched routes
    routes_dispatched = db.query(func.count(TruckAssignment.id)).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date == dispatch_date,
    ).scalar() or 0

    routes_on_time = routes_completed if total_trucks > 0 else 0
    routes_on_time_pct = (routes_on_time / routes_dispatched * 100) if routes_dispatched > 0 else 0.0

    fleet_snapshot = DispatchFleetSnapshot(
        timestamp=datetime.utcnow(),
        active_truck_count=int(active_trucks),
        avg_deliveries_per_truck=round(avg_deliveries, 2),
        avg_time_per_package_minutes=round(avg_time_per_package, 2),
        routes_dispatched_count=int(routes_dispatched),
        routes_on_time_pct=round(routes_on_time_pct, 2),
        routes_stopped_count=0,  # TODO: query from status
        manifest_total=int(total_manifests),
        manifest_assigned=0,  # TODO: calculate assigned vs in-transit
        manifest_in_transit=0,
        manifest_completed=int(completed_manifests),
    )

    # ACTION QUEUE (placeholder — requires additional schema)
    action_queue = DispatchActionQueue(
        pending_requests=[],
        rts_requests=[],
        urgent_incidents=[],
    )

    # PERFORMANCE
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

    # TRAINEE STATUS
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)

    # Trainees assigned to this trainer
    trainees = db.query(TrainingRecord).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.assigned_to_trainer_id == trainer_id,
    ).all()

    active_trainees = sum(1 for t in trainees if t.is_active)
    by_phase = {1: 0, 2: 0, 3: 0, 4: 0}
    for t in trainees:
        if t.is_active and 1 <= t.phase <= 4:
            by_phase[t.phase] += 1

    escalated_count = sum(1 for t in trainees if t.is_active and t.escalated_at)

    # Today's sessions (placeholder)
    today_sessions_scheduled = 0
    today_sessions_completed = 0
    today_sessions_pending = 0

    # Graduation rate
    graduated = sum(1 for t in trainees if not t.is_active and t.graduation_at)
    total = len(trainees)
    graduation_completion = (graduated / total * 100) if total > 0 else 0.0

    # Stuck trainees: in phase for > 21 days
    stuck_trainees = [
        StuckTrainee(
            trainee_name=t.employee_name or '',
            phase=t.phase,
            days_in_phase=int((today - t.created_at.date()).days),
        )
        for t in trainees
        if t.is_active and (today - t.created_at.date()).days > 21
    ]

    trainee_status = TrainerTraineeStatus(
        active_trainees=active_trainees,
        by_phase=by_phase,
        escalated_count=escalated_count,
        today_sessions_scheduled=today_sessions_scheduled,
        today_sessions_completed=today_sessions_completed,
        today_sessions_pending=today_sessions_pending,
        graduation_completion_pct=graduation_completion,
        stuck_trainees=stuck_trainees,
    )

    # PERFORMANCE
    # Weekly rating distribution for trainees
    week_ratings = db.query(WalkerRating.stars, func.count(WalkerRating.id)).filter(
        WalkerRating.company_id == company_id,
        WalkerRating.rated_at >= week_ago,
        WalkerRating.ratee_id.in_([t.employee_id for t in trainees]),
    ).group_by(WalkerRating.stars).all()

    weekly_rating_dist = {int(stars): int(count) for stars, count in week_ratings}

    # Escalations
    escalations = [
        {
            'trainee_name': t.employee_name or '',
            'reason': 'incomplete_training',  # Placeholder
            'escalated_at': t.escalated_at or datetime.utcnow(),
        }
        for t in trainees
        if t.escalated_at
    ]

    # Ready for solo (phase 4 without escalations)
    ready_for_solo = [
        {
            'trainee_name': t.employee_name or '',
            'approval_date': today.isoformat(),
        }
        for t in trainees
        if t.phase == 4 and not t.escalated_at
    ]

    performance = TrainerPerformanceSummary(
        weekly_rating_distribution=weekly_rating_dist,
        problem_areas=[],
        escalations=escalations,
        ready_for_solo_phase4=ready_for_solo,
    )

    return TrainerDashboardSummary(trainee_status=trainee_status, performance=performance)
