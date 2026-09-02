import { errorText } from '../utils/errorText';
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Settings, Clock, BookOpen, Truck, Star, CheckSquare,
  Save, RefreshCw, CheckCircle2, AlertTriangle, RotateCcw,
  MessageSquare, MapPin, HelpCircle, Plus, Trash2,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import SettingsHelpDrawer from '../components/ui/SettingsHelpDrawer';
import { useAuth } from '../contexts/AuthContext';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CompanyConfig {
  id: string;
  company_id: string;
  is_configured: boolean;
  shift_start: string | null;
  shift_end: string | null;
  checkin_open: string | null;
  checkin_close: string | null;
  dispatch_confirmation_cutoff: string | null;
  rating_window_hours: number | null;
  graduation_assignments: number | null;
  debt_escalation_threshold: number | null;
  phase4_pass_score: number | null;
  underperforming_trainer_threshold: number | null;
  max_training_phase: number | null;
  dispatch_weight_driver: number | null;
  dispatch_weight_trainer: number | null;
  dispatch_weight_walker: number | null;
  dispatch_mutual_bonus: number | null;
  dispatch_tridirectional_bonus: number | null;
  dispatch_consecutive_penalty: number | null;
  dispatch_weight_cap: number | null;
  flag_threshold: number | null;
  driver_checkin_count: number | null;
  late_window_minutes: number | null;
  ncns_cutoff_minutes: number | null;
  effort_time_factor: number | null;
  effort_physical_factor: number | null;
  ingestion_mode: string | null;
  // Amazon scorecard tier targets (ADR-262). null = no target configured; the
  // scorecard shows the reported value with no pass/fail judgement.
  scorecard_dcr_target: number | null;
  scorecard_dnr_dpmo_target: number | null;
  scorecard_pod_target: number | null;
  scorecard_cc_target: number | null;
  scorecard_cdf_target: number | null;
  scorecard_dsb_dpmo_target: number | null;
  scorecard_fico_target: number | null;
  scorecard_speeding_rate_target: number | null;
  scorecard_signsignal_rate_target: number | null;
  scorecard_dvic_target: number | null;
}

interface DiscordConfig {
  discord_guild_id: number | null;
  discord_drivers_channel_id: number | null;
  discord_trainers_channel_id: number | null;
  discord_captains_channel_id: number | null;
  discord_general_channel_id: number | null;
  discord_invite_channel_id: number | null;
  discord_role_admin: number | null;
  discord_role_manager: number | null;
  discord_role_asheflow: number | null;
  discord_role_bot: number | null;
  discord_role_dispatch: number | null;
  discord_role_driver: number | null;
  discord_role_trainer: number | null;
  discord_role_captain: number | null;
  discord_role_walker: number | null;
}

// ---------------------------------------------------------------------------
// Field metadata
// ---------------------------------------------------------------------------

type FieldType = 'time' | 'int' | 'float' | 'select' | 'bigint';

interface FieldMeta {
  key: string;
  label: string;
  description: string;
  placeholder: string;
  type: FieldType;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
}

const SHIFT_TIMING: FieldMeta[] = [
  { key: 'shift_start', label: 'Shift Start', type: 'time', description: 'Time drivers must be on-site.', placeholder: '07:00' },
  { key: 'shift_end', label: 'Shift End', type: 'time', description: 'Expected shift close time.', placeholder: '18:00' },
  { key: 'checkin_open', label: 'Check-in Opens', type: 'time', description: 'Earliest accepted morning check-in.', placeholder: '06:30' },
  { key: 'checkin_close', label: 'Check-in Closes', type: 'time', description: 'Late submissions after this are flagged.', placeholder: '07:45' },
  { key: 'dispatch_confirmation_cutoff', label: 'Confirmation Cutoff', type: 'time', description: 'Deadline for employees to accept/decline dispatch assignments.', placeholder: '09:00' },
];

const TRAINING_RULES: FieldMeta[] = [
  { key: 'graduation_assignments', label: 'Graduation Threshold (days)', type: 'int', required: true, description: 'Clean dispatch days needed to graduate.', placeholder: '5', min: 1, max: 30 },
  { key: 'debt_escalation_threshold', label: 'Debt Escalation Threshold', type: 'int', required: true, description: 'Days a task stays incomplete before escalating.', placeholder: '3', min: 1, max: 30 },
  { key: 'phase4_pass_score', label: 'Phase 4 Pass Score (%)', type: 'float', required: true, description: 'Minimum Phase 4 score to advance.', placeholder: '90', min: 0, max: 100, step: 0.1 },
  { key: 'underperforming_trainer_threshold', label: 'Underperforming Trainer Threshold', type: 'int', required: true, description: 'Low-scoring sessions before trainer is flagged.', placeholder: '3', min: 1, max: 30 },
  { key: 'max_training_phase', label: 'Max Training Phase', type: 'int', required: true, description: 'Total number of training phases.', placeholder: '4', min: 1, max: 10 },
];

const DISPATCH_WEIGHTS: FieldMeta[] = [
  { key: 'dispatch_weight_driver', label: 'Driver Preference Weight', type: 'float', required: true, description: 'Influence of driver preference history.', placeholder: '0.70', min: 0, max: 1, step: 0.01 },
  { key: 'dispatch_weight_trainer', label: 'Trainer Preference Weight', type: 'float', required: true, description: 'Influence of trainer preference history.', placeholder: '0.50', min: 0, max: 1, step: 0.01 },
  { key: 'dispatch_weight_walker', label: 'Walker Preference Weight', type: 'float', required: true, description: 'Influence of walker preference history.', placeholder: '0.30', min: 0, max: 1, step: 0.01 },
  { key: 'dispatch_mutual_bonus', label: 'Mutual Preference Bonus', type: 'float', required: true, description: 'Score bonus for mutual two-way preferences.', placeholder: '0.10', min: 0, max: 1, step: 0.01 },
  { key: 'dispatch_tridirectional_bonus', label: 'Three-Way Preference Bonus', type: 'float', required: true, description: 'Score bonus for all-three-way mutual preferences.', placeholder: '0.20', min: 0, max: 1, step: 0.01 },
  { key: 'dispatch_consecutive_penalty', label: 'Consecutive Truck Penalty', type: 'float', required: true, description: 'Deduction for same crew on same truck back-to-back.', placeholder: '0.05', min: 0, max: 1, step: 0.01 },
  { key: 'dispatch_weight_cap', label: 'Max Preference Score Cap', type: 'float', required: true, description: 'Ceiling on any preference score contribution.', placeholder: '0.85', min: 0, max: 1, step: 0.01 },
];

const WALKER_RATING: FieldMeta[] = [
  { key: 'rating_window_hours', label: 'Rating Window (hours)', type: 'int', required: true, description: 'Hours after departure ratings can be submitted.', placeholder: '6', min: 1, max: 48 },
  { key: 'flag_threshold', label: 'Rating Flag Threshold', type: 'float', required: true, description: 'Deviation from average that triggers an anomaly flag.', placeholder: '1.0', min: 0, max: 10, step: 0.1 },
];

// ADR-198/228: attendance windows drive NCNS + the check-in-deadline ordering
// guard. NCNS cutoff must be set before check-in deadlines are accepted, and
// Check-In #1 can't be earlier than it (both minutes past shift start).
const ATTENDANCE: FieldMeta[] = [
  { key: 'late_window_minutes', label: 'Late Window (min)', type: 'int', description: 'Minutes past shift start before a crew arrival counts as “late” (not yet NCNS).', placeholder: '20', min: 0, max: 240 },
  { key: 'ncns_cutoff_minutes', label: 'NCNS Cutoff (min)', type: 'int', description: 'Minutes past shift start (auto-extends on a late station AP) before an unaccounted crew member is NCNS. Set this BEFORE adding check-in deadlines.', placeholder: '60', min: 1, max: 480 },
];

const EFFORT_SCORING: FieldMeta[] = [
  { key: 'effort_time_factor', label: 'Effort Time Factor', type: 'float', description: 'Weight for time-based effort in route scoring (0–1).', placeholder: '0.5', min: 0, max: 1, step: 0.05 },
  { key: 'effort_physical_factor', label: 'Effort Physical Factor', type: 'float', description: 'Weight for physical-based effort in route scoring (0–1).', placeholder: '0.5', min: 0, max: 1, step: 0.05 },
];

// Amazon scorecard tier targets (ADR-262). Leave blank if you have not confirmed
// the number against your own station's card — a blank target means "no
// judgement", which is correct, whereas a guessed one silently mislabels every
// week. The placeholders are industry-typical values from third-party DSP
// guides, NOT Amazon-published figures: Amazon sets several per station.
//
// Direction is deliberately spelled out in each description because the card
// mixes floors and ceilings, and reading a DPMO row as higher-is-better is the
// single most common scorecard misreading.
const SCORECARD_QUALITY: FieldMeta[] = [
  { key: 'scorecard_dcr_target', label: 'DCR Target (%)', type: 'float', description: 'Delivery Completion Rate. Higher is better. Pass at or above this.', placeholder: '99.0', min: 0, max: 100, step: 0.1 },
  { key: 'scorecard_pod_target', label: 'POD Target (%)', type: 'float', description: 'Photo on Delivery usable-photo rate. Higher is better.', placeholder: '97.0', min: 0, max: 100, step: 0.1 },
  { key: 'scorecard_cc_target', label: 'Contact Compliance Target (%)', type: 'float', description: 'Required in-app customer contacts made. Higher is better.', placeholder: '98.0', min: 0, max: 100, step: 0.1 },
  { key: 'scorecard_cdf_target', label: 'CDF Target (%)', type: 'float', description: 'Customer Delivery Feedback positive rate. Higher is better.', placeholder: '84.9', min: 0, max: 100, step: 0.1 },
  { key: 'scorecard_dnr_dpmo_target', label: 'DNR DPMO Ceiling', type: 'int', description: 'Delivered-Not-Received defects per million. LOWER is better — pass at or below this.', placeholder: '950', min: 0, max: 1000000 },
  { key: 'scorecard_dsb_dpmo_target', label: 'DSB DPMO Ceiling', type: 'int', description: 'Delivery Success Behaviors defects per million. LOWER is better.', placeholder: '', min: 0, max: 1000000 },
];

const SCORECARD_SAFETY: FieldMeta[] = [
  { key: 'scorecard_fico_target', label: 'FICO Target', type: 'int', description: 'Safe Driving Score, 100–850. Higher is better. Driver track only.', placeholder: '800', min: 100, max: 850 },
  { key: 'scorecard_dvic_target', label: 'DVIC Compliance Target (%)', type: 'float', description: 'Pre/post-trip inspections completed. Higher is better.', placeholder: '95.0', min: 0, max: 100, step: 0.1 },
  { key: 'scorecard_speeding_rate_target', label: 'Speeding Rate Ceiling (per 100 trips)', type: 'float', description: 'LOWER is better. Pass at or below this.', placeholder: '10.0', min: 0, max: 1000, step: 0.1 },
  { key: 'scorecard_signsignal_rate_target', label: 'Sign/Signal Rate Ceiling (per 100 trips)', type: 'float', description: 'Stop-light violations weigh ~10x a stop sign. LOWER is better.', placeholder: '15.0', min: 0, max: 1000, step: 0.1 },
];

const INGESTION: FieldMeta[] = [
  {
    key: 'ingestion_mode', label: 'Ingestion Mode', type: 'select',
    description: 'How daily manifests are ingested.',
    placeholder: 'file',
    options: [
      { value: 'file', label: 'File Upload (manual)' },
      { value: 'api', label: 'API Integration (automatic)' },
    ],
  },
];

const DISCORD_CHANNELS: FieldMeta[] = [
  { key: 'discord_guild_id', label: 'Server ID (Guild ID)', type: 'bigint', description: 'Numeric ID of your Discord server.', placeholder: '1234567890123456789' },
  { key: 'discord_drivers_channel_id', label: 'Drivers Channel', type: 'bigint', description: 'Channel for driver dispatch notifications.', placeholder: '' },
  { key: 'discord_trainers_channel_id', label: 'Trainers Channel', type: 'bigint', description: 'Channel for trainer assignments and updates.', placeholder: '' },
  { key: 'discord_captains_channel_id', label: 'Captains Channel', type: 'bigint', description: "Channel where the day's captain roster is posted at finalize.", placeholder: '' },
  { key: 'discord_general_channel_id', label: 'General Channel', type: 'bigint', description: 'Fallback channel for company-wide announcements.', placeholder: '' },
  { key: 'discord_invite_channel_id', label: 'Invite Channel', type: 'bigint', description: 'Channel where new invite links are posted.', placeholder: '' },
];

const DISCORD_ROLES: FieldMeta[] = [
  { key: 'discord_role_admin', label: 'Admin Role', type: 'bigint', description: 'Discord role ID for admin employees.', placeholder: '' },
  { key: 'discord_role_manager', label: 'Manager Role', type: 'bigint', description: 'Discord role ID for management employees.', placeholder: '' },
  { key: 'discord_role_dispatch', label: 'Dispatch Role', type: 'bigint', description: 'Discord role ID for dispatch employees.', placeholder: '' },
  { key: 'discord_role_driver', label: 'Driver Role', type: 'bigint', description: 'Discord role ID for driver employees.', placeholder: '' },
  { key: 'discord_role_walker', label: 'Walker Role', type: 'bigint', description: 'Discord role ID for walker employees.', placeholder: '' },
  { key: 'discord_role_trainer', label: 'Trainer Role', type: 'bigint', description: 'Discord role ID for trainers. This role was previously named "Captain" in Discord — see the Captain Role below.', placeholder: '' },
  { key: 'discord_role_captain', label: 'Captain Role', type: 'bigint', description: 'Discord role ID for captains (truck route leads). Distinct from the Trainer role above.', placeholder: '' },
  { key: 'discord_role_asheflow', label: 'AsheFlow Bot Role', type: 'bigint', description: 'Role assigned to the AsheFlow bot.', placeholder: '' },
  { key: 'discord_role_bot', label: 'Generic Bot Role', type: 'bigint', description: 'Shared bot role if used in your server.', placeholder: '' },
];

// ---------------------------------------------------------------------------
// Field sets for serialisation
// ---------------------------------------------------------------------------

const CONFIG_KEYS: string[] = [
  'shift_start', 'shift_end', 'checkin_open', 'checkin_close', 'dispatch_confirmation_cutoff',
  'rating_window_hours', 'graduation_assignments', 'debt_escalation_threshold',
  'phase4_pass_score', 'underperforming_trainer_threshold', 'max_training_phase',
  'dispatch_weight_driver', 'dispatch_weight_trainer', 'dispatch_weight_walker',
  'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus', 'dispatch_consecutive_penalty',
  'dispatch_weight_cap', 'flag_threshold', 'driver_checkin_count',
  'late_window_minutes', 'ncns_cutoff_minutes',
  'effort_time_factor', 'effort_physical_factor', 'ingestion_mode',
  'scorecard_dcr_target', 'scorecard_dnr_dpmo_target', 'scorecard_pod_target',
  'scorecard_cc_target', 'scorecard_cdf_target', 'scorecard_dsb_dpmo_target',
  'scorecard_fico_target', 'scorecard_speeding_rate_target',
  'scorecard_signsignal_rate_target', 'scorecard_dvic_target',
];

const DISCORD_KEYS: string[] = [
  'discord_guild_id', 'discord_drivers_channel_id', 'discord_trainers_channel_id',
  'discord_captains_channel_id', 'discord_general_channel_id', 'discord_invite_channel_id',
  'discord_role_admin', 'discord_role_manager', 'discord_role_asheflow',
  'discord_role_bot', 'discord_role_dispatch', 'discord_role_driver',
  'discord_role_trainer', 'discord_role_captain', 'discord_role_walker',
];

const TIME_FIELDS = new Set(['shift_start', 'shift_end', 'checkin_open', 'checkin_close', 'dispatch_confirmation_cutoff']);
const INT_FIELDS = new Set([
  'rating_window_hours', 'graduation_assignments', 'debt_escalation_threshold',
  'underperforming_trainer_threshold', 'max_training_phase', 'driver_checkin_count',
  'late_window_minutes', 'ncns_cutoff_minutes',
  'scorecard_dnr_dpmo_target', 'scorecard_dsb_dpmo_target', 'scorecard_fico_target',
]);
const FLOAT_FIELDS = new Set([
  'phase4_pass_score', 'dispatch_weight_driver', 'dispatch_weight_trainer',
  'dispatch_weight_walker', 'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus',
  'dispatch_consecutive_penalty', 'dispatch_weight_cap', 'flag_threshold',
  'effort_time_factor', 'effort_physical_factor',
  'scorecard_dcr_target', 'scorecard_pod_target', 'scorecard_cc_target',
  'scorecard_cdf_target', 'scorecard_speeding_rate_target',
  'scorecard_signsignal_rate_target', 'scorecard_dvic_target',
]);
const STRING_FIELDS = new Set(['ingestion_mode']);

const REQUIRED_KEYS = new Set([
  'rating_window_hours', 'graduation_assignments', 'debt_escalation_threshold',
  'phase4_pass_score', 'underperforming_trainer_threshold', 'max_training_phase',
  'dispatch_weight_driver', 'dispatch_weight_trainer', 'dispatch_weight_walker',
  'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus', 'dispatch_consecutive_penalty',
  'dispatch_weight_cap', 'flag_threshold',
]);

function configToFormValues(config: CompanyConfig): Record<string, string> {
  const result: Record<string, string> = {};
  for (const k of CONFIG_KEYS) {
    const v = (config as any)[k];
    result[k] = v !== null && v !== undefined ? String(v) : '';
  }
  return result;
}

function discordToFormValues(config: DiscordConfig): Record<string, string> {
  const result: Record<string, string> = {};
  for (const k of DISCORD_KEYS) {
    const v = (config as any)[k];
    result[k] = v !== null && v !== undefined ? String(v) : '';
  }
  return result;
}

function formValuesToPayload(values: Record<string, string>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const [k, raw] of Object.entries(values)) {
    if (raw === '' || raw === null || raw === undefined) continue;
    if (TIME_FIELDS.has(k)) {
      payload[k] = raw;
    } else if (INT_FIELDS.has(k)) {
      const n = parseInt(raw, 10);
      if (!isNaN(n)) payload[k] = n;
    } else if (FLOAT_FIELDS.has(k)) {
      const n = parseFloat(raw);
      if (!isNaN(n)) payload[k] = n;
    } else if (STRING_FIELDS.has(k)) {
      payload[k] = raw;
    }
  }
  return payload;
}

function discordValuesToPayload(values: Record<string, string>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const [k, raw] of Object.entries(values)) {
    if (raw === '' || raw === null || raw === undefined) continue;
    // Send as string — Discord snowflake IDs exceed Number.MAX_SAFE_INTEGER.
    // Pydantic coerces string → int on the backend without precision loss.
    if (/^\d+$/.test(raw)) payload[k] = raw;
  }
  return payload;
}

function missingRequired(values: Record<string, string>): string[] {
  return [...REQUIRED_KEYS].filter(k => !values[k]);
}

// ---------------------------------------------------------------------------
// ConfigSection component
// ---------------------------------------------------------------------------

interface SectionProps {
  title: string;
  icon: React.ElementType;
  fields: FieldMeta[];
  values: Record<string, string>;
  onChange: (key: string, val: string) => void;
  onHelp: (key: string) => void;
  isOnboarding?: boolean;
}

function ConfigSection({ title, icon: Icon, fields, values, onChange, onHelp, isOnboarding }: SectionProps) {
  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary/10">
          <Icon className="w-4 h-4 text-primary" />
        </div>
        <h3 className="font-semibold text-sm">{title}</h3>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
        {fields.map(field => (
          <div key={field.key}>
            <label className="flex items-center gap-1 text-xs font-medium text-foreground mb-1">
              {field.label}
              {isOnboarding && field.required && (
                <span className="text-danger ml-0.5">*</span>
              )}
              <button
                type="button"
                onClick={() => onHelp(field.key)}
                className="ml-0.5 text-muted-foreground hover:text-primary transition-colors"
                tabIndex={-1}
                aria-label={`Help for ${field.label}`}
              >
                <HelpCircle className="w-3 h-3" />
              </button>
            </label>

            {field.type === 'select' && field.options ? (
              <select
                className="input-field"
                value={values[field.key] ?? ''}
                onChange={e => onChange(field.key, e.target.value)}
              >
                <option value="">— select —</option>
                {field.options.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            ) : (
              <input
                className="input-field"
                type={field.type === 'time' ? 'text' : 'number'}
                value={values[field.key] ?? ''}
                onChange={e => onChange(field.key, e.target.value)}
                placeholder={field.placeholder}
                min={field.min}
                max={field.max}
                step={field.step ?? (field.type === 'bigint' ? 1 : undefined)}
              />
            )}

            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              {field.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Check-in deadline editor (ADR-228)
// ---------------------------------------------------------------------------

interface CheckInDeadline { id: string; sequence: number; offset_minutes: number; }

// shift_start "HH:MM" + offset minutes → clock-time helper label "8:30 AM".
function offsetToClock(shiftStart: string | undefined, offset: number): string | null {
  if (!shiftStart || !/^\d{1,2}:\d{2}$/.test(shiftStart)) return null;
  const [h, m] = shiftStart.split(':').map(Number);
  const total = h * 60 + m + offset;
  const hh = Math.floor((total % 1440) / 60);
  const mm = total % 60;
  const ampm = hh < 12 ? 'AM' : 'PM';
  const h12 = hh % 12 === 0 ? 12 : hh % 12;
  return `${h12}:${String(mm).padStart(2, '0')} ${ampm}`;
}

function CheckInDeadlineEditor({ shiftStart, ncnsCutoff, onHelp }: {
  shiftStart: string | undefined; ncnsCutoff: string | undefined; onHelp: () => void;
}) {
  const [rows, setRows] = useState<CheckInDeadline[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = async () => {
    try {
      const res = await axiosClient.get<CheckInDeadline[]>('/companies/my-config/check-in-deadlines');
      setRows(res.data ?? []);
    } catch { /* best-effort */ }
    finally { setLoaded(true); }
  };
  useEffect(() => { load(); }, []);

  const ncnsNum = ncnsCutoff ? parseInt(ncnsCutoff, 10) : null;
  const lastOffset = rows.length ? rows[rows.length - 1].offset_minutes : null;
  const nextSeq = rows.length + 1;
  // The floor the next deadline must clear: NCNS for #1, the previous for the rest.
  const floor = nextSeq === 1 ? ncnsNum : lastOffset;

  const add = async () => {
    const offset = parseInt(draft, 10);
    if (Number.isNaN(offset)) { setError('Enter the deadline in minutes past shift start.'); return; }
    setBusy(true); setError(null);
    try {
      await axiosClient.post('/companies/my-config/check-in-deadlines', { offset_minutes: offset });
      setDraft('');
      await load();
    } catch (e: unknown) {
      setError(errorText(e, 'Could not add the check-in.'));
    } finally { setBusy(false); }
  };

  const remove = async (sequence: number) => {
    setBusy(true); setError(null);
    try {
      await axiosClient.delete(`/companies/my-config/check-in-deadlines/${sequence}`);
      await load();
    } catch (e: unknown) {
      setError(errorText(e, 'Could not remove the check-in.'));
    } finally { setBusy(false); }
  };

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary/10">
          <CheckSquare className="w-4 h-4 text-primary" />
        </div>
        <h3 className="font-semibold text-sm">Check-in Deadlines</h3>
        <button type="button" onClick={onHelp} tabIndex={-1}
          className="text-muted-foreground hover:text-primary transition-colors" aria-label="Help for check-in deadlines">
          <HelpCircle className="w-3 h-3" />
        </button>
      </div>

      {ncnsNum === null && (
        <div className="p-2.5 rounded-lg bg-warning/10 border border-warning/20 text-xs text-warning">
          Set the <strong>NCNS Cutoff</strong> (Attendance section) and save before adding check-ins. Check-In&nbsp;#1 can’t be earlier than it.
        </div>
      )}

      {loaded && rows.length === 0 && ncnsNum !== null && (
        <p className="text-xs text-muted-foreground">No check-ins configured yet. Add the first below.</p>
      )}

      {rows.length > 0 && (
        <div className="space-y-1.5">
          {rows.map(r => {
            const clock = offsetToClock(shiftStart, r.offset_minutes);
            const isLast = r.sequence === rows[rows.length - 1].sequence;
            return (
              <div key={r.id} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border bg-surface text-sm">
                <span className="font-semibold text-foreground w-16">#{r.sequence}</span>
                <span className="flex-1 tabular-nums">
                  {r.offset_minutes} min after shift start
                  {clock && <span className="text-muted-foreground"> · {clock}</span>}
                </span>
                {isLast && (
                  <button type="button" disabled={busy} onClick={() => remove(r.sequence)}
                    className="text-muted-foreground hover:text-danger transition-colors disabled:opacity-40"
                    aria-label={`Remove check-in #${r.sequence}`}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {ncnsNum !== null && (
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <label className="block text-xs font-medium text-foreground mb-1">
              Add Check-in #{nextSeq} · minutes after shift start
            </label>
            <input
              className="input-field"
              type="number"
              value={draft}
              onChange={e => setDraft(e.target.value)}
              placeholder={floor != null ? `> ${floor}` : '90'}
              min={floor != null ? floor + (nextSeq === 1 ? 0 : 1) : 1}
            />
            <p className="text-xs text-muted-foreground mt-1">
              {nextSeq === 1
                ? `Must be at or after the NCNS cutoff (${ncnsNum} min${offsetToClock(shiftStart, ncnsNum) ? ` · ${offsetToClock(shiftStart, ncnsNum)}` : ''}).`
                : `Must be later than Check-in #${nextSeq - 1} (${lastOffset} min).`}
              {draft && !Number.isNaN(parseInt(draft, 10)) && offsetToClock(shiftStart, parseInt(draft, 10)) &&
                ` → ${offsetToClock(shiftStart, parseInt(draft, 10))}`}
            </p>
          </div>
          <button type="button" disabled={busy || !draft} onClick={add}
            className="btn-secondary flex items-center gap-1.5 mb-6 disabled:opacity-40">
            <Plus className="w-3.5 h-3.5" /> Add
          </button>
        </div>
      )}

      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Setup defaults
// ---------------------------------------------------------------------------

const SETUP_DEFAULTS: Record<string, string> = {
  rating_window_hours: '6',
  graduation_assignments: '5',
  debt_escalation_threshold: '3',
  phase4_pass_score: '90.0',
  underperforming_trainer_threshold: '3',
  max_training_phase: '4',
  dispatch_weight_driver: '0.70',
  dispatch_weight_trainer: '0.50',
  dispatch_weight_walker: '0.30',
  dispatch_mutual_bonus: '0.10',
  dispatch_tridirectional_bonus: '0.20',
  dispatch_consecutive_penalty: '0.05',
  dispatch_weight_cap: '0.85',
  flag_threshold: '1.0',
  driver_checkin_count: '4',
  effort_time_factor: '0.5',
  effort_physical_factor: '0.5',
  ingestion_mode: 'file',
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

interface CompanySettingsProps {
  isOnboarding?: boolean;
}

export default function CompanySettings({ isOnboarding = false }: CompanySettingsProps) {
  const navigate = useNavigate();
  const { refreshConfigured } = useAuth();

  const [config, setConfig] = useState<CompanyConfig | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [discordValues, setDiscordValues] = useState<Record<string, string>>({});
  const [discordSaving, setDiscordSaving] = useState(false);
  const [discordError, setDiscordError] = useState<string | null>(null);
  const [discordSaved, setDiscordSaved] = useState(false);

  const [helpKey, setHelpKey] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [configRes, discordRes] = await Promise.all([
        axiosClient.get<CompanyConfig>('/companies/my-config'),
        axiosClient.get<DiscordConfig>('/companies/my-discord-config'),
      ]);
      setConfig(configRes.data);
      setFormValues(configToFormValues(configRes.data));
      setDiscordValues(discordToFormValues(discordRes.data));
    } catch {
      setError('Failed to load company configuration.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleChange = (key: string, val: string) => {
    setFormValues(prev => ({ ...prev, [key]: val }));
    setSaved(false);
  };

  const handleDiscordChange = (key: string, val: string) => {
    setDiscordValues(prev => ({ ...prev, [key]: val }));
    setDiscordSaved(false);
  };

  const fillDefaults = () => {
    setFormValues(prev => ({ ...prev, ...SETUP_DEFAULTS }));
    setSaved(false);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);

    if (isOnboarding) {
      const missing = missingRequired(formValues);
      if (missing.length > 0) {
        setError('Please fill in all required fields before completing setup.');
        return;
      }
    }

    setSaving(true);
    try {
      const payload = formValuesToPayload(formValues);
      const res = await axiosClient.patch<CompanyConfig>('/companies/my-config', payload);
      setConfig(res.data);
      setFormValues(configToFormValues(res.data));

      if (isOnboarding && res.data.is_configured) {
        await refreshConfigured();
        navigate('/admin', { replace: true });
        return;
      }

      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to save configuration.'));
    } finally {
      setSaving(false);
    }
  };

  const handleDiscordSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setDiscordError(null);
    setDiscordSaved(false);
    setDiscordSaving(true);
    try {
      const payload = discordValuesToPayload(discordValues);
      const res = await axiosClient.patch<DiscordConfig>('/companies/my-discord-config', payload);
      setDiscordValues(discordToFormValues(res.data));
      setDiscordSaved(true);
      setTimeout(() => setDiscordSaved(false), 3000);
    } catch (err: unknown) {
      setDiscordError(errorText(err, 'Failed to save Discord configuration.'));
    } finally {
      setDiscordSaving(false);
    }
  };

  const CONFIG_SECTIONS = [
    { title: 'Shift Timing', icon: Clock, fields: SHIFT_TIMING },
    { title: 'Training Rules', icon: BookOpen, fields: TRAINING_RULES },
    { title: 'Dispatch Weights', icon: Truck, fields: DISPATCH_WEIGHTS },
    { title: 'Walker Rating', icon: Star, fields: WALKER_RATING },
    { title: 'Attendance', icon: CheckSquare, fields: ATTENDANCE },
    { title: 'Effort Scoring', icon: MapPin, fields: EFFORT_SCORING },
    { title: 'Scorecard Targets — Quality', icon: Star, fields: SCORECARD_QUALITY },
    { title: 'Scorecard Targets — Safety', icon: Truck, fields: SCORECARD_SAFETY },
    { title: 'Manifest Ingestion', icon: Settings, fields: INGESTION },
  ];

  const content = (
    <div className="space-y-6 animate-slide-up">
      {isOnboarding ? (
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-warning/10">
              <Settings className="w-5 h-5 text-warning" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-foreground">Company Setup</h1>
              <p className="text-sm text-muted-foreground">Complete this before your team can use the platform.</p>
            </div>
          </div>
          <div className="flex items-start gap-2.5 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-warning">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>
              Fields marked <span className="font-semibold">*</span> are required. Click the <span className="font-semibold">?</span> next to any field for a full explanation.
            </span>
          </div>
        </div>
      ) : (
        <SectionHeader
          title="Company Settings"
          description="Operational configuration for your company."
          actions={
            <button onClick={load} className="btn-ghost flex items-center gap-1.5 text-sm">
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
          }
        />
      )}

      {error && <ErrorBanner message={error} />}

      {loading ? (
        <div className="space-y-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="card animate-pulse h-40" />
          ))}
        </div>
      ) : (
        <>
          {/* ---- Operational config form ---- */}
          <form onSubmit={handleSave} className="space-y-4">
            {CONFIG_SECTIONS.map(({ title, icon, fields }) => (
              <motion.div
                key={title}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <ConfigSection
                  title={title}
                  icon={icon}
                  fields={fields}
                  values={formValues}
                  onChange={handleChange}
                  onHelp={setHelpKey}
                  isOnboarding={isOnboarding}
                />
              </motion.div>
            ))}

            {/* Check-in deadlines editor (ADR-228) — its own CRUD, not part of the
                config PATCH. Hidden during first-run onboarding (needs a saved
                config + NCNS cutoff first). */}
            {!isOnboarding && (
              <CheckInDeadlineEditor
                shiftStart={formValues.shift_start}
                ncnsCutoff={formValues.ncns_cutoff_minutes}
                onHelp={() => setHelpKey('check_in_deadlines')}
              />
            )}

            <div className="flex items-center justify-between gap-3 pt-2">
              {isOnboarding ? (
                <button
                  type="button"
                  onClick={fillDefaults}
                  className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors font-medium"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  Fill with recommended defaults
                </button>
              ) : (
                <span />
              )}
              <div className="flex items-center gap-3">
                {saved && !isOnboarding && (
                  <motion.span
                    initial={{ opacity: 0, x: 8 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0 }}
                    className="flex items-center gap-1.5 text-sm text-success"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    Saved
                  </motion.span>
                )}
                <button
                  type="submit"
                  disabled={saving}
                  className="btn-primary flex items-center gap-2 text-sm"
                >
                  {isOnboarding ? (
                    <>
                      <CheckCircle2 className="w-4 h-4" />
                      {saving ? 'Completing Setup…' : 'Complete Setup'}
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4" />
                      {saving ? 'Saving…' : 'Save Changes'}
                    </>
                  )}
                </button>
              </div>
            </div>
          </form>

          {/* ---- Discord config form (hidden in onboarding) ---- */}
          {!isOnboarding && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.05 }}
            >
              <form onSubmit={handleDiscordSave} className="space-y-4">
                {discordError && <ErrorBanner message={discordError} />}

                <ConfigSection
                  title="Discord — Channels"
                  icon={MessageSquare}
                  fields={DISCORD_CHANNELS}
                  values={discordValues}
                  onChange={handleDiscordChange}
                  onHelp={setHelpKey}
                />
                <ConfigSection
                  title="Discord — Roles"
                  icon={MessageSquare}
                  fields={DISCORD_ROLES}
                  values={discordValues}
                  onChange={handleDiscordChange}
                  onHelp={setHelpKey}
                />

                <div className="flex items-center justify-end gap-3 pt-2">
                  {discordSaved && (
                    <motion.span
                      initial={{ opacity: 0, x: 8 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="flex items-center gap-1.5 text-sm text-success"
                    >
                      <CheckCircle2 className="w-4 h-4" />
                      Discord saved
                    </motion.span>
                  )}
                  <button
                    type="submit"
                    disabled={discordSaving}
                    className="btn-primary flex items-center gap-2 text-sm"
                  >
                    <Save className="w-4 h-4" />
                    {discordSaving ? 'Saving…' : 'Save Discord Config'}
                  </button>
                </div>
              </form>
            </motion.div>
          )}
        </>
      )}

      <SettingsHelpDrawer fieldKey={helpKey} onClose={() => setHelpKey(null)} />
    </div>
  );

  if (isOnboarding) {
    return (
      <div className="min-h-screen bg-background flex items-start justify-center pt-16 px-4">
        <div className="w-full max-w-3xl">
          {content}
        </div>
      </div>
    );
  }

  return content;
}
