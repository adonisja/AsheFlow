import { errorText } from '../utils/errorText';
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Settings, Clock, BookOpen, Truck, Star, CheckSquare,
  Save, RefreshCw, CheckCircle2, AlertTriangle, RotateCcw,
  MessageSquare, MapPin, HelpCircle, Plus, Trash2,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import type { MetricTarget } from '../api/types';
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
  flag_threshold: number | null;
  driver_checkin_count: number | null;
  late_window_minutes: number | null;
  ncns_cutoff_minutes: number | null;
  effort_time_factor: number | null;
  effort_physical_factor: number | null;
  ingestion_mode: string | null;
  // Amazon scorecard tier targets (ADR-262). null = no target configured; the
  // scorecard shows the reported value with no pass/fail judgement.
}

interface DiscordConfig {
  /** ADR-448 D2. Built from the RUNNING bot's application id, not a constant —
   *  staging and prod are different Discord applications, and a build-time
   *  value would send prod admins to invite the staging bot. */
  bot_invite_url?: string | null;
  /** ADR-448 D3. THREE-STATE: true / false / null for "could not ask". A
   *  restarting bot must not show a red cross next to a correct config. */
  bot_in_guild?: boolean | null;
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
  'flag_threshold', 'driver_checkin_count',
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
  'phase4_pass_score', 'flag_threshold',
  'effort_time_factor', 'effort_physical_factor',
  'scorecard_dcr_target', 'scorecard_pod_target', 'scorecard_cc_target',
  'scorecard_cdf_target', 'scorecard_speeding_rate_target',
  'scorecard_signsignal_rate_target', 'scorecard_dvic_target',
]);
const STRING_FIELDS = new Set(['ingestion_mode']);

const REQUIRED_KEYS = new Set([
  'rating_window_hours', 'graduation_assignments', 'debt_escalation_threshold',
  'phase4_pass_score', 'underperforming_trainer_threshold', 'max_training_phase',
  'flag_threshold',
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
  // ADR-448. The raw response, kept because bot_invite_url / bot_in_guild are
  // live server-resolved fields, not editable form values.
  const [discordCfg, setDiscordCfg] = useState<DiscordConfig | null>(null);
  const [discordSaving, setDiscordSaving] = useState(false);
  const [discordError, setDiscordError] = useState<string | null>(null);
  const [discordSaved, setDiscordSaved] = useState(false);

  /* ADR-473 D6. Scorecard targets, as a collection.

     Hidden during onboarding on purpose: a DSP setting the platform up has not
     read their first Amazon card yet, and a page that asks for numbers they
     cannot have is a page they abandon. ADR-262 made the same call about these
     never being required fields. */
  const [targets, setTargets] = useState<MetricTarget[] | null>(null);
  const [targetsError, setTargetsError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const loadTargets = useCallback(async () => {
    try {
      const r = await axiosClient.get<MetricTarget[]>('/companies/my-config/metric-targets');
      setTargets(r.data);
      setTargetsError(null);
    } catch {
      setTargets([]);
      setTargetsError('Could not load scorecard targets.');
    }
  }, []);

  useEffect(() => { if (!isOnboarding) void loadTargets(); }, [isOnboarding, loadTargets]);

  const saveTarget = async (metricKey: string, raw: string) => {
    setSavingKey(metricKey);
    setTargetsError(null);
    try {
      if (raw.trim() === '') {
        // Clearing is a real action, not an empty save: an unset target means
        // "report the value with no verdict" rather than "the target is zero".
        await axiosClient.delete(`/companies/my-config/metric-targets/${metricKey}`);
      } else {
        await axiosClient.put('/companies/my-config/metric-targets', {
          metric_key: metricKey,
          target_value: Number(raw),
        });
      }
      await loadTargets();
    } catch (err: unknown) {
      setTargetsError(errorText(err, 'Could not save that target.'));
    } finally {
      setSavingKey(null);
    }
  };

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
      // The PATCH response carries a FRESH bot_in_guild, so saving a guild id
      // updates the panel above without a reload (ADR-448 D3).
      setDiscordCfg(res.data);
      setDiscordSaved(true);
      setTimeout(() => setDiscordSaved(false), 3000);
    } catch (err: unknown) {
      setDiscordError(errorText(err, 'Failed to save Discord configuration.'));
    } finally {
      setDiscordSaving(false);
    }
  };

  /* ADR-473. The two Scorecard Targets sections are gone from this fixed list.
     Their ten fields asserted a direction and a unit in the form definition, and
     five asserted them wrong against Amazon's own metric guides. Targets are now
     rows in company_metric_targets, carrying their own direction and unit, and
     get their own surface rather than a hardcoded field list that has to be
     migrated every time Amazon reshapes a metric. */
  /* ADR-473 D6. The metrics offered in the UI, with labels.

     DELIBERATELY NOT the source of direction or unit -- those come back on the
     row from the server. A hardcoded direction here that disagreed with the
     stored one would be the exact defect ADR-473 closed, moved from the backend
     to the frontend.

     A curated list rather than everything the registry knows: an Owner wants the
     metrics on their card, in card order, not an alphabetical dump. A metric
     added server-side is simply not offered here until someone adds the label,
     which is a smaller failure than showing a key nobody recognises. */
  const KNOWN_METRICS: { key: string; label: string; hint: string }[] = [
    { key: 'pod',                     label: 'POD Acceptance',        hint: 'Photos accepted, as a percentage.' },
    { key: 'dsb_dpmo',                label: 'DSB',                   hint: 'Concessions per million packages.' },
    { key: 'cdf_dpmo',                label: 'Customer Feedback',     hint: 'Negative feedback per million deliveries.' },
    { key: 'dc_dpmo',                 label: 'Delivery Completion',   hint: 'Returned packages per million dispatched.' },
    { key: 'fico',                    label: 'FICO',                  hint: 'Driving score, 100 to 850.' },
    { key: 'speeding_rate',           label: 'Speeding',              hint: 'Events per 100 trips.' },
    { key: 'signsignal_rate',         label: 'Sign / Signal',         hint: 'Events per 100 trips.' },
    { key: 'seatbelt_rate',           label: 'Seatbelt',              hint: 'Events per 100 trips.' },
    { key: 'distractions_rate',       label: 'Distractions',          hint: 'Events per 100 trips.' },
    { key: 'following_distance_rate', label: 'Following Distance',    hint: 'Events per 100 trips.' },
    { key: 'fleet_execution',         label: 'Fleet Execution',       hint: 'Defects per 100 vehicles.' },
  ];

  const CONFIG_SECTIONS = [
    { title: 'Shift Timing', icon: Clock, fields: SHIFT_TIMING },
    { title: 'Training Rules', icon: BookOpen, fields: TRAINING_RULES },
    { title: 'Walker Rating', icon: Star, fields: WALKER_RATING },
    { title: 'Attendance', icon: CheckSquare, fields: ATTENDANCE },
    { title: 'Effort Scoring', icon: MapPin, fields: EFFORT_SCORING },
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

          {/* ---- Scorecard targets (ADR-473 D6, hidden in onboarding) ---- */}
          {!isOnboarding && (
            <div className="card">
              <div className="flex items-start justify-between gap-3 mb-4">
                <div>
                  <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
                    <Star className="w-4 h-4 text-primary" />
                    Scorecard Targets
                  </h2>
                  <p className="text-xs text-muted-foreground mt-1">
                    The figures your team is measured against. Take each one from
                    your own weekly Amazon scorecard. Leave a target empty and that
                    metric is reported without a pass or fail.
                  </p>
                </div>
              </div>

              {targetsError && <ErrorBanner message={targetsError} />}

              {targets === null ? (
                <div className="h-24 animate-pulse rounded-lg bg-accent/40" />
              ) : (
                <div className="space-y-2">
                  {KNOWN_METRICS.map(({ key, label, hint }) => {
                    const row = targets.find(t => t.metric_key === key);
                    /* The direction comes from the SERVER, never from this list.
                       A label here that disagreed with the stored row would be
                       the ADR-473 defect wearing a different hat. */
                    const dir = row?.direction;
                    return (
                      <div key={key} className="flex items-center gap-3 py-2 border-b border-border last:border-0">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="text-sm font-medium text-foreground">{label}</span>
                            <button
                              type="button"
                              onClick={() => setHelpKey(`metric_${key}`)}
                              tabIndex={-1}
                              className="text-muted-foreground hover:text-primary transition-colors"
                              aria-label={`Help for ${label}`}
                            >
                              <HelpCircle className="w-3 h-3" />
                            </button>
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {dir === 'lower'
                              ? 'A ceiling: pass at or below this.'
                              : dir === 'higher'
                                ? 'Pass at or above this.'
                                : hint}
                          </p>
                        </div>
                        <input
                          type="number"
                          step="any"
                          min={0}
                          defaultValue={row?.target_value ?? ''}
                          placeholder="Not set"
                          disabled={savingKey === key}
                          onBlur={e => {
                            const next = e.target.value;
                            const current = row?.target_value;
                            const unchanged = next.trim() === ''
                              ? current === undefined
                              : Number(next) === current;
                            if (!unchanged) void saveTarget(key, next);
                          }}
                          className="input w-32 text-right disabled:opacity-50"
                        />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* ---- Discord config form (hidden in onboarding) ---- */}
          {!isOnboarding && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.05 }}
            >
              <form onSubmit={handleDiscordSave} className="space-y-4">
                {discordError && <ErrorBanner message={discordError} />}

                {/* ADR-448 D1. FIRST, above the id fields: every id below can be
                    correct and Discord will still do nothing until a server admin
                    authorises the bot. Screen order is operation order. */}
                {discordCfg && (
                  <div className="card p-5">
                    <div className="flex items-start gap-3">
                      <MessageSquare className="w-5 h-5 text-muted-foreground mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <h3 className="section-title mb-1">Connect the AsheFlow bot</h3>

                        {discordCfg.bot_in_guild === true && (
                          <p className="text-sm text-success">
                            The bot is in your Discord server. Channel and role IDs
                            below take effect immediately.
                          </p>
                        )}

                        {discordCfg.bot_in_guild === false && (
                          <p className="text-sm text-muted-foreground">
                            The bot is <strong className="text-warning">not yet in your
                            Discord server</strong>. Until it is, dispatch notifications,
                            crew rooms and employee Discord invites will not work, even
                            with every ID below filled in correctly.
                          </p>
                        )}

                        {discordCfg.bot_in_guild == null && (
                          <p className="text-sm text-muted-foreground">
                            {discordCfg.discord_guild_id
                              ? 'Could not check whether the bot is in your server right now.'
                              : 'Set your Server ID below, then authorise the bot.'}
                          </p>
                        )}

                        {discordCfg.bot_invite_url && discordCfg.bot_in_guild !== true && (
                          <>
                            <a
                              href={discordCfg.bot_invite_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn-primary mt-3 inline-flex items-center gap-2"
                            >
                              Authorise in Discord
                            </a>
                            <p className="text-xs text-muted-foreground mt-2">
                              Opens Discord. You need <strong>Manage Server</strong> on the
                              server you pick. If that is not you, send this link to
                              whoever has it.
                            </p>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                )}

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
