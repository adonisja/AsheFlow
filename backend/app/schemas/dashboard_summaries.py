from datetime import datetime, date
from uuid import UUID
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict


# ── Admin Dashboard Schemas ─────────────────────────────────────────────────────

class AlertItem(BaseModel):
    severity: str  # 'critical' | 'warning'
    message: str
    since: datetime


class DbHealth(BaseModel):
    replication_lag_ms: int
    backup_ok: bool
    migration_active: bool


class AdminSystemHealthSummary(BaseModel):
    adp_last_sync: datetime
    adp_status: str  # 'connected' | 'stale' | 'error'
    adp_employee_count: int
    adp_sync_failures_this_week: int

    flex_last_sync: datetime
    flex_manifest_count: int
    flex_misroute_count: int
    flex_data_freshness_hours: int

    db_health: DbHealth
    active_alerts: List[AlertItem]

    model_config = ConfigDict(from_attributes=True)


class FailureItem(BaseModel):
    item_name: str
    failure_count: int


class IncidentTrendItem(BaseModel):
    date: date
    count: int


class AdminComplianceSummary(BaseModel):
    training_completion_pct: float
    days_since_last_crew_training: int
    overdue_trainees_count: int

    vehicle_inspection_pass_rate_7d: float
    failed_items_trending: List[FailureItem]
    repeat_failure_count: int

    incident_7d_count: int
    incident_30d_trend: List[IncidentTrendItem]
    unresolved_incident_count: int
    critical_incident_count: int

    timesheets_pending_approval: int
    hours_variance_flagged: int
    audit_flags_active: int

    model_config = ConfigDict(from_attributes=True)


class AdminDashboardSummary(BaseModel):
    system_health: AdminSystemHealthSummary
    compliance: AdminComplianceSummary

    model_config = ConfigDict(from_attributes=True)


# ── Management Dashboard Schemas ────────────────────────────────────────────────

class ManagementOperationalSummary(BaseModel):
    period: str  # 'today' | 'week' | 'month'

    packages_per_hour: float
    avg_time_per_package_minutes: float
    total_packages_delivered: int
    total_paid_hours: float

    delivery_success_rate_pct: float
    rework_rate_pct: float
    total_rework_count: int

    on_time_completion_rate_pct: float
    routes_completed: int
    routes_dispatched: int

    crew_utilization_pct: float
    crews_deployed: int
    crews_total: int

    trend_packages_per_hour: str  # 'up' | 'down' | 'flat'
    trend_success_rate: str  # 'up' | 'down' | 'flat'

    model_config = ConfigDict(from_attributes=True)


class NoShowItem(BaseModel):
    employee_name: str
    count: int
    role: str


class WalkerPerformance(BaseModel):
    employee_name: str
    avg_rating: float
    deliveries: int


class TroubleWalker(BaseModel):
    employee_name: str
    no_show_count: int
    avg_rating: Optional[float] = None


class ManagementCrewSummary(BaseModel):
    active_trainees: int
    escalated_trainees: int
    training_completion_pct: float

    no_shows_this_week: List[NoShowItem]
    roll_call_completion_pct: float

    top_walkers: List[WalkerPerformance]
    trouble_walkers: List[TroubleWalker]

    vehicle_inspection_pass_rate_7d: float
    repeat_failure_items: List[FailureItem]

    model_config = ConfigDict(from_attributes=True)


class IncidentCategory(BaseModel):
    category: str
    count: int
    avg_30d: float


class IncidentPattern(BaseModel):
    route_id: Optional[str] = None
    category: str
    frequency: int


class ManagementIncidentSummary(BaseModel):
    total_7d: int
    by_severity: Dict[str, int]
    by_category: List[IncidentCategory]

    unresolved_count: int
    oldest_unresolved_age_hours: int

    rts_pending_count: int
    avg_field_time_hours: float
    patterns: List[IncidentPattern]

    model_config = ConfigDict(from_attributes=True)


class MisroutedHotspot(BaseModel):
    zone: Optional[str] = None
    address: Optional[str] = None
    count: int


class ManagementFleetSummary(BaseModel):
    fleet_active: int
    fleet_completed: int
    fleet_pending: int
    fleet_behind_schedule: int

    route_on_time_rate_pct: float
    route_avg_completion_time_hours: float

    misrouted_7d_count: int
    misrouted_pct: float
    misrouted_hotspots: List[MisroutedHotspot]

    model_config = ConfigDict(from_attributes=True)


class ManagementDashboardSummary(BaseModel):
    operational: ManagementOperationalSummary
    crew: ManagementCrewSummary
    incidents: ManagementIncidentSummary
    fleet: ManagementFleetSummary

    model_config = ConfigDict(from_attributes=True)


# ── Dispatch Dashboard Schemas ──────────────────────────────────────────────────

class DispatchFleetSnapshot(BaseModel):
    timestamp: datetime
    active_truck_count: int
    avg_deliveries_per_truck: float
    avg_time_per_package_minutes: float

    routes_dispatched_count: int
    routes_on_time_pct: float
    routes_stopped_count: int

    manifest_total: int
    manifest_assigned: int
    manifest_in_transit: int
    manifest_completed: int

    model_config = ConfigDict(from_attributes=True)


class DispatchPendingRequest(BaseModel):
    id: str
    type: str  # 'time_off' | 'off_day' | 'reassignment'
    employee_name: str
    date: date
    submitted_at: datetime
    age_minutes: int
    is_urgent: bool


class DispatchRtsRequest(BaseModel):
    driver_id: str
    driver_name: str
    route_id: str
    completion_pct: float
    time_in_field_hours: float
    packages_remaining: int
    requested_at: datetime


class DispatchUrgentIncident(BaseModel):
    incident_id: str
    severity: str
    category: str
    route_id: Optional[str] = None
    reported_at: datetime
    age_minutes: int


class DispatchActionQueue(BaseModel):
    pending_requests: List[DispatchPendingRequest]
    rts_requests: List[DispatchRtsRequest]
    urgent_incidents: List[DispatchUrgentIncident]

    model_config = ConfigDict(from_attributes=True)


class SlowestRoute(BaseModel):
    route_id: str
    actual_time_hours: float
    expected_time_hours: float
    variance_pct: float


class CrewPerformance(BaseModel):
    crew_id: str
    driver_name: str
    packages_per_hour: float


class OptimizationSuggestion(BaseModel):
    type: str
    impact: str
    action: str


class DispatchPerformanceSummary(BaseModel):
    slowest_routes: List[SlowestRoute]

    fastest_crew: Optional[CrewPerformance] = None
    slowest_crew: Optional[CrewPerformance] = None
    crew_variance_pct: float

    optimization_suggestions: List[OptimizationSuggestion]

    model_config = ConfigDict(from_attributes=True)


class DispatchDashboardSummary(BaseModel):
    fleet_snapshot: DispatchFleetSnapshot
    action_queue: DispatchActionQueue
    performance: DispatchPerformanceSummary

    model_config = ConfigDict(from_attributes=True)


# ── Trainer Dashboard Schemas ───────────────────────────────────────────────────

class StuckTrainee(BaseModel):
    trainee_name: str
    phase: int
    days_in_phase: int


class TrainerTraineeStatus(BaseModel):
    active_trainees: int
    by_phase: Dict[int, int]
    escalated_count: int

    today_sessions_scheduled: int
    today_sessions_completed: int
    today_sessions_pending: int

    graduation_completion_pct: float
    stuck_trainees: List[StuckTrainee]

    model_config = ConfigDict(from_attributes=True)


class ProblemArea(BaseModel):
    category: str
    trainee_name: str
    count: int


class TraineeEscalation(BaseModel):
    trainee_name: str
    reason: str  # 'low_rating' | 'no_shows' | 'field_behavior' | 'incomplete_training'
    escalated_at: datetime


class ReadyForSolo(BaseModel):
    trainee_name: str
    approval_date: date


class TrainerPerformanceSummary(BaseModel):
    weekly_rating_distribution: Dict[int, int]
    problem_areas: List[ProblemArea]

    escalations: List[TraineeEscalation]

    ready_for_solo_phase4: List[ReadyForSolo]

    model_config = ConfigDict(from_attributes=True)


class TrainerDashboardSummary(BaseModel):
    trainee_status: TrainerTraineeStatus
    performance: TrainerPerformanceSummary

    model_config = ConfigDict(from_attributes=True)
