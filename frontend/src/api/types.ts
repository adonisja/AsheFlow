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
  truck_assignments?: { truck_id: string; status: string }[];
  workflow_status?: 'dispatched' | 'published' | 'finalized';
  warnings: DispatchWarning[];
}

export interface UnavailableStaff {
  id: string;
  name: string;
  role: string;
  discord_id: string;
  phone_number: string | null;
  reason: 'time_off_request' | 'recurring_off_day';
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

export interface MisroutedPackageOut {
  id?: string;
  tba_number: string;
  current_bag_id: string;
  destination_block_key: string | null;
  normalised_address?: string | null;
  suggested_route_number: number | null;
}

/** One delivery stop — a unique address with its packages (ADR-194).
 *  Server-sorted: blocks ascending, house numbers ascending within a block. */
export interface RouteStop {
  block_key: string;
  address: string;
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
  created_at: string;
  misrouted_packages: MisroutedPackageOut[];
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
  building_type_status: 'pending' | 'verified' | 'locked';
  building_type_agreement_count: number;
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
  weekly_trend: { week_start: string; delivered: number }[];
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
