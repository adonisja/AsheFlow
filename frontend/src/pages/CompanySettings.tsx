import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Settings, Clock, BookOpen, Truck, Star, CheckSquare,
  Save, RefreshCw, CheckCircle2, AlertTriangle, RotateCcw,
  MessageSquare, MapPin, Package, HelpCircle,
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
  tier1_small_tote_cutoff: number | null;
  tier1_small_stray_max: number | null;
  tier1_small_uncertain_max: number | null;
  tier1_stray_pct: number | null;
  tier1_uncertain_pct: number | null;
  effort_time_factor: number | null;
  effort_physical_factor: number | null;
  ingestion_mode: string | null;
}

interface DiscordConfig {
  discord_guild_id: number | null;
  discord_drivers_channel_id: number | null;
  discord_trainers_channel_id: number | null;
  discord_general_channel_id: number | null;
  discord_invite_channel_id: number | null;
  discord_role_admin: number | null;
  discord_role_manager: number | null;
  discord_role_asheflow: number | null;
  discord_role_bot: number | null;
  discord_role_dispatch: number | null;
  discord_role_driver: number | null;
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

const DRIVER_CHECKINS: FieldMeta[] = [
  { key: 'driver_checkin_count', label: 'Mid-Shift Check-ins', type: 'int', description: 'Structured check-in photos expected per shift.', placeholder: '4', min: 0, max: 10 },
];

const TIER1_VERIFY: FieldMeta[] = [
  { key: 'tier1_small_tote_cutoff', label: 'Small Tote Cutoff', type: 'int', description: 'Max packages in a cluster for it to be "small."', placeholder: '10', min: 1, max: 100 },
  { key: 'tier1_small_stray_max', label: 'Small Tote Max Strays', type: 'int', description: 'Max stray packages allowed in a small tote.', placeholder: '1', min: 0, max: 20 },
  { key: 'tier1_small_uncertain_max', label: 'Small Tote Max Uncertain', type: 'int', description: 'Max uncertain packages in a small tote.', placeholder: '3', min: 0, max: 20 },
  { key: 'tier1_stray_pct', label: 'Stray % Threshold', type: 'float', description: 'Max strays as fraction of tote size (large totes).', placeholder: '0.10', min: 0, max: 1, step: 0.01 },
  { key: 'tier1_uncertain_pct', label: 'Uncertain % Threshold', type: 'float', description: 'Max uncertain packages as fraction of tote (large totes).', placeholder: '0.40', min: 0, max: 1, step: 0.01 },
];

const EFFORT_SCORING: FieldMeta[] = [
  { key: 'effort_time_factor', label: 'Effort Time Factor', type: 'float', description: 'Weight for time-based effort in route scoring (0–1).', placeholder: '0.5', min: 0, max: 1, step: 0.05 },
  { key: 'effort_physical_factor', label: 'Effort Physical Factor', type: 'float', description: 'Weight for physical-based effort in route scoring (0–1).', placeholder: '0.5', min: 0, max: 1, step: 0.05 },
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
  { key: 'discord_general_channel_id', label: 'General Channel', type: 'bigint', description: 'Fallback channel for company-wide announcements.', placeholder: '' },
  { key: 'discord_invite_channel_id', label: 'Invite Channel', type: 'bigint', description: 'Channel where new invite links are posted.', placeholder: '' },
];

const DISCORD_ROLES: FieldMeta[] = [
  { key: 'discord_role_admin', label: 'Admin Role', type: 'bigint', description: 'Discord role ID for admin employees.', placeholder: '' },
  { key: 'discord_role_manager', label: 'Manager Role', type: 'bigint', description: 'Discord role ID for management employees.', placeholder: '' },
  { key: 'discord_role_dispatch', label: 'Dispatch Role', type: 'bigint', description: 'Discord role ID for dispatch employees.', placeholder: '' },
  { key: 'discord_role_driver', label: 'Driver Role', type: 'bigint', description: 'Discord role ID for driver employees.', placeholder: '' },
  { key: 'discord_role_walker', label: 'Walker Role', type: 'bigint', description: 'Discord role ID for walker employees.', placeholder: '' },
  { key: 'discord_role_captain', label: 'Captain Role', type: 'bigint', description: 'Discord role ID for captain/lead employees.', placeholder: '' },
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
  'tier1_small_tote_cutoff',
  'tier1_small_stray_max', 'tier1_small_uncertain_max', 'tier1_stray_pct', 'tier1_uncertain_pct',
  'effort_time_factor', 'effort_physical_factor', 'ingestion_mode',
];

const DISCORD_KEYS: string[] = [
  'discord_guild_id', 'discord_drivers_channel_id', 'discord_trainers_channel_id',
  'discord_general_channel_id', 'discord_invite_channel_id',
  'discord_role_admin', 'discord_role_manager', 'discord_role_asheflow',
  'discord_role_bot', 'discord_role_dispatch', 'discord_role_driver',
  'discord_role_captain', 'discord_role_walker',
];

const TIME_FIELDS = new Set(['shift_start', 'shift_end', 'checkin_open', 'checkin_close', 'dispatch_confirmation_cutoff']);
const INT_FIELDS = new Set([
  'rating_window_hours', 'graduation_assignments', 'debt_escalation_threshold',
  'underperforming_trainer_threshold', 'max_training_phase', 'driver_checkin_count',
  'tier1_small_tote_cutoff', 'tier1_small_stray_max',
  'tier1_small_uncertain_max',
]);
const FLOAT_FIELDS = new Set([
  'phase4_pass_score', 'dispatch_weight_driver', 'dispatch_weight_trainer',
  'dispatch_weight_walker', 'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus',
  'dispatch_consecutive_penalty', 'dispatch_weight_cap', 'flag_threshold',
  'tier1_stray_pct', 'tier1_uncertain_pct',
  'effort_time_factor', 'effort_physical_factor',
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
  tier1_small_tote_cutoff: '10',
  tier1_small_stray_max: '1',
  tier1_small_uncertain_max: '3',
  tier1_stray_pct: '0.10',
  tier1_uncertain_pct: '0.40',
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
    } catch (err: any) {
      setError(err.response?.data?.detail ?? 'Failed to save configuration.');
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
    } catch (err: any) {
      setDiscordError(err.response?.data?.detail ?? 'Failed to save Discord configuration.');
    } finally {
      setDiscordSaving(false);
    }
  };

  const CONFIG_SECTIONS = [
    { title: 'Shift Timing', icon: Clock, fields: SHIFT_TIMING },
    { title: 'Training Rules', icon: BookOpen, fields: TRAINING_RULES },
    { title: 'Dispatch Weights', icon: Truck, fields: DISPATCH_WEIGHTS },
    { title: 'Walker Rating', icon: Star, fields: WALKER_RATING },
    { title: 'Driver Check-ins', icon: CheckSquare, fields: DRIVER_CHECKINS },
    { title: 'Tier 1 Manifest Verify', icon: Package, fields: TIER1_VERIFY },
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
