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
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

export interface CrewMember {
  employee_id: string;
  name: string;
  role: string;
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
  truck_name: string;
  submitted_at: string;
  has_failures: boolean;
  failed_items: string[];
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
  location: string;
  eta: string | null;
  notes: string | null;
  submitted_at: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

// ---------------------------------------------------------------------------
// Walker Performance
// ---------------------------------------------------------------------------

export interface WalkerSummary {
  walker_id: string;
  walker_name: string;
  total_shifts: number;
  present_shifts: number;
  no_show_count: number;
  avg_stars: number | null;
  presence_rate: number | null;
  grade: 'A' | 'B' | 'C' | 'D' | 'F' | null;
  grade_eligible: boolean;
}

export interface WalkerRatingDetail {
  id: string;
  date: string;
  driver_id: string;
  driver_name: string;
  present: boolean;
  stars: number | null;
  comment: string | null;
  rated_at: string;
}

export interface WalkerProfile extends WalkerSummary {
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
