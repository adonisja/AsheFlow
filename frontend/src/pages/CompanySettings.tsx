import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Settings, Clock, BookOpen, Truck,
  Star, CheckSquare, Save, RefreshCw, CheckCircle2, AlertTriangle, RotateCcw,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
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
}

// ---------------------------------------------------------------------------
// Field metadata
// ---------------------------------------------------------------------------

type FieldType = 'time' | 'int' | 'float';

interface FieldMeta {
  key: keyof CompanyConfig;
  label: string;
  description: string;
  placeholder: string;
  type: FieldType;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
}

const SHIFT_TIMING: FieldMeta[] = [
  {
    key: 'shift_start', label: 'Shift Start Time', type: 'time',
    description: 'The time drivers are expected to begin their shift at the offsite.',
    placeholder: '07:00',
  },
  {
    key: 'shift_end', label: 'Shift End Time', type: 'time',
    description: 'The expected end of the working shift.',
    placeholder: '18:00',
  },
  {
    key: 'checkin_open', label: 'Check-in Opens', type: 'time',
    description: 'Earliest time the morning check-in photo is accepted.',
    placeholder: '06:30',
  },
  {
    key: 'checkin_close', label: 'Check-in Closes', type: 'time',
    description: 'Latest time the morning check-in photo is accepted. Submissions after this are flagged.',
    placeholder: '07:45',
  },
];

const TRAINING_RULES: FieldMeta[] = [
  {
    key: 'graduation_assignments', label: 'Graduation Threshold (days)', type: 'int',
    required: true,
    description: 'Number of successfully completed dispatch days before a trainee is graduated to walker.',
    placeholder: '5', min: 1, max: 30,
  },
  {
    key: 'debt_escalation_threshold', label: 'Debt Escalation Threshold (days)', type: 'int',
    required: true,
    description: 'Consecutive days a mandatory training task can remain incomplete before the record is flagged for manager review.',
    placeholder: '3', min: 1, max: 30,
  },
  {
    key: 'phase4_pass_score', label: 'Phase 4 Pass Score (%)', type: 'float',
    required: true,
    description: 'Minimum score required on Phase 4 (practical observation) to pass and proceed to graduation.',
    placeholder: '90', min: 0, max: 100, step: 0.1,
  },
  {
    key: 'underperforming_trainer_threshold', label: 'Underperforming Trainer Threshold', type: 'int',
    required: true,
    description: 'Number of below-threshold training records before a trainer is flagged for review.',
    placeholder: '3', min: 1, max: 30,
  },
  {
    key: 'max_training_phase', label: 'Max Training Phase', type: 'int',
    required: true,
    description: 'The highest phase number in the training curriculum.',
    placeholder: '4', min: 1, max: 10,
  },
];

const DISPATCH_WEIGHTS: FieldMeta[] = [
  {
    key: 'dispatch_weight_driver', label: 'Driver Preference Weight', type: 'float',
    required: true,
    description: 'How heavily the dispatch algorithm weights a driver\'s preference history. Higher = more loyal pairing.',
    placeholder: '0.70', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_weight_trainer', label: 'Trainer Preference Weight', type: 'float',
    required: true,
    description: 'Same as above for trainer-role employees.',
    placeholder: '0.50', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_weight_walker', label: 'Walker Preference Weight', type: 'float',
    required: true,
    description: 'Same as above for walker-role employees.',
    placeholder: '0.30', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_mutual_bonus', label: 'Mutual Preference Bonus', type: 'float',
    required: true,
    description: 'Bonus score when two crew members have each other on their preference lists.',
    placeholder: '0.10', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_tridirectional_bonus', label: 'Three-Way Preference Bonus', type: 'float',
    required: true,
    description: 'Bonus score when three crew members all mutually prefer each other.',
    placeholder: '0.20', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_consecutive_penalty', label: 'Consecutive Truck Penalty', type: 'float',
    required: true,
    description: 'Score deduction when an employee is assigned to the same truck as the previous day.',
    placeholder: '0.05', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_weight_cap', label: 'Maximum Preference Score Cap', type: 'float',
    required: true,
    description: 'The highest score any crew member can receive from the preference algorithm.',
    placeholder: '0.85', min: 0, max: 1, step: 0.01,
  },
];

const WALKER_RATING: FieldMeta[] = [
  {
    key: 'rating_window_hours', label: 'Walker Rating Window (hours)', type: 'int',
    required: true,
    description: 'Hours after driver departure within which walker ratings can be submitted.',
    placeholder: '6', min: 1, max: 48,
  },
  {
    key: 'flag_threshold', label: 'Walker Rating Flag Threshold', type: 'float',
    required: true,
    description: 'Deviation from a driver\'s average rating that triggers an anomaly flag.',
    placeholder: '1.0', min: 0, max: 10, step: 0.1,
  },
];

const DRIVER_CHECKINS: FieldMeta[] = [
  {
    key: 'driver_checkin_count', label: 'Driver Mid-Shift Check-ins', type: 'int',
    description: 'Number of structured mid-shift check-ins expected from the driver during the day.',
    placeholder: '4', min: 0, max: 10,
  },
];

// ---------------------------------------------------------------------------
// Config section component
// ---------------------------------------------------------------------------

interface SectionProps {
  title: string;
  icon: React.ElementType;
  fields: FieldMeta[];
  values: Record<string, string>;
  onChange: (key: string, val: string) => void;
  isOnboarding?: boolean;
}

function ConfigSection({ title, icon: Icon, fields, values, onChange, isOnboarding }: SectionProps) {
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
          <div key={field.key as string}>
            <label className="block text-xs font-medium text-foreground mb-1">
              {field.label}
              {isOnboarding && field.required && (
                <span className="text-danger ml-1">*</span>
              )}
            </label>
            <input
              className="input-field"
              type={field.type === 'time' ? 'text' : 'number'}
              value={values[field.key as string] ?? ''}
              onChange={e => onChange(field.key as string, e.target.value)}
              placeholder={field.placeholder}
              min={field.min}
              max={field.max}
              step={field.step}
            />
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
// Helpers
// ---------------------------------------------------------------------------

const CONFIG_KEYS: Array<keyof CompanyConfig> = [
  'shift_start', 'shift_end', 'checkin_open', 'checkin_close',
  'rating_window_hours',
  'graduation_assignments', 'debt_escalation_threshold', 'phase4_pass_score',
  'underperforming_trainer_threshold', 'max_training_phase',
  'dispatch_weight_driver', 'dispatch_weight_trainer', 'dispatch_weight_walker',
  'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus', 'dispatch_consecutive_penalty',
  'dispatch_weight_cap', 'flag_threshold', 'driver_checkin_count',
];

function configToFormValues(config: CompanyConfig): Record<string, string> {
  const result: Record<string, string> = {};
  for (const k of CONFIG_KEYS) {
    const v = config[k];
    result[k as string] = v !== null && v !== undefined ? String(v) : '';
  }
  return result;
}

const TIME_FIELDS = new Set(['shift_start', 'shift_end', 'checkin_open', 'checkin_close']);
const INT_FIELDS = new Set([
  'rating_window_hours', 'graduation_assignments', 'debt_escalation_threshold',
  'underperforming_trainer_threshold', 'max_training_phase', 'driver_checkin_count',
]);
const FLOAT_FIELDS = new Set([
  'phase4_pass_score', 'dispatch_weight_driver', 'dispatch_weight_trainer',
  'dispatch_weight_walker', 'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus',
  'dispatch_consecutive_penalty', 'dispatch_weight_cap', 'flag_threshold',
]);

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
    }
  }
  return payload;
}

const REQUIRED_KEYS = new Set([
  'rating_window_hours', 'graduation_assignments', 'debt_escalation_threshold',
  'phase4_pass_score', 'underperforming_trainer_threshold', 'max_training_phase',
  'dispatch_weight_driver', 'dispatch_weight_trainer', 'dispatch_weight_walker',
  'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus', 'dispatch_consecutive_penalty',
  'dispatch_weight_cap', 'flag_threshold',
]);

function missingRequired(values: Record<string, string>): string[] {
  return [...REQUIRED_KEYS].filter(k => !values[k]);
}

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

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<CompanyConfig>('/companies/my-config');
      setConfig(res.data);
      setFormValues(configToFormValues(res.data));
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
        setError(`Please fill in all required fields before completing setup.`);
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

  const SECTIONS = [
    { title: 'Shift Timing', icon: Clock, fields: SHIFT_TIMING },
    { title: 'Training Rules', icon: BookOpen, fields: TRAINING_RULES },
    { title: 'Dispatch Weights', icon: Truck, fields: DISPATCH_WEIGHTS },
    { title: 'Walker Rating', icon: Star, fields: WALKER_RATING },
    { title: 'Driver Check-ins', icon: CheckSquare, fields: DRIVER_CHECKINS },
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
              All fields marked <span className="font-semibold">*</span> are required. The platform will remain locked until setup is complete.
              Shift timing and driver check-ins are optional — you can set them later from Settings.
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
        <form onSubmit={handleSave} className="space-y-4">
          {SECTIONS.map(({ title, icon, fields }) => (
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
      )}
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
