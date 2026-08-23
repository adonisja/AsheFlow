// Shared API response types for all AsheFlow endpoints.
// Import from here instead of using `any` in page components.

// ---------------------------------------------------------------------------
// Core entities
// ---------------------------------------------------------------------------

export interface Employee {
  id: string;
  name: string;
  first_name?: string;
  email?: string;
  discord_id?: string;
  cognito_sub?: string;
  role: string;
  is_active: boolean;
  phone_number?: string | null;
}

export interface Truck {
  id: string;
  name: string;
  is_active: boolean;
  /** A hub truck (ADR-274): excluded from run_dispatch and staffed by hand for
   *  intra-day assembly. Independent of is_active — a hub is an active truck
   *  that is simply not auto-assignable. Its Discord room is the same
   *  discord_channel_id every other truck uses. */
  is_hub?: boolean;
  discord_channel_id?: string | null;
  initial_anchor_lat?: number | null;
  initial_anchor_lng?: number | null;
  initial_anchor_address?: string | null;
  initial_anchor2_lat?: number | null;
  initial_anchor2_lng?: number | null;
  initial_anchor2_address?: string | null;
}

export interface OutlierTote {
  tote_id: string;
  centroid_lat: number | null;
  centroid_lng: number | null;
  package_count: number;
  tba_numbers: string[];
}

export interface OutlierTotesResponse {
  sort_date: string;
  totes: OutlierTote[];
  manifest_available: boolean;
}

// ── Station load finalization (ADR-174) ─────────────────────────────────────

export interface ToteTransferOut {
  id: string;
  bag_id: string;
  from_truck_id: string;
  from_truck_name: string;
  from_driver_name?: string | null;
  to_truck_id: string;
  to_truck_name: string;
  to_driver_name?: string | null;
  package_count?: number | null;
  status: 'suggested' | 'confirmed' | 'completed' | 'kept' | 'undone';
  reason: 'rerun_diff' | 'dispatch';
}

export interface OvDetail {
  size: string;            // OV_S | OV_M | OV_L | OV_XL
  zone?: string | null;    // OV sort zone on the dock
}

export interface RosterTote {
  bag_id: string;
  package_count: number;
  ov_count: number;
  ov_sizes: string[];
  ov_details?: OvDetail[];
  dock_tags: string[];
  ov_dock_tags: string[];
  rider_count?: number;
  pull_tbas?: string[];
  checked: boolean;
  checked_by_name?: string | null;
  transfer?: ToteTransferOut | null;
}

export interface TruckRoster {
  zone_id: string;
  truck_id: string;
  zone_label: string;
  driver_name?: string | null;
  totes: RosterTote[];
  tote_count: number;
  checked_count: number;
  incoming: ToteTransferOut[];
  outgoing: ToteTransferOut[];
  // ADR-181 driver handoff
  load_confirmed?: boolean;
  confirmed_by_name?: string | null;
  confirmed_at?: string | null;
  short_count?: number;
}

export interface RostersResponse {
  sort_date: string;
  rosters: TruckRoster[];
  pending_transfer_count: number;
  unchecked_count: number;
  flagged_removal_count?: number;
  loading_finalized: boolean;
  roster_available: boolean;
}

// ADR-184 mid-day freight addition
export interface UnroutedItem {
  tba: string;
  reason: 'geocode_failed' | 'truck_confirmed' | 'no_match' | string;
}

export interface AddFreightResponse extends RostersResponse {
  added: number;
  unrouted: UnroutedItem[];
}

export interface LooseFreightIn {
  tba: string;
  address: string;
  size?: string;
}

// ── Out-of-zone removals (ADR-176) ──────────────────────────────────────────

export interface RemovalOut {
  id: string;
  bag_id: string;
  tba?: string | null;              // null = whole tote
  tba_numbers?: string[] | null;
  package_count: number;
  whole_tote: boolean;
  reason: string;
  locator?: string | null;
  truck_name?: string | null;
  status: 'flagged' | 'removed';
  pull_point: 'station' | 'anchor_point';
  removed_by_name?: string | null;
  removed_at?: string | null;
  // AP-pull walker->driver handoff (ADR-178) — anchor_point rows only
  owner_walker_name?: string | null;
  owner_route_number?: number | null;
  handoff_status?: 'pending' | 'handed_over' | 'received';
  handed_over_by_name?: string | null;
  received_by_name?: string | null;
}

export interface RemovalsResponse {
  sort_date: string;
  removals: RemovalOut[];
  flagged_count: number;
  removed_count: number;
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

export interface CrewMember {
  employee_id: string;
  name: string;
  role: string;
  assignment_id?: string;
  discord_id?: string | null;
  id?: string; // fallback used in some contexts
}

export interface DispatchWarning {
  type?: string;
  message?: string;
  employee_id?: string;
  banned_by?: string[];
}

export interface DispatchResult {
  date: string;
  assigned_crews: Record<string, CrewMember[]>;
  truck_assignments?: {
    truck_id: string;
    status: string;
    /** TruckAssignment id — mobile AP Sort / My Route resolve the truck with it. */
    assignment_id?: string;
    /** From the TRUCK, not derived from status (ADR-274). The old client-side
     *  derivation (`status === 'planned'`) matched every truck before publish. */
    is_hub?: boolean;
    /** Physical bay this truck collects from (ADR-274 D17). Null until dispatch
     *  sets one or publish inherits the truck's last known bay. The Discord bot
     *  reads this same payload, so the DM and this board cannot disagree. */
    dock_zone?: string | null;
  }[];
  workflow_status?: 'dispatched' | 'published' | 'finalized';
  /** ADR-264 — scheduled driver trainees with no crew row today.
   *
   *  A driver trainee is HELD OUT of crews rather than paired with a driver who
   *  has never supervised them. Held out is only safe if it is visible: they
   *  have no AssignmentMember row, so they appear in no truck, and the run-time
   *  warning used to be discarded by this endpoint on every refresh.
   *
   *  Derived on read, so pairing them by hand makes the entry disappear with
   *  nothing to dismiss. */
  unpaired_driver_trainees?: {
    employee_id: string;
    employee_name: string;
    /** 'first_day' — never had a supervisor.
     *  'unavailable' — every driver who has supervised them is off today. */
    reason: 'first_day' | 'unavailable';
  }[];
  warnings: DispatchWarning[];
}

/** POST /dispatch/{date}/finalize (ADR-256 D3).
 *
 * `captainless_trucks` names trucks that finalized WITHOUT a captain. The gate is
 * warn-only until captains are staffed and assign_captains places them, so this is
 * the only signal that a truck rolled with no route lead — a 200 alone looks clean.
 */
export interface FinalizeResponse {
  status: string;
  date: string;
  captainless_trucks: string[];
}

export interface UnavailableStaff {
  id: string;
  name: string;
  role: string;
  discord_id: string;
  phone_number: string | null;
  reason: 'time_off_request' | 'recurring_off_day';
}

/**
 * One person dispatch can still phone for a date (ADR-267).
 *
 * Distinct from UnavailableStaff, which answers "who did the pool exclude" —
 * that INCLUDES approved PTO (who must not be called) and OMITS decliners and
 * unassigned staff (who are exactly who you call).
 */
export interface EmergencyPoolMember {
  id: string;
  name: string;
  role: string;
  /** Why they are free. Most actionable wins where several apply. */
  reason: 'declined' | 'scheduled_off' | 'unassigned';
  phone_number: string | null;
  email: string | null;
  discord_id: string | null;
  /** Resolved live from the bot's member cache; null if the bot cannot see
   *  them or is down. Never stored, so it cannot go stale. */
  discord_name: string | null;
}

export type ConfirmationStatus = 'pending' | 'confirmed' | 'declined';

export interface ConfirmationsResponse {
  date: string;
  confirmations: Record<string, ConfirmationStatus>;
}

// ---------------------------------------------------------------------------
// Field Ops
// ---------------------------------------------------------------------------

export interface CheckIn {
  date: string;
  photo_url?: string | null;
  checked_in_at: string;
}

export interface Departure {
  date: string;
  itinerary_photo_url?: string | null;
  departed_at: string | null;
  returned_at: string | null;
}

export interface VehicleInspection {
  date: string;
  has_failures: boolean;
  items: Record<string, boolean>;
  notes?: string | null;
}

export interface FuelLog {
  id: string;
  date: string;
  odometer_start: number;
  odometer_end?: number | null;
  fuel_added?: number | null;
  notes?: string | null;
}

export interface WalkerRating {
  walker_id: string;
  driver_id?: string;
  driver_name?: string;
  date: string;
  present: boolean;
  stars?: number | null;
  comment?: string | null;
  rated_at?: string;
  id?: string;
}

export interface CrewForDriver {
  crew: Array<{ id: string; name: string; role: string }>;
  truck_id: string;
}

export interface CheckInSummaryRow {
  date: string;
  driver_name: string;
  employee_id: string;
}

export interface ReturnSummaryRow {
  driver_name: string;
  employee_id: string;
  departed_at: string | null;
  returned_at: string | null;
  duration_minutes: number | null;
  status: string;
}

export interface InspectionSummaryRow {
  inspection_id: string;
  driver_name: string;
  truck_name: string | null;
  date: string;
  inspection_type: string;
  submitted_at: string;
  has_failures: boolean;
  failed_items: string[];
  notes?: string | null;
}

export interface FuelLogSummaryRow {
  log_id: string;
  driver_name: string;
  truck_name: string;
  odometer_start: number;
  odometer_end: number | null;
  distance: number | null;
  fuel_added: number | null;
}

export interface NoShowRow {
  walker_id: string;
  walker_name: string;
  driver_name: string;
}

export interface AnchorPoint {
  id: string;
  truck_id: string;
  driver_id: string;
  date: string;
  sequence: number;
  is_initial: boolean;
  status: 'preliminary' | 'arrived' | 'relocated';
  location: string;
  eta: string | null;
  notes: string | null;
  submitted_at: string;
  arrived_at: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

// ---------------------------------------------------------------------------
// Walker Performance
// ---------------------------------------------------------------------------

// Peer-rating leaderboard row (ADR-201). Keyed by employee (any crew role).
export interface WalkerSummary {
  employee_id: string;
  employee_name: string;
  role: string;
  ratings_received: number;
  distinct_raters: number;
  avg_stars: number | null;
  grade: 'A' | 'B' | 'C' | 'D' | 'F' | null;
  grade_eligible: boolean;

  // ── Operational outcomes (ADR-268) ────────────────────────────────────────
  // Reported ALONGSIDE the peer grade, never folded into it: an outcome and an
  // opinion are different claims, and averaging them makes both unreadable.
  packages_total: number;
  rts_count: number;
  missing_count: number;
  /** Raw return rate. Confounded by route difficulty — 2.10% on easy routes
   *  against 10.81% on heavy. Do NOT rank people on this. */
  rts_rate: number | null;
  /** rts_rate divided by the company rate for the same effort class,
   *  volume-weighted across the classes this person actually worked.
   *  1.0 = exactly typical for work of that difficulty. THE fair comparison. */
  rts_rate_vs_class: number | null;
  /** False when they have not worked enough packages (100) for any of the
   *  above to mean anything. Check this before flagging anyone. */
  outcome_volume_ok: boolean;
  /** Materially worse than peers on comparable work (>= 1.5x class baseline). */
  outcome_at_risk: boolean;
}

export interface WalkerRatingDetail {
  id: string;
  date: string;
  rater_id: string;
  rater_name: string;
  stars: number;
  comment: string | null;
  rated_at: string;
}

// Profile keeps walker_* keys for the existing page contract (ADR-201).
export interface WalkerProfile {
  walker_id: string;
  walker_name: string;
  ratings_received: number;
  distinct_raters: number;
  avg_stars: number | null;
  grade: 'A' | 'B' | 'C' | 'D' | 'F' | null;
  ratings: WalkerRatingDetail[];
}

export interface DriverConsistencyRow {
  driver_id: string;
  driver_name: string;
  shift_count: number;
  avg_stars: number | null;
  deviation: number | null;
  flagged: boolean;
}

export interface WalkerConsistency {
  walker_avg_stars: number | null;
  flag_threshold: number;
  drivers: DriverConsistencyRow[];
}

// ---------------------------------------------------------------------------
// Incidents
// ---------------------------------------------------------------------------

export interface Incident {
  id: string;
  date: string;
  severity: 'warning' | 'critical';
  category: string;
  description: string;
  photo_url?: string | null;
  incident_location?: string | null;
  packages_tba?: string | null;
  incident_time?: string | null;
  witness_name?: string | null;
  body_part_affected?: string | null;
  medical_attention_required?: boolean;
  resolved: boolean;
  resolved_at?: string | null;
  reporter_name?: string;
  driver_name?: string;
  truck_name?: string;
  driver_id?: string;
}

// ---------------------------------------------------------------------------
// Schedule
// ---------------------------------------------------------------------------

export interface ScheduleDay {
  date: string;
  status: string;
  truck_name?: string | null;
  crew?: Array<{ id: string; name: string; role: string }>;
}

export interface TimeOffRequest {
  id: string;
  employee_id: string;
  date: string;
  created_at: string;
  status: 'pending' | 'approved' | 'rejected';
}

export interface EmployeeOffDay {
  id: string;
  employee_id: string;
  day_of_week: string;
  created_at: string;
  status: 'pending' | 'approved' | 'rejected';
}

export interface ScheduleChangeRequest {
  id: string;
  employee_id: string;
  created_at: string;
  status: string;
  request_type: string;
  days_to_add?: string[] | null;
  days_to_drop?: string[] | null;
  proposed_schedule?: string[] | null;
  reason?: string | null;
  employee?: { name: string; role: string };
}

export interface AvailabilityByDate {
  driver: Array<{ id: string }>;
  trainer: Array<{ id: string }>;
  walker: Array<{ id: string }>;
}

// ---------------------------------------------------------------------------
// Training
// ---------------------------------------------------------------------------

export interface TrainingTask {
  id: string;
  topic_title: string;
  is_completed: boolean;
  is_training_debt: boolean;
  is_escalated: boolean;
}

export interface TrainingRecord {
  id: string;
  current_day_number: number;
  is_locked: boolean;
  trainer_comments?: string | null;
  trainer_rating?: number | null;
  trainee_comments?: string | null;
  manager_comments?: string | null;
  record_date?: string;
}

export interface TrainerMark {
  id: string;
  reason: string;
  trainee: { name: string };
  phase: number;
  record_date: string;
  debt_chain_context?: string | null;
}

export interface TrainerMarkSummary {
  total_marks: number;
  distinct_trainees_with_marks: number;
  underperforming: boolean;
}

export interface TrainerTodayData {
  record: TrainingRecord | null;
  trainee: { id: string; name: string } | null;
  tasks: TrainingTask[];
  previous_trainer_comments: {
    comments: string;
    record_date: string;
    day_number: number;
  } | null;
  manager_comments: string | null;
}

export interface TrainerHistorySession {
  record: TrainingRecord;
  tasks: TrainingTask[];
}

export interface TrainerHistoryGroup {
  trainee: { id: string; name: string };
  sessions: TrainerHistorySession[];
}

export interface ActiveTrainingRow {
  record: { id: string };
  trainee: { name: string };
  trainer: { name: string };
  progress: { completed: number; total: number };
}

// ---------------------------------------------------------------------------
// Employee Relationships
// ---------------------------------------------------------------------------

export interface EmployeeRelationship {
  id: string;
  employee_id: string;
  target_employee_id: string;
  relationship_type: 'fav' | 'ban';
}

export interface AssignmentChangeRequest {
  id: string;
  requested_date: string;
  status: string;
  reason?: string | null;
  employee?: { name: string; role: string };
}

// ---------------------------------------------------------------------------
// Walker Sort / Route Model
// ---------------------------------------------------------------------------

/** Sort-time DTO — emitted by route_sort BEFORE any flag row exists, so it
 *  deliberately has no `id`. For a PERSISTED flag (which is what
 *  RouteResponse.misrouted_packages carries) use MisroutedPackageFlagResponse. */
export interface MisroutedPackageOut {
  tba_number: string;
  current_bag_id: string;
  destination_block_key: string | null;
  normalised_address?: string | null;
  suggested_route_number: number | null;
}

/** A persisted misroute flag. This — not MisroutedPackageOut — is what
 *  RouteResponse.misrouted_packages contains; `id` is what
 *  PATCH /walker-routes/routes/{routeId}/misroutes/{id}/resolve needs. */
export interface MisroutedPackageFlagResponse {
  id: string;
  route_id: string;
  tba_number: string;
  current_bag_id: string;
  destination_block_key: string | null;
  normalised_address: string | null;
  suggested_route_id: string | null;
  resolved: boolean;
  resolved_by: string | null;
  resolved_at: string | null;
}

/** One delivery stop — a unique address with its packages (ADR-194).
 *  Server-sorted: blocks ascending, house numbers ascending within a block. */
export interface RouteStop {
  block_key: string;
  address: string;
  /** ADR-279: LION segment for this building, modal across the stop's packages.
   *  null when GeoClient returned no segment topology for the address. */
  segment_id: string | null;
  tba_numbers: string[];
}

export interface RouteOut {
  route_number: number;
  block_keys: string[];
  tote_ids: string[];
  tba_numbers: string[];
  normalised_addresses: string[];
  stops?: RouteStop[];
  slot_cost: number;
  capacity_limit: number;
  effort_class: 'easy' | 'standard' | 'heavy' | 'very_heavy';
  effort_score: number;
  workload_source: 'address_profile' | 'block_profile' | 'flag' | 'default';
  package_count: number;
  coverage_pct: number;
  misrouted_packages: MisroutedPackageOut[];
}

export interface SortResult {
  truck_assignment_id: string;
  route_date: string;
  routes: RouteOut[];
  unassigned_misroutes: MisroutedPackageOut[];
}

// ADR-212: a route participant (executor or supervisor), name resolved server-side.
export interface RouteParticipant {
  id: string;   // employee_id
  name: string;
}

export interface RouteResponse {
  id: string;
  truck_assignment_id: string;
  route_date: string;
  route_number: number;
  wave_number: number;
  block_keys: string[];
  tote_ids: string[];
  tba_numbers: string[];
  normalised_addresses: string[];
  stops: RouteStop[] | null;   // null = route predates ADR-194 → fall back to flat lists
  slot_cost: number;
  capacity_limit: number;
  package_count: number;
  capacity_limit_paired: number | null;
  effort_class: 'easy' | 'standard' | 'heavy' | 'very_heavy';
  effort_score: number | null;
  workload_source: 'address_profile' | 'block_profile' | 'flag' | 'default';
  coverage_pct: number | null;
  // ADR-212: membership. executor = assignee-of-record (null until assigned);
  // supervisors = trainers overseeing the route ([] when solo).
  executor: RouteParticipant | null;
  supervisors: RouteParticipant[];
  trainee_phase: number | null;
  phase4_solo_opted_in: boolean;
  status: 'unassigned' | 'assigned' | 'in_progress' | 'completed';
  departed_at: string | null;
  returned_at: string | null;
  /** Stamped by POST /request-help (ADR-229) — gates the captain's
   *  emergency split. Idempotent re-stamp. */
  help_requested_at: string | null;
  created_at: string;
  misrouted_packages: MisroutedPackageFlagResponse[];
}

export interface WalkerRouteResponse {
  id: string;
  truck_assignment_id: string;
  route_date: string;
  employee_id: string;
  total_routes: number;
  total_packages: number;
  total_bags: number;
  total_slot_cost: number;
  created_at: string;
  routes: RouteResponse[];
}

export interface CommitSortResponse {
  routes: RouteResponse[];
  packages_sorted: number;
  packages_dropped: number;
  dropped_tbas: string[];
  unassigned_misroutes: MisroutedPackageOut[];
}

export interface WaveAssignmentEntry {
  route_number: number;
  employee_id: string;
  // D9.2: true = accepted from auto-proposal as-is; false = human overrode;
  // null/undefined = manually assigned (no proposal for this route)
  auto_proposed?: boolean | null;
}

// ---------------------------------------------------------------------------
// Wave pool (GET /{truck_assignment_id}/wave-pool)
// ---------------------------------------------------------------------------

export interface ReturnedWalkerRoute {
  route_number: number;
  wave_number: number;
  package_count: number;
  effort_class: string;
}

export interface ReturnedWalker {
  employee_id: string;
  employee_name: string;
  injury_status: string | null;
  completed_routes: ReturnedWalkerRoute[];
}

export interface UnassignedRouteEntry {
  route_id: string;
  route_number: number;
  effort_class: string;
  package_count: number;
  slot_cost: number;
  wave_number: number;
}

export interface WaveStatusCounts {
  assigned: number;
  in_progress: number;
  completed: number;
  unassigned: number;
}

export interface WaveSummary {
  waves: Record<string, WaveStatusCounts>;
  total_routes: number;
}

export interface WavePoolResponse {
  returned_walkers: ReturnedWalker[];
  unassigned_routes: UnassignedRouteEntry[];
  wave_summary: WaveSummary;
}

// ---------------------------------------------------------------------------
// Wave distribution — auto-propose mode
// ---------------------------------------------------------------------------

export interface ProposedAssignmentEntry {
  route_number: number;
  route_id: string;
  employee_id: string;
  employee_name: string;
  effort_class: string;
  auto_proposed: boolean;
}

export interface WaveDistributionProposal {
  proposed_assignments: ProposedAssignmentEntry[];
  conflicts: string[];
}

// ---------------------------------------------------------------------------
// My Assignment (GET /assignments/mine)
// ---------------------------------------------------------------------------

export interface MyAssignmentResponse {
  truck_assignment_id: string;
  truck_id: string;
  truck_name: string;
  date: string;
  status: string;
  role: string;
  paired_trainer_id: string | null;
}

// ---------------------------------------------------------------------------
// RTS / Missing Packages / Delivery Stops
// ---------------------------------------------------------------------------

export type RtsType =
  | 'no_access'
  | 'business_closed'
  | 'package_damaged'
  | 'inclement_weather'
  | 'customer_requested_future_delivery'
  | 'customer_cancelled_order';

export interface RTSPackageCreate {
  route_id: string;
  tba_number: string;
  rts_type: RtsType;
  rts_explanation: string;
}

export interface RTSPackageResponse {
  id: string;
  company_id: string;
  route_id: string;
  truck_assignment_id: string;
  tba_number: string;
  normalised_address: string | null;
  rts_type: string;
  rts_explanation: string;
  is_reattemptable: boolean;
  walker_id: string | null;
  walker_name: string | null;
  recorded_at: string;
  delivery_stop_id: string | null;
}

export interface MissingPackageCreate {
  route_id: string;
  tba_number: string;
}

export interface MissingPackageResponse {
  id: string;
  company_id: string;
  route_id: string;
  truck_assignment_id: string;
  tba_number: string;
  normalised_address: string | null;
  walker_id: string | null;
  walker_name: string | null;
  reported_at: string;
  resolution_status: string;
  misroute_flag_id: string | null;
  resolution_notes: string | null;
  resolved_by: string | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  delivery_stop_id: string | null;
}

// Dispatch queue view of MissingPackageResponse — adds route context (ADR-190)
export interface MissingQueueEntry extends MissingPackageResponse {
  route_number: number | null;
  route_date: string | null;
}

// Pre-route damage reporting (ADR-190). On-route damage stays in the RTS flow.
export type DamageStage = 'station_sort' | 'truck_load' | 'in_truck';

export interface DamagedPackageCreate {
  route_date: string;
  tba_number: string;
  stage: DamageStage;
  damage_notes: string;
  bag_id?: string | null;
  truck_assignment_id?: string | null;
}

export interface DamagedPackageResponse {
  id: string;
  company_id: string;
  route_date: string;
  tba_number: string;
  bag_id: string | null;
  truck_assignment_id: string | null;
  stage: string;
  damage_notes: string;
  normalised_address: string | null;
  reported_by: string | null;
  reported_by_name: string | null;
  reported_at: string;
  resolution_status: string;
  resolution_notes: string | null;
  resolved_by: string | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
}

export interface DeliveryStopCreate {
  route_id: string;
  tba_numbers: string[];
  completed_at: string;
}

export interface DeliveryStopResponse {
  id: string;
  company_id: string;
  route_id: string;
  truck_assignment_id: string;
  walker_id: string | null;
  walker_name: string | null;
  normalised_address: string;
  block_key: string;
  /** ADR-279: purge-durable join key. Survives the ADR-219 48h address nulling
   *  (public street topology, like block_key), so it stays set after
   *  normalised_address is gone. null on ad-hoc stops (RTS, found packages). */
  segment_id: string | null;
  tba_numbers: string[];
  // Lifecycle (ADR-197): planned rows carry nulls until completed
  status: 'planned' | 'in_progress' | 'completed';
  is_unplanned: boolean;
  started_at: string | null;
  completed_at: string | null;
  stop_sequence: number;
  packages_total: number | null;
  packages_delivered: number | null;
  rts_count: number;
  missing_count: number;
  effort_class: string | null;
  workload_class: string | null;
}

// ── Crew status + availability (ADR-197 Phase 0b) ──────────────────────────

export interface AssignmentMemberResponse {
  id: string;
  company_id: string;
  assignment_id: string;
  employee_id: string;
  role: string;
  paired_trainer_id: string | null;
  status: 'active' | 'departed' | 'transferred';
  departed_at: string | null;
}

export interface CrewAvailabilityEntry {
  employee_id: string;
  name: string | null;
  role: string;
  membership_status: 'active' | 'departed' | 'transferred';
  availability: 'not_arrived' | 'available' | 'on_route_early' | 'on_route_returning' | 'done' | 'off_crew';
  route_completion_pct: number | null;
}

export interface CrewAvailabilityResponse {
  entries: CrewAvailabilityEntry[];
  active_crew: number;
  available_for_route: number;
  completion_threshold: number;
}

// Crew Status page (ADR-197 Phase B) — enriched, fleet-aware.
export interface CrewStatusMember {
  member_id: string | null;
  employee_id: string;
  name: string | null;
  role: string;
  membership_status: 'active' | 'departed' | 'transferred';
  availability: 'not_arrived' | 'available' | 'on_route_early' | 'on_route_returning' | 'done' | 'off_crew';
  route_completion_pct: number | null;
  trip_count: number;
  paired_trainer_id: string | null;
  paired_trainer_name: string | null;
  paired_trainee_id: string | null;
  paired_trainee_name: string | null;
  orphaned: boolean;
  current_stop_sequence: number | null;
  current_stop_total: number | null;
  /** Present on the wire for the crew map. Do not render or log it —
   *  Dimension 7 keeps addresses out of surfaces that outlive the shift. */
  current_stop_address: string | null;
}

export interface CrewStatusTruck {
  truck_assignment_id: string;
  truck_id: string;
  truck_name: string | null;
  active_crew: number;
  available_for_route: number;
  members: CrewStatusMember[];
}

export interface CrewStatusResponse {
  date: string;
  completion_threshold: number;
  trucks: CrewStatusTruck[];
}

// ADR-199 Phase B reassignment (available-trainer suggestion + reassign).
export interface AvailableTrainer {
  trainer_id: string;
  trainer_name: string | null;
  truck_assignment_id: string;
  truck_id: string;
  truck_name: string | null;
  same_truck: boolean;
  has_route: boolean;
}

export interface AvailableTrainersResponse {
  trainee_id: string;
  trainee_name: string | null;
  current_trainer_id: string | null;
  suggestions: AvailableTrainer[];
}

export interface StopSignal {
  signal: string;
  reason: string;
  urgency: number;
}

export interface BagGroup {
  bag_id: string;
  tba_numbers: string[];
}

export interface NextStopSuggestion {
  normalised_address: string;
  block_key: string;
  tba_numbers: string[];
  bags: BagGroup[];
  packages_total: number;
  signals: StopSignal[];
  urgency_score: number;
  building_type: string | null;
  workload_class: string | null;
  operational_note: string | null;
  protocol_reminder: string | null;
  has_locked_profile: boolean;
}

// ---------------------------------------------------------------------------
// Building Profiles
// ---------------------------------------------------------------------------

export type BuildingType =
  | 'receptionist'
  | 'walkup'
  | 'elevator'
  | 'biz_freight'
  | 'biz_security'
  | 'biz_loading_dock'
  | 'mailroom'
  | 'doorman'
  | 'biz_front';

export interface BuildingProfileCreate {
  normalised_address: string;
  block_key?: string;
  building_type: BuildingType;
  raw_note?: string;
}

export interface LocationHint {
  label: string;
  sublabel: string;
  source: 'history' | 'truck_anchor' | 'building_profile';
  use_count?: number | null;   // times this AP was used (history)
  distance_m?: number | null;  // metres from today's package cluster centroid
  reason?: string | null;      // human summary, e.g. "used 4× · ~230 m from today's cluster"
}

export interface BuildingProfileAnchorPatch {
  lat: number | null;
  lng: number | null;
  note?: string | null;
}

export interface BuildingProfileResponse {
  id: string;
  company_id: string;
  normalised_address: string;
  block_key: string;
  building_type: string;
  workload_class: string;
  raw_note: string | null;
  operational_note: string | null;
  note_verified: boolean;
  protocol_reminder: string | null;
  /** ADR-276 D1 — two stages. 'review' means the field agreed (two walkers, or
   *  one captain) and it is queued for a captain or dispatch to sign off;
   *  'verified' means a route lead has. Only 'locked' is read downstream. */
  building_type_status: 'pending' | 'review' | 'verified' | 'locked';
  building_type_agreement_count: number;
  /** ADR-277 D1 — address resolution, independent of building_type_status.
   *  A profile can have full field agreement and still be 'rejected' here:
   *  the crew agrees about a building whose address GeoClient cannot match.
   *  'rejected' rows show the retry affordance and can never be locked. */
  address_status: 'pending' | 'resolved' | 'rejected';
  /** Geosupport return code + message on rejection, e.g. "42" /
   *  "ADDRESS NUMBER OUT OF RANGE". Shown beside the retry form so the
   *  captain knows what to change. */
  geo_grc?: string | null;
  geo_message?: string | null;
  /** ADR-277 D2 / ADR-279 — LION segment, the join key that survives the
   *  ADR-219 48h address purge. lat/lng drive proximity sorting. */
  segment_id?: string | null;
  lat?: number | null;
  lng?: number | null;
  /** ADR-276 D6 — computed server-side per caller so neither client re-derives
   *  the weighting rule. Null on read paths that do not resolve caller state,
   *  where the UI falls back to showing the raw count. */
  remaining_weight?: number | null;
  can_verify?: boolean | null;
  verify_blocked_reason?: 'own_submission' | 'already_verified'
    | 'not_a_field_verifier' | 'awaiting_signoff' | null;
  nomination_status: string | null;
  submitted_by: string | null;
  submitted_by_name: string;
  submitted_at: string | null;
  verified_by: string | null;
  verified_by_name: string | null;
  verified_at: string | null;
  initial_anchor_lat: number | null;
  initial_anchor_lng: number | null;
  initial_anchor_note: string | null;
  initial_anchor_set_by: string | null;
  initial_anchor_set_by_name: string | null;
  initial_anchor_set_at: string | null;
  created_at: string;
  updated_at: string;
}

/** ADR-277 D3 — one address this truck visited, with whatever we know about it.
 *  `profile` is null for the "no profile yet" group: that is the collection
 *  prompt, not a missing field. */
export interface TruckBuildingStop {
  normalised_address: string | null;
  block_key: string;
  segment_id: string | null;
  /** Times this truck hit the address in range — most-visited sorts first,
   *  because that building is worth profiling before a one-off. */
  stop_count: number;
  profile: BuildingProfileResponse | null;
}

/** ADR-277 D3 — three groups, in the order a captain works them. Sent as three
 *  lists rather than one flat list with a status, so the client cannot re-derive
 *  the grouping differently from the server. */
/** ADR-277 D4 — one parsed CSV row, carrying whatever is wrong with it.
 *  Invalid rows are KEPT, not filtered: the preview has to show which of the
 *  operator's rows will not import and why. */
export interface BulkProfileRow {
  /** 1-based and matching the file, so a header is line 1 and the first data
   *  row is line 2 — the operator fixes their CSV by line number. */
  line: number;
  address: string;
  building_type: string;
  raw_note?: string | null;
  ok: boolean;
  error?: string | null;
  /** An existing profile's address when this row collides with one. */
  duplicate_of?: string | null;
}

export interface BulkProfilePreview {
  rows: BulkProfileRow[];
  valid_count: number;
  error_count: number;
  duplicate_count: number;
}

export interface BulkProfileConfirm {
  rows: BulkProfileRow[];
}

export interface BulkProfileResult {
  created: number;
  skipped: number;
  errors: string[];
}

export interface TruckBuildingsResponse {
  route_date: string;
  truck_assignment_id: string | null;
  truck_name: string | null;
  needs_signoff: TruckBuildingStop[];
  known: TruckBuildingStop[];
  no_profile: TruckBuildingStop[];
  /** True when the caller is not crewed on a truck that day — the UI says so
   *  instead of rendering three empty lists as a fully-profiled day. */
  no_truck_assigned: boolean;
}

export interface ManifestStatusResponse {
  sort_date: string;
  status: 'ready' | 'enriching' | 'failed' | 'not_found';
  package_count: number;
  failed_count: number;
  failed_reason: string | null;
  packages_processed: number | null;
  packages_total: number | null;
}

// ---------------------------------------------------------------------------
// Manifest sort run
// ---------------------------------------------------------------------------


export interface SortRunRequest {
  sort_date: string;
}

export type AnchorSource = 'truck_anchor' | 'zone_history' | 'building_profile' | 'quantile';

export interface ClusterAssignmentOut {
  truck_id: string;
  truck_name: string;
  anchor_source?: AnchorSource | null;
  workload_score: number | null;
  package_count: number;
}

export interface SortRunResponse {
  sort_date: string;
  package_count: number;
  outlier_count: number;
  cluster_count: number;
  zones_created: number;
  station_removals: number;
  ap_flags: number;
  unplaced_totes: number;
  volume_alert: boolean;
  volume_alert_msg: string;
  assignments: ClusterAssignmentOut[];
}

export interface SortRunAccepted {
  task_id: string;
  status: 'queued';
}

export type SortRunTaskStatus = 'running' | 'done' | 'tier1_failed' | 'error';

export interface SortRunStatusResponse {
  task_id: string;
  status: 'running' | 'done' | 'error';
  sort_date?: string;
  package_count?: number;
  outlier_count?: number;
  cluster_count?: number;
  zones_created?: number;
  station_removals?: number;
  ap_flags?: number;
  unplaced_totes?: number;
  volume_alert?: boolean;
  volume_alert_msg?: string;
  assignments: ClusterAssignmentOut[];
  detail?: string | null;
  http_status?: number | null;
}

export interface ManifestPreviewRow {
  tba: string;
  raw_address: string | null;
  normalised_address: string | null;
  block_key: string | null;
  lat: number | null;
  lng: number | null;
  bag_id: string | null;
  enriched: boolean;
  geocode_reason: string | null;
}

export interface ManifestPreviewResponse {
  sort_date: string;
  total_packages: number;
  enriched_count: number;
  failed_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  preview_rows: ManifestPreviewRow[];
}

export interface ManifestPackagePatchResponse {
  tba: string;
  raw_address: string | null;
  normalised_address: string | null;
  block_key: string | null;
  lat: number | null;
  lng: number | null;
  enriched: boolean;
  geocode_reason: string | null;
}

export interface SortPreviewAssignment {
  truck_id: string;
  truck_name: string;
  anchor_source?: AnchorSource | null;
  workload_score: number | null;
  package_count: number;
  outlier_count: number;
}

export interface SortPreviewResponse {
  sort_date: string;
  task_id: string;
  package_count: number;
  outlier_count: number;
  cluster_count: number;
  zones_created: number;
  station_removals: number;
  ap_flags: number;
  unplaced_totes: number;
  volume_alert: boolean;
  volume_alert_msg: string;
  assignments: SortPreviewAssignment[];
}

export interface TbaReassignRequest {
  tba_numbers: string[];
  destination_zone_id: string;
}

export interface TbaReassignResponse {
  source_zone_id: string;
  destination_zone_id: string;
  moved_tbas: string[];
  source_remaining: number;
  destination_total: number;
}

export interface ArrivalConfirmResponse {
  sort_not_yet_committed: boolean;
  paired_route: RouteResponse | null;
  absorbed_route_numbers: number[];
  trimmed_route_numbers: number[];
  paired_capacity_limit: number;
}

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------

export interface DispatchFillRateResponse {
  summary: {
    total_slots: number;
    algo_slots: number;
    algo_pct: number;
    manual_slots: number;
  };
  by_date: Array<{ date: string; algo: number; manual: number; total: number }>;
}

export interface TrainerLoadRow {
  trainer_id: string;
  trainer_name: string;
  active_trainees: number;
  phases: Record<string, number>;
}

export interface CornerPoint {
  lat: number;
  lng: number;
}

export interface CompanyZone {
  id: string;
  name: string;
  sw_lat: number;
  sw_lng: number;
  ne_lat: number;
  ne_lng: number;
  corners?: CornerPoint[];
}

export interface BanOverrideFreqResponse {
  total_overrides: number;
  weeks: number;
  by_week: Array<{ week_start: string; count: number }>;
}

export interface ConfirmationTimesResponse {
  overall: {
    total_responses: number;
    median_minutes: number | null;
    p90_minutes: number | null;
  };
  by_role: Array<{
    role: string;
    median_minutes: number | null;
    p90_minutes: number | null;
    count: number;
  }>;
}

// My Performance card (ADR-203) — the caller's own field-execution stats.
export interface MyPerformance {
  role: string;
  lifetime_delivered: number;
  lifetime_rts: number;
  lifetime_missing: number;
  success_pct: number | null;
  avg_stars: number | null;
  grade: string | null;
  trips_today: number;
  trips_this_week: number;
  daily_last_week: { day: string; delivered: number; rts: number }[];
  /** `rts` is optional on the wire: a client can outrun the backend that
   *  serves it, exactly as with AssignmentDay.supervised. Read as `?? 0`. */
  weekly_trend: { week_start: string; delivered: number; rts?: number }[];
  rts_reasons_30d: { rts_type: string; count: number }[];
  troublesome_addresses_30d: { normalised_address: string; count: number }[];
}

// Amazon (NYCD) weekly scorecard (ADR-204).
export interface ScorecardMetric {
  id: string;
  key: string;
  label: string;
  value: string;
  unit?: string | null;
  tier?: string | null;
  flag?: 'excellent' | 'needs_focus' | null;
  sort_order: number;
}

export interface Scorecard {
  id: string;
  week: string;
  scope: 'individual' | 'company';
  employee_id?: string | null;
  employee_name?: string | null;
  overall_standing?: string | null;
  source_file_url?: string | null;
  created_at: string;
  metrics: ScorecardMetric[];
}

// Scorecard cross-check (ADR-204 Phase D) — Amazon vs our data.
export interface CrossCheckItem {
  metric: string;
  amazon_value: number | null;
  our_value: number | null;
  delta: number | null;
  contestable: boolean;
  note: string;
}
export interface ScorecardCrossCheck {
  scorecard_id: string;
  week: string;
  week_start: string;
  week_end: string;
  our_delivered: number;
  our_rts: number;
  our_missing: number;
  items: CrossCheckItem[];
  rts_evidence: { rts_type: string; count: number }[];
}

// ── Dashboard DTOs — GENERATED from the backend OpenAPI schema ──────────────
// Do not hand-edit. Regenerate after changing app/schemas/dashboard_summaries.py.
//
// `| null` means the backend could not compute the metric. Render it as "—",
// never 0 — those are different facts. Use utils/metric.ts.

export interface FailureItem {
  item_name: string;
  failure_count: number;
}

export interface IncidentTrendItem {
  date: string;
  count: number;
}

export interface AdminSystemHealthSummary {
  adp_configured: boolean;
  adp_enabled: boolean;
  adp_last_employee_sync?: string | null;
  adp_last_timecard_sync?: string | null;
  adp_status: string;
  adp_verified_employee_count: number;
  flex_last_upload?: string | null;
  flex_data_freshness_hours?: number | null;
  manifest_count_today: number;
  unresolved_misroute_count: number;
}

export interface AdminComplianceSummary {
  graduation_completion_pct?: number | null;
  active_trainee_count: number;
  escalated_trainee_count: number;
  days_since_last_training_record?: number | null;
  vehicle_inspection_pass_rate_7d?: number | null;
  inspections_submitted_7d: number;
  failed_items_trending: FailureItem[];
  incident_7d_count: number;
  incident_30d_trend: IncidentTrendItem[];
  unresolved_incident_count: number;
  critical_incident_count: number;
}

export interface AdminDashboardSummary {
  system_health: AdminSystemHealthSummary;
  compliance: AdminComplianceSummary;
}

export interface ManagementOperationalSummary {
  period: string;
  period_start: string;
  period_end: string;
  total_packages_delivered: number;
  total_packages_assigned: number;
  total_paid_hours?: number | null;
  paid_hours_source: string;
  packages_per_hour?: number | null;
  avg_minutes_per_stop?: number | null;
  delivery_success_rate_pct?: number | null;
  rework_rate_pct?: number | null;
  total_rework_count: number;
  routes_dispatched: number;
  routes_completed: number;
  completion_rate_pct?: number | null;
  on_time_rate_pct?: number | null;
  on_time_reference?: string | null;
  crews_total: number;
  crews_deployed: number;
  crew_utilization_pct?: number | null;
  trend_packages_per_hour?: string | null;
  trend_success_rate?: string | null;
  prior_packages_per_hour?: number | null;
  prior_success_rate_pct?: number | null;
}

export interface NoShowItem {
  employee_name: string;
  role: string;
  count: number;
}

export interface WalkerPerformance {
  employee_name: string;
  avg_rating?: number | null;
  rating_count: number;
  packages_delivered: number;
}

export interface TroubleWalker {
  employee_name: string;
  ncns_count: number;
  late_count: number;
  avg_rating?: number | null;
}

export interface TraineePhaseRow {
  phase: number;
  label: string;
  trainee_count: number;
}

export interface StuckTrainee {
  trainee_name: string;
  phase: number;
  days_in_phase: number;
}

export interface ProblemArea {
  topic_title: string;
  escalated_count: number;
  late_count: number;
  debt_count: number;
}

/** One slice of decline data — a weekday, a truck, or a person.
 *
 *  `rate` is null until the slice clears its volume gate, and that is
 *  load-bearing: render `rate` only when `gated` is false, otherwise show
 *  `declines`. Publishing a one-sample percentage is the exact failure the
 *  backend gate exists to prevent, and null (rather than 0) is what makes the
 *  mistake impossible to make silently. */
export interface DeclineSlice {
  key: string;
  declines: number;
  total: number;
  /** Distinct dates observed. For a weekday slice this is the gate unit. */
  occurrences: number;
  rate?: number | null;
  gated: boolean;
}

export interface DeclineAnalysis {
  start_date: string;
  end_date: string;
  total_confirmations: number;
  total_declines: number;
  by_weekday: DeclineSlice[];
  by_truck: DeclineSlice[];
  by_person: DeclineSlice[];
}

/** Spare capacity per role for TODAY — not the dashboard's selected period.
 *  "Who could I still call" has no meaning averaged over a week. */
export interface CoverageDepth {
  assigned_drivers: number;
  spare_drivers: number;
  assigned_captains: number;
  spare_captains: number;
  assigned_walkers: number;
  spare_walkers: number;
  assigned_trainers: number;
  spare_trainers: number;
  /** True when a truck-critical role (driver/captain) has no spare at all. */
  at_capacity_risk: boolean;
}

export interface ManagementCrewSummary {
  active_trainees: number;
  escalated_trainees: number;
  graduation_completion_pct?: number | null;
  roll_call_total: number;
  roll_call_confirmed_pct?: number | null;
  no_shows_this_period: NoShowItem[];
  top_walkers: WalkerPerformance[];
  trouble_walkers: TroubleWalker[];
  vehicle_inspection_pass_rate_7d?: number | null;
  trainee_phases: TraineePhaseRow[];
  stuck_trainees: StuckTrainee[];
  training_problem_areas: ProblemArea[];
  /** Null when the backend could not compute it — never render a 0 in its place. */
  coverage_depth?: CoverageDepth | null;
}

export interface IncidentCategory {
  category: string;
  count: number;
  avg_per_week_30d: number;
}

export interface ManagementIncidentSummary {
  total_period: number;
  by_severity: Record<string, number>;
  by_category: IncidentCategory[];
  unresolved_count: number;
  oldest_unresolved_age_hours?: number | null;
  rts_pending_count: number;
  avg_rts_review_hours?: number | null;
}

export interface MisroutedHotspot {
  block_key: string;
  count: number;
}

export interface ManagementFleetSummary {
  fleet_planned: number;
  fleet_active: number;
  fleet_completed: number;
  route_avg_duration_hours?: number | null;
  routes_with_timing: number;
  misrouted_count: number;
  misrouted_unresolved: number;
  misrouted_pct_of_packages?: number | null;
  misrouted_hotspots: MisroutedHotspot[];
}

export interface ManagementDashboardSummary {
  operational: ManagementOperationalSummary;
  crew: ManagementCrewSummary;
  incidents: ManagementIncidentSummary;
  fleet: ManagementFleetSummary;
}

export interface DispatchFleetSnapshot {
  timestamp: string;
  dispatch_date: string;
  trucks_planned: number;
  trucks_active: number;
  trucks_completed: number;
  routes_dispatched: number;
  routes_needing_help: number;
  routes_on_time_pct?: number | null;
  manifest_totes: number;
  manifest_ov: number;
  manifest_total: number;
  stops_planned: number;
  stops_in_progress: number;
  stops_completed: number;
  packages_delivered: number;
  avg_packages_per_active_truck?: number | null;
  avg_minutes_per_stop?: number | null;
}

export interface DispatchPendingRequest {
  id: string;
  employee_name: string;
  requested_date: string;
  reason?: string | null;
  created_at: string;
  age_minutes: number;
  is_urgent: boolean;
}

export interface DispatchRtsRequest {
  report_id: string;
  driver_name: string;
  total_rts: number;
  crew_confirmed: boolean;
  submitted_at: string;
  age_minutes: number;
  route_completion_pct?: number | null;
  packages_remaining?: number | null;
  time_in_field_hours?: number | null;
}

export interface DispatchUrgentIncident {
  incident_id: string;
  severity: string;
  category: string;
  truck_id?: string | null;
  reported_at: string;
  age_minutes: number;
}

export interface DispatchActionQueue {
  pending_reassignments: DispatchPendingRequest[];
  rts_requests: DispatchRtsRequest[];
  urgent_incidents: DispatchUrgentIncident[];
}

export interface SlowestRoute {
  route_id: string;
  route_number?: number | null;
  actual_hours: number;
  package_count: number;
  actual_minutes_per_package?: number | null;
  expected_hours?: number | null;
  variance_pct?: number | null;
}

export interface CrewPerformance {
  employee_name: string;
  packages_delivered: number;
  hours?: number | null;
  packages_per_hour?: number | null;
}

export interface DispatchPerformanceSummary {
  baseline_minutes_per_package?: number | null;
  baseline_sample_size: number;
  slowest_routes: SlowestRoute[];
  fastest_crew?: CrewPerformance | null;
  slowest_crew?: CrewPerformance | null;
}

export interface DispatchDashboardSummary {
  fleet_snapshot: DispatchFleetSnapshot;
  action_queue: DispatchActionQueue;
  performance: DispatchPerformanceSummary;
}


// ── Scorecard company trend — GENERATED from the backend OpenAPI schema ──────
// Amazon's weekly scorecard is the number the business is judged on. Values
// arrive as display strings ("100.0%", "PLATINUM"); `value` is the parsed
// number, null when the raw value is a tier word rather than a figure.

export interface MetricTrendPoint {
  week: string;
  value?: number | null;
  raw: string;
  tier?: string | null;
  flag?: string | null;
}

export interface MetricTrend {
  key: string;
  label: string;
  unit?: string | null;
  points: MetricTrendPoint[];
  latest?: number | null;
  previous?: number | null;
  delta?: number | null;
  // Direction is already corrected for lower-is-better metrics (DPMO, driver
  // behaviour), so "up" always means IMPROVED regardless of which way the
  // number moved. Do not re-derive this from delta on the client.
  direction?: string | null;
  weeks_flagged?: number;
}

export interface StandingPoint {
  week: string;
  standing?: string | null;
}

export interface ScorecardTrendResponse {
  weeks: string[];
  standings: StandingPoint[];
  current_standing?: string | null;
  previous_standing?: string | null;
  metrics: MetricTrend[];
  focus_now?: string[];
  missing_weeks?: string[];
}
// ── Scorecard tiers + appeals — GENERATED from the backend OpenAPI schema ───
// Do not hand-edit. Regenerate after changing app/schemas/scorecard*.py.
//
// Access tiers (docs/SCORECARD_ACCESS_MODEL.md): company standing is Tier 1
// (all roles); individual data and appeals are management/admin only.

export interface CompanyStandingCard {
  week?: string | null;
  standing?: string | null;
  previous_standing?: string | null;
  direction?: string | null;
  consecutive_weeks?: number;
  has_data?: boolean;
}

export interface IndividualMetricPoint {
  week: string;
  value?: number | null;
  raw: string;
  flag?: string | null;
}

export interface IndividualMetricTrend {
  key: string;
  label: string;
  unit?: string | null;
  points: IndividualMetricPoint[];
  latest?: number | null;
  previous?: number | null;
  delta?: number | null;
  direction?: string | null;
}

export interface IndividualTrendResponse {
  employee_id?: string | null;
  employee_name?: string | null;
  weeks: string[];
  standings: StandingPoint[];
  current_standing?: string | null;
  metrics: IndividualMetricTrend[];
  focus_now?: string[];
}

export interface IndividualRosterRow {
  employee_id: string;
  employee_name: string;
  employee_role?: string | null;
  latest_week?: string | null;
  standing?: string | null;
  weeks_recorded?: number;
  flagged_metric_count?: number;
  trend_direction?: string | null;
}

export interface IndividualRosterResponse {
  weeks_considered: string[];
  rows: IndividualRosterRow[];
  employees_without_scorecards?: number;
}

/** Evidence attached to one appeal item.
 *  Mirrors the backend's AppealEvidence, which is `extra="forbid"` — an
 *  unrecognised key is a 422, not a silent write. Was Record<string, unknown>
 *  on both sides; the shape was always known, the latitude was accidental. */
export interface AppealEvidence {
  rts_reasons: { rts_type: string; count: number }[];
}

export interface AppealItemIn {
  metric_key: string;
  metric_label: string;
  amazon_value?: string | null;
  our_value?: string | null;
  delta?: number | null;
  evidence?: AppealEvidence | null;
  claim?: string | null;
  sort_order?: number;
}

export interface AppealItemOut {
  metric_key: string;
  metric_label: string;
  amazon_value?: string | null;
  our_value?: string | null;
  delta?: number | null;
  evidence?: AppealEvidence | null;
  claim?: string | null;
  sort_order?: number;
  id: string;
  outcome: string;
  outcome_notes?: string | null;
  corrected_value?: string | null;
}

export interface AppealItemResolve {
  outcome: "accepted" | "rejected";
  corrected_value?: string | null;
  outcome_notes?: string | null;
}

export interface AppealCreate {
  scorecard_id: string;
  title?: string | null;
  rationale?: string | null;
  items?: AppealItemIn[];
}

export interface AppealUpdate {
  title?: string | null;
  rationale?: string | null;
  items?: AppealItemIn[] | null;
}

export interface AppealSubmit {
  amazon_reference?: string | null;
}

export interface AppealResolve {
  outcome: "won" | "lost" | "withdrawn";
  outcome_notes?: string | null;
}

export interface AppealOut {
  id: string;
  company_id: string;
  scorecard_id: string;
  week: string;
  scope: string;
  employee_id?: string | null;
  employee_name?: string | null;
  status: string;
  title?: string | null;
  rationale?: string | null;
  submitted_at?: string | null;
  submitted_by_name?: string | null;
  amazon_reference?: string | null;
  resolved_at?: string | null;
  resolved_by_name?: string | null;
  outcome_notes?: string | null;
  created_by_name?: string | null;
  created_at: string;
  items?: AppealItemOut[];
}

export interface AppealListItem {
  id: string;
  scorecard_id: string;
  week: string;
  scope: string;
  employee_name?: string | null;
  status: string;
  title?: string | null;
  item_count?: number;
  items_accepted?: number;
  submitted_at?: string | null;
  resolved_at?: string | null;
  created_at: string;
}

export interface MetricTally {
  metric: string;
  count: number;
}

export interface AppealStats {
  total?: number;
  draft?: number;
  submitted?: number;
  won?: number;
  lost?: number;
  withdrawn?: number;
  win_rate_pct?: number | null;
  most_appealed_metrics?: MetricTally[];
  most_won_metrics?: MetricTally[];
}


// ── Package lookup (ADR-245) — GENERATED from the backend OpenAPI schema ────
// Operational TBA tracking for dispatch. Distinct from the Tier 3 appeal
// evidence search; no address fields by design (Dimension 7 / ADR-219).

export interface AssignmentTrace {
  route_id: string;
  route_number?: number | null;
  route_date: string;
  route_status?: string | null;
  walker_id?: string | null;
  walker_name?: string | null;
  truck_name?: string | null;
}

export interface DeliveryTrace {
  stop_id: string;
  status: string;
  stop_sequence?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  walker_id?: string | null;
  walker_name?: string | null;
  recorded_by_name?: string | null;
  packages_delivered?: number | null;
}

export interface ExceptionTrace {
  source: string;
  recorded_at?: string | null;
  route_date?: string | null;
  walker_name?: string | null;
  recorded_by_name?: string | null;
  rts_type?: string | null;
  rts_explanation?: string | null;
  is_reattemptable?: boolean | null;
  resolution_status?: string | null;
  damage_stage?: string | null;
  notes?: string | null;
}

export interface PackageTimeline {
  tba_number: string;
  current_holder_name?: string | null;
  current_holder_id?: string | null;
  holder_basis?: string | null;
  assignments?: AssignmentTrace[];
  deliveries?: DeliveryTrace[];
  exceptions?: ExceptionTrace[];
}

export interface PackageLookupResponse {
  query: string;
  matched_on: string;
  ambiguous?: boolean;
  results?: PackageTimeline[];
}


// ---------------------------------------------------------------------------
// Unregistered package intake (ADR-246)
// ---------------------------------------------------------------------------

export interface IntakeCandidate {
  route_id: string;
  route_number: number | null;
  walker_name: string | null;
  status: string | null;
  can_accept: boolean;
  /** address | block_key | near_segment | near_block — how the route matched. */
  match: string;
  /**
   * How far, in the unit of the tier that matched (ADR-260): graph hops for
   * near_segment, blocks for near_block. Null on an exact match. The units
   * differ, so render via matchLabel() rather than showing the bare number.
   */
  distance: number | null;
  is_adders_route: boolean;
}

export interface IntakeAssessmentOut {
  in_zone: boolean;
  /** False when we lack coords or a boundary. Distinct from in_zone=false:
   *  we cannot prove the package is foreign, so it escalates to dispatch. */
  decidable: boolean;
  zone_reason: string | null;
  best_fit: IntakeCandidate | null;
  adders_route: IntakeCandidate | null;
  candidates: IntakeCandidate[];
  /**
   * best_fit_in_progress:{n} — the closest route had left, so a further one
   *   that could still accept took it.
   * all_departed:{n} — EVERY nearby route had left; the package was placed
   *   anyway because it still has to go out today (ADR-260). Candidates will
   *   all read can_accept: false.
   */
  absorbed_reason: string | null;
  /** Whether ANY route exists for the date. Distinguishes "the day is not
   *  sorted yet" from "no route is near enough" when candidates is empty. */
  routes_exist: boolean;
}

export type IntakeOutcome = 'added' | 'duplicate' | 'removal' | 'needs_dispatch';

export interface PackageIntakeResponse {
  outcome: IntakeOutcome;
  tba: string;
  route_id: string | null;
  route_number: number | null;
  walker_name: string | null;
  stop_id: string | null;
  removal_id: string | null;
  reason: string | null;
  /** Set on outcome="duplicate" — the holder is named rather than the caller
   *  simply being refused (ADR-246). */
  existing_holder: string | null;
  existing_route_number: number | null;
  assessment: IntakeAssessmentOut | null;
}

/** OCR of a label photo — a SUGGESTION. Both fields stay editable, and
 *  needs_manual_entry / confidence let the UI ask for eyes rather than
 *  presenting a shaky read as fact (ADR-246). */
export interface LabelReadResponse {
  tba: string | null;
  address_line: string | null;
  confidence: number | null;
  needs_manual_entry: boolean;
  lines: string[];
  warnings: string[];
}

export interface FieldAddedPackage {
  tba: string;
  route_id: string | null;
  route_number: number | null;
  walker_name: string | null;
  added_by_name: string | null;
  added_at: string;
  outcome: string;
  is_unplanned: boolean;
}

export interface FieldAddedResponse {
  route_date: string;
  total: number;
  packages: FieldAddedPackage[];
}

// ── Assignment history (ADR-268) ─────────────────────────────────────────────

export interface HistoryCrewMember {
  name: string;
  /** The SLOT held that day, not the job title — a captain may ride as a
   *  walker (ADR-256 D2). */
  role: string;
}

export interface HistoryRTSDetail {
  tba_number: string;
  rts_type: string;
  rts_explanation: string;
  is_reattemptable: boolean;
  /** Null once ADR-219's 48h window has closed. Not an error — check
   *  `address_detail` on the day before treating it as missing data. */
  normalised_address: string | null;
}

export interface AssignmentDay {
  route_date: string;
  truck_name: string | null;
  slot_role: string;
  crew: HistoryCrewMember[];
  route_numbers: number[];

  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;

  effort_class: string | null;
  rts_rate: number | null;
  /**
   * rts_rate divided by the company rate for the SAME effort_class.
   * 1.0 = exactly typical for a route of that difficulty.
   *
   * ALWAYS prefer this over rts_rate when comparing people. Raw rate is
   * confounded by difficulty — measured 2.10% on easy routes vs 10.81% on
   * heavy ones, a 5x spread the walker does not control. Null when the class
   * lacks the volume to be a trustworthy denominator.
   */
  rts_rate_vs_class: number | null;

  rts_details: HistoryRTSDetail[];
  /** 'street' while addresses survive, 'block' after ADR-219 nulls them. */
  address_detail: 'street' | 'block';
  /**
   * Whose numbers the counts are.
   *   'truck' — driver/captain; they answer for the whole load
   *   'own'   — walker/trainer/trainee; only the stops they executed
   * MUST be labelled in the UI. A walker's 142 and a driver's 2,865 are
   * different measurements, and rendering them identically was the bug.
   */
  counts_scope: 'truck' | 'own';
  /**
   * Trainees the caller was PAIRED with on this date (ADR-269).
   *
   * Empty for every role except a trainer who was actually paired that day —
   * the pairing IS the authorisation, so this is never a filtered view of a
   * longer list. Render SEPARATELY from the counts above; merging them
   * resurrects the ADR-244 attribution bug.
   *
   * OPTIONAL ON THE WIRE. The client ships ahead of the backend it talks to,
   * so during a deploy window — or against any older API — this field is
   * absent. Typing it as required turned `day.supervised.map()` into a hard
   * render crash for EVERY user, not just trainers. Any newly-added response
   * field is missing from some running server until that server is updated.
   * Read it as `day.supervised ?? []`.
   */
  supervised?: SupervisedDay[];
}

/**
 * A paired trainee's day, as their trainer sees it (ADR-269).
 *
 * The same block the trainee sees for themselves, RTS details included:
 * during training the trainer answers for items on this record, and a bare
 * count cannot support that conversation. Counts are the trainee's OWN
 * executed stops, never the truck total.
 */
export interface SupervisedDay {
  employee_id: string;
  name: string;
  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  rts_rate: number | null;
  /** Prefer this over rts_rate — same difficulty confound as the parent day. */
  rts_rate_vs_class: number | null;
  rts_details: HistoryRTSDetail[];
}

export interface AssignmentHistoryResponse {
  employee_id: string;
  start_date: string;
  end_date: string;
  days: AssignmentDay[];
}

// ── Dispatch day replay (ADR-268) ────────────────────────────────────────────

export interface ReplayMemberOutcome {
  employee_id: string;
  name: string;
  slot_role: string;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  /**
   * True for driver/captain. Their line is the TRUCK's load, not their own
   * stops. The UI must say so — otherwise the row reads as one person who
   * delivered thirty times more than everyone else.
   */
  is_truck_lead: boolean;
}

export interface ReplayTruckOutcome {
  truck_id: string;
  truck_name: string | null;
  route_numbers: number[];
  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  effort_class: string | null;
  crew: ReplayMemberOutcome[];
  /** {rts_type: count} for the whole truck. */
  rts_reasons: Record<string, number>;
}

export interface DayReplay {
  route_date: string;
  trucks: ReplayTruckOutcome[];
  /**
   * Summed from the TRUCK rows, never the crew lines: a lead's line already
   * contains the whole load, so adding crew together double-counts every
   * package. Measured on staging: crew lines summed to 5,730 against a real
   * day total of 2,865.
   */
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
}

// ── My Stats drill-down (ADR-271) ───────────────────────────────────────────

/** One completed day. NEVER today — the series ends yesterday so the payload
 *  is immutable once fetched, which is what makes client-side caching safe. */
export interface DayStat {
  d: string;
  delivered: number;
  total: number;
  rts: number;
  missing: number;
  /** Packages the person brought back DAMAGED — a SUBSET of `rts`, since
   *  package_damaged is one of the six RTS_TYPES. Never add the two. */
  damaged: number;
  /** Damage reported on their truck pre-delivery. A different event from
   *  `damaged`; the UI must not sum them. Populated for driver/captain only. */
  truck_damaged: number;
  effort: string | null;
  /** Per-day reason mix, {abbreviated_rts_type: count}. Folded into the bulk
   *  payload so every level's donut is a client-side sum (ADR-271 B). */
  rz: Record<string, number>;
  /** Roll-call status for the day, or null if none recorded. */
  rc: string | null;
}

export interface StatsSeries {
  start_date: string;
  /** Always yesterday. */
  end_date: string;
  role: string;
  days: DayStat[];
}

export interface LifetimeTotals {
  delivered: number;
  rts: number;
  missing: number;
  damaged: number;
  truck_damaged: number;
  trips: number;
  /** Null, never 0, when nothing has been attempted. */
  success_pct: number | null;
}

/** Per calendar year, ALL TIME — computed server-side because the daily series
 *  is capped at 24 months and the lifetime chart is year-over-year. */
export interface YearStat {
  year: number;
  delivered: number;
  total: number;
  rts: number;
  missing: number;
  damaged: number;
  truck_damaged: number;
}

export interface MyStats {
  lifetime: LifetimeTotals;
  years: YearStat[];
  series: StatsSeries;
}

/** One block worked in the selected period. `block_key` survives ADR-219's
 *  address purge, so it carries no PII. */
export interface BlockStat {
  block_key: string;
  stops: number;
  delivered: number;
  rts: number;
  /** Null, never 0, when nothing was attempted there. */
  rts_rate: number | null;
}

export interface Attendance {
  present: number;
  late: number;
  ncns: number;
  total: number;
  /** Null when nothing was recorded — "no roll calls" is not "0% attendance". */
  rate: number | null;
}

/** Scoped to ONE period: "top 5 for week 1 may not be top 5 for the month",
 *  so this cannot be precomputed into the cached series. Requested from WEEK
 *  outward only — at a single day "top blocks" is just "the blocks you
 *  worked", which belongs in the day detail. */
/** One RTS reason within the selected period. */
export interface ReasonStat {
  rts_type: string;
  count: number;
}

export interface PeriodExtras {
  start_date: string;
  end_date: string;
  top_blocks: BlockStat[];
  attendance: Attendance;
  /** Why packages came back this period. Scoped like the counts: a driver's
   *  mix covers the whole truck, a walker's covers what they carried. */
  reasons: ReasonStat[];
  /** False for driver/captain: blocks come from the stop's executor and a
   *  driver does not carry, so HIDE the panel rather than render it empty. */
  blocks_apply: boolean;
}
