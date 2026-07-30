"""Dashboard summary schemas.

Every field here is backed by a real column. Fields that had no source were
DELETED rather than shipped as zeros or placeholders — see
docs/DASHBOARD_FIELD_AVAILABILITY_MAP.md for the per-field audit and the
reasoning behind each removal.

Nullable metrics (Optional[...]) mean "not computable for this company/period"
— e.g. on-time needs CompanyConfig.shift_end, which is nullable. The frontend
renders those as "—", never as 0.

Definitions locked 2026-07-29:
  on-time   : Route.returned_at <= CompanyConfig.shift_end (null if unset)
  graduated : employee has training records but role is no longer 'trainee'
  baseline  : historical mean minutes-per-package, scaled by package_count
  trainer   : TrainingTask signals + phase-4 scores; trainer_rating is
              trainee->trainer feedback and is labelled as such
"""

from datetime import datetime, date
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict


# ── shared ────────────────────────────────────────────────────────────────────

class FailureItem(BaseModel):
    item_name: str
    failure_count: int


class IncidentTrendItem(BaseModel):
    date: date
    count: int


# ── Admin ─────────────────────────────────────────────────────────────────────

class AdminSystemHealthSummary(BaseModel):
    """ADP/Flex integration freshness.

    DELETED: db_health (needs infra probes — Phase 2 returned hardcoded
    {0, True, False}); active_alerts (no alert store exists);
    adp_sync_failures_this_week (no failure-count table).
    """
    adp_configured: bool
    adp_enabled: bool
    adp_last_employee_sync: Optional[datetime] = None
    adp_last_timecard_sync: Optional[datetime] = None
    adp_status: str                      # connected | stale | never_synced | disabled | not_configured
    adp_verified_employee_count: int

    flex_last_upload: Optional[datetime] = None
    flex_data_freshness_hours: Optional[float] = None
    manifest_count_today: int
    unresolved_misroute_count: int

    model_config = ConfigDict(from_attributes=True)


class AdminComplianceSummary(BaseModel):
    """DELETED: timesheets_pending_approval / hours_variance_flagged (approval
    lives in ADP, not AsheFlow); audit_flags_active (audit_logs has no flag
    concept); repeat_failure_count (subsumed by failed_items_trending).
    """
    graduation_completion_pct: Optional[float] = None
    active_trainee_count: int
    escalated_trainee_count: int
    days_since_last_training_record: Optional[int] = None

    vehicle_inspection_pass_rate_7d: Optional[float] = None
    inspections_submitted_7d: int
    failed_items_trending: List[FailureItem]

    incident_7d_count: int
    incident_30d_trend: List[IncidentTrendItem]
    unresolved_incident_count: int
    critical_incident_count: int

    model_config = ConfigDict(from_attributes=True)


class AdminDashboardSummary(BaseModel):
    system_health: AdminSystemHealthSummary
    compliance: AdminComplianceSummary
    model_config = ConfigDict(from_attributes=True)


# ── Management ────────────────────────────────────────────────────────────────

class ManagementOperationalSummary(BaseModel):
    """Rates are package-denominated (Dimension 5: count the right unit).
    Phase 2 divided delivered packages by STOP count — a unit bug.

    DELETED: nothing. on_time_completion_rate_pct is now Optional and honest.
    """
    period: str
    period_start: date
    period_end: date

    total_packages_delivered: int
    total_packages_assigned: int
    total_paid_hours: Optional[float] = None
    paid_hours_source: str                       # flex_timesheets | departures | none

    packages_per_hour: Optional[float] = None
    avg_minutes_per_stop: Optional[float] = None

    delivery_success_rate_pct: Optional[float] = None
    rework_rate_pct: Optional[float] = None
    total_rework_count: int

    routes_dispatched: int
    routes_completed: int
    completion_rate_pct: Optional[float] = None
    on_time_rate_pct: Optional[float] = None     # null when shift_end unconfigured
    on_time_reference: Optional[str] = None      # e.g. "18:00"

    crews_total: int
    crews_deployed: int
    crew_utilization_pct: Optional[float] = None

    trend_packages_per_hour: Optional[str] = None   # up | down | flat | null
    trend_success_rate: Optional[str] = None
    prior_packages_per_hour: Optional[float] = None
    prior_success_rate_pct: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class NoShowItem(BaseModel):
    employee_name: str
    role: str
    count: int


class WalkerPerformance(BaseModel):
    employee_name: str
    avg_rating: Optional[float] = None
    rating_count: int
    packages_delivered: int


class TroubleWalker(BaseModel):
    employee_name: str
    ncns_count: int
    late_count: int
    avg_rating: Optional[float] = None


class ManagementCrewSummary(BaseModel):
    """No-shows come from ShiftRollCall.status=='ncns' (ADR-200/201) — there is
    no NoShow model. Escalation comes from TrainingTask, not TrainingRecord.

    DELETED: repeat_failure_items (folded into Admin's failed_items_trending).
    """
    active_trainees: int
    escalated_trainees: int
    graduation_completion_pct: Optional[float] = None

    roll_call_total: int
    roll_call_confirmed_pct: Optional[float] = None
    no_shows_this_period: List[NoShowItem]

    top_walkers: List[WalkerPerformance]
    trouble_walkers: List[TroubleWalker]

    vehicle_inspection_pass_rate_7d: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class IncidentCategory(BaseModel):
    category: str
    count: int
    avg_per_week_30d: float


class ManagementIncidentSummary(BaseModel):
    """DELETED: patterns (never defined — pure invention)."""
    total_period: int
    by_severity: Dict[str, int]
    by_category: List[IncidentCategory]

    unresolved_count: int
    oldest_unresolved_age_hours: Optional[int] = None

    rts_pending_count: int
    avg_rts_review_hours: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class MisroutedHotspot(BaseModel):
    """block_key only. normalised_address would violate CLAUDE.md Dimension 7
    (no addresses in output) and breaks anyway — ADR-219 nulls it after 48h.
    """
    block_key: str
    count: int


class ManagementFleetSummary(BaseModel):
    """DELETED: fleet_behind_schedule (no per-route SLA exists).
    Route timing reads Route.departed_at/returned_at — TruckAssignment has
    NEITHER created_at NOR updated_at, which Phase 2 assumed.
    """
    fleet_planned: int
    fleet_active: int
    fleet_completed: int

    route_avg_duration_hours: Optional[float] = None
    routes_with_timing: int

    misrouted_count: int
    misrouted_unresolved: int
    misrouted_pct_of_packages: Optional[float] = None
    misrouted_hotspots: List[MisroutedHotspot]

    model_config = ConfigDict(from_attributes=True)


class ManagementDashboardSummary(BaseModel):
    operational: ManagementOperationalSummary
    crew: ManagementCrewSummary
    incidents: ManagementIncidentSummary
    fleet: ManagementFleetSummary
    model_config = ConfigDict(from_attributes=True)


# ── Dispatch ──────────────────────────────────────────────────────────────────

class DispatchFleetSnapshot(BaseModel):
    """manifest_total reads package_manifests (the actual manifest table) —
    Phase 2 summed DeliveryStop.packages_total instead.

    DELETED: routes_stopped_count (no 'stopped' state) → replaced by
    routes_needing_help, backed by Route.help_requested_at.
    """
    timestamp: datetime
    dispatch_date: date

    trucks_planned: int
    trucks_active: int
    trucks_completed: int

    routes_dispatched: int
    routes_needing_help: int
    routes_on_time_pct: Optional[float] = None

    manifest_totes: int
    manifest_ov: int
    manifest_total: int

    stops_planned: int
    stops_in_progress: int
    stops_completed: int
    packages_delivered: int

    avg_packages_per_active_truck: Optional[float] = None
    avg_minutes_per_stop: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class DispatchPendingRequest(BaseModel):
    """Reassignments ONLY. Time-off/off-day requests moved to ADP as a manager
    concern (see memory: adp_timeoff_readonly) and are not a dispatch queue.
    AssignmentChangeRequest is the only one of the three with created_at, so it
    is the only one that can be aged.
    """
    id: str
    employee_name: str
    requested_date: date
    reason: Optional[str] = None
    created_at: datetime
    age_minutes: int
    is_urgent: bool


class DispatchRtsRequest(BaseModel):
    report_id: str
    driver_name: str
    total_rts: int
    crew_confirmed: bool
    submitted_at: datetime
    age_minutes: int
    route_completion_pct: Optional[float] = None
    packages_remaining: Optional[int] = None
    time_in_field_hours: Optional[float] = None


class DispatchUrgentIncident(BaseModel):
    """route_id replaced by truck_id — Incident has truck_id, not route_id."""
    incident_id: str
    severity: str
    category: str
    truck_id: Optional[str] = None
    reported_at: datetime
    age_minutes: int


class DispatchActionQueue(BaseModel):
    pending_reassignments: List[DispatchPendingRequest]
    rts_requests: List[DispatchRtsRequest]
    urgent_incidents: List[DispatchUrgentIncident]
    model_config = ConfigDict(from_attributes=True)


class SlowestRoute(BaseModel):
    """Baseline is a historical mean minutes-per-package scaled by this route's
    package_count. block_keys is an ARRAY, so a per-block mean cannot attribute
    cleanly; per-package normalisation also controls for route size.
    """
    route_id: str
    route_number: Optional[int] = None
    actual_hours: float
    package_count: int
    actual_minutes_per_package: Optional[float] = None
    expected_hours: Optional[float] = None
    variance_pct: Optional[float] = None


class CrewPerformance(BaseModel):
    employee_name: str
    packages_delivered: int
    hours: Optional[float] = None
    packages_per_hour: Optional[float] = None


class DispatchPerformanceSummary(BaseModel):
    """DELETED: optimization_suggestions (no rules engine, no defined
    heuristics — pure invention).
    """
    baseline_minutes_per_package: Optional[float] = None
    baseline_sample_size: int

    slowest_routes: List[SlowestRoute]
    fastest_crew: Optional[CrewPerformance] = None
    slowest_crew: Optional[CrewPerformance] = None

    model_config = ConfigDict(from_attributes=True)


class DispatchDashboardSummary(BaseModel):
    fleet_snapshot: DispatchFleetSnapshot
    action_queue: DispatchActionQueue
    performance: DispatchPerformanceSummary
    model_config = ConfigDict(from_attributes=True)


# ── Trainer ───────────────────────────────────────────────────────────────────

class TraineePhaseRow(BaseModel):
    """current_day_number is 1-4 normal, 5 = quiz, 6+ = remediation. A {1..4}
    dict silently drops trainees, so phases are returned as rows.
    """
    phase: int
    label: str
    trainee_count: int


class StuckTrainee(BaseModel):
    trainee_name: str
    phase: int
    days_in_phase: int


class TrainerTraineeStatus(BaseModel):
    """DELETED: today_sessions_scheduled (no scheduling concept — a
    TrainingRecord is created FOR a day, never 'scheduled').
    """
    active_trainees: int
    phases: List[TraineePhaseRow]
    escalated_count: int

    records_today_total: int
    records_today_submitted: int
    records_today_open: int

    graduation_completion_pct: Optional[float] = None
    stuck_trainees: List[StuckTrainee]

    model_config = ConfigDict(from_attributes=True)


class ProblemArea(BaseModel):
    topic_title: str
    escalated_count: int
    late_count: int
    debt_count: int


class Phase4Result(BaseModel):
    trainee_name: str
    score: Optional[float] = None
    passed: Optional[bool] = None
    record_date: date


class TraineeFeedbackAboutMe(BaseModel):
    """TrainingRecord.trainer_rating is the TRAINEE rating the TRAINER.
    Phase 2 mislabelled this as trainee performance — opposite direction.
    """
    avg_rating: Optional[float] = None
    rating_count: int
    recent_comments: List[str]


class TrainerMarkSummary(BaseModel):
    """TrainerMark is a demerit against the TRAINER
    (phase_not_closed | submitted_late), not against the trainee.
    """
    total_marks: int
    by_reason: Dict[str, int]


class TrainerPerformanceSummary(BaseModel):
    """DELETED: weekly_rating_distribution (measured the wrong direction);
    escalations[].reason (Phase 2 hardcoded 'incomplete_training' for every
    row) — replaced by problem_areas with real TrainingTask signals;
    ready_for_solo_phase4[].approval_date (Phase 2 used today's date).
    """
    problem_areas: List[ProblemArea]
    phase4_results: List[Phase4Result]
    ready_for_solo: List[str]
    trainee_feedback_about_me: TraineeFeedbackAboutMe
    my_marks: TrainerMarkSummary

    model_config = ConfigDict(from_attributes=True)


class TrainerDashboardSummary(BaseModel):
    trainee_status: TrainerTraineeStatus
    performance: TrainerPerformanceSummary
    model_config = ConfigDict(from_attributes=True)
