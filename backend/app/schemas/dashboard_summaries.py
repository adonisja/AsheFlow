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

    # ADR-294 D1/D2: Optional, NOT int-with-a-zero-default.
    #
    # Zero is a MEASUREMENT — "your crew delivered nothing today". Absence is a
    # different statement — "this company has no package feed, so the question
    # does not apply". A dispatcher acts on the first and ignores the second, and
    # an int field cannot tell them apart. That conflation is the shape of the
    # 2026-07-29 incident where 11 DTO fields returned fabricated data.
    total_packages_delivered: Optional[int] = None
    total_packages_assigned: Optional[int] = None
    total_paid_hours: Optional[float] = None
    paid_hours_source: str                       # flex_timesheets | departures | none

    packages_per_hour: Optional[float] = None
    avg_minutes_per_stop: Optional[float] = None

    # D2: carry the reason. A client that infers "null means workforce mode"
    # is wrong the first time a full-mode company legitimately has no
    # deliveries yet today, so the cause is stated rather than guessed.
    package_metrics_available: bool = True
    package_metrics_unavailable_reason: Optional[str] = None

    delivery_success_rate_pct: Optional[float] = None
    rework_rate_pct: Optional[float] = None
    total_rework_count: Optional[int] = None

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


class ProblemArea(BaseModel):
    topic_title: str
    escalated_count: int
    late_count: int
    debt_count: int


class CoverageDepth(BaseModel):
    """Spare capacity per role for today.

    `spare_*` counts people who could still be called — the emergency pool
    (ADR-267) minus anyone already on a truck. Zero spare drivers is the
    number that matters: it means the next decline strands a truck.
    """
    assigned_drivers: int = 0
    spare_drivers: int = 0
    assigned_captains: int = 0
    spare_captains: int = 0
    assigned_walkers: int = 0
    spare_walkers: int = 0
    assigned_trainers: int = 0
    spare_trainers: int = 0
    # True when any truck-critical role has no spare at all.
    at_capacity_risk: bool = False

    model_config = ConfigDict(from_attributes=True)


class ManagementCrewSummary(BaseModel):
    """No-shows come from ShiftRollCall.status=='ncns' (ADR-200/201) — there is
    no NoShow model. Escalation comes from TrainingTask, not TrainingRecord.

    Training OVERSIGHT lives here, not on the trainer dashboard: comparing
    trainees across a roster, spotting who is stuck, and finding which topics
    keep failing company-wide are management judgements. A trainer's own view is
    correctly scoped to their session (see pages/TrainerDashboard/index.tsx and
    the mobile Trainer screens).

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

    # Roster-wide training oversight (moved from TrainerDashboardSummary).
    trainee_phases: List[TraineePhaseRow]
    stuck_trainees: List[StuckTrainee]
    training_problem_areas: List[ProblemArea]

    # Coverage depth (ADR-268): how many people are CALLABLE beyond those
    # already rostered, per role. Answers "are we one flu away from a stranded
    # truck" — a today number, which is why it is a field here rather than a
    # page of its own. Driver and captain are called out separately because
    # either being short strands a whole vehicle, where a walker short is a
    # slower route.
    coverage_depth: Optional[CoverageDepth] = None

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
    # ADR-294 D1/D2: Optional, NOT int-with-a-zero-default.
    #
    # Zero is a MEASUREMENT — "your crew delivered nothing today". Absence is a
    # different statement — "this company has no package feed, so the question
    # does not apply". A dispatcher acts on the first and ignores the second, and
    # an int field cannot tell them apart. That conflation is the shape of the
    # 2026-07-29 incident where 11 DTO fields returned fabricated data.
    packages_delivered: Optional[int] = None

    avg_packages_per_active_truck: Optional[float] = None
    avg_minutes_per_stop: Optional[float] = None

    # D2 — see ManagementOperationalSummary.
    package_metrics_available: bool = True
    package_metrics_unavailable_reason: Optional[str] = None

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
#
# REMOVED (ADR-241 follow-up). The trainer dashboard endpoint has no consumer and
# no remaining unique data:
#
#   phases / stuck_trainees / problem_areas
#       -> moved to ManagementCrewSummary. Comparing trainees across a roster is
#          management oversight, not a trainer's own work.
#
#   my_marks
#       -> mobile TrainerPerformanceScreen already does this better via
#          /trainer-marks/mine + /mine/summary (standing banner, per-mark debt
#          chain expansion, distinct_trainees_with_marks).
#
#   trainee_feedback_about_me
#       -> mobile TrainerHistoryScreen already surfaces trainer_rating and
#          trainee_comments.
#
#   phase4_results / records_today_*
#       -> mobile Phase4Screen and TrainerTodayScreen cover these from
#          /training/trainer/today.
#
# Field staff are mobile-first, and the mobile trainer surface (7 screens) is
# more complete than the web page ever was.


# ── Decline analysis (ADR-268) ────────────────────────────────────────────────

class DeclineSlice(BaseModel):
    """One slice of decline data — a weekday, a truck, or a person.

    `rate` is Optional and is None until the slice clears its volume gate. That
    is deliberate and load-bearing: a consumer rendering `rate ?? count` cannot
    accidentally publish a one-sample percentage as a finding. Returning 0.0
    would require every caller to remember to check `gated` first, and one that
    forgets shows "0% declines" for a slice with no data.
    """
    key: str
    declines: int
    total: int
    # Distinct dates observed. For a weekday slice this is the GATE unit: 12
    # confirmations across 2 Fridays is not 12 observations of "Friday".
    occurrences: int
    rate: Optional[float] = None
    gated: bool

    model_config = ConfigDict(from_attributes=True)


class DeclineAnalysisOut(BaseModel):
    """Where the operation loses capacity to declines, sliced three ways.

    A raw decline rate is ambiguous — "declined 4 of 12" reads the same whether
    someone is unreliable or is repeatedly handed a shift they cannot make.
    Clustering disambiguates: concentrated on a weekday it is a ROTA problem,
    concentrated on a truck it is that shift, and only alongside those two is
    the per-person number interpretable.

    Slices below their gate keep `rate: null` and sort last.
    """
    start_date: date
    end_date: date
    total_confirmations: int
    total_declines: int
    by_weekday: List[DeclineSlice]
    by_truck: List[DeclineSlice]
    by_person: List[DeclineSlice]

    model_config = ConfigDict(from_attributes=True)
