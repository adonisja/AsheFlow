import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Settings, Clock, Users, BookOpen, Truck, BarChart2,
  Star, CheckSquare, Save, RefreshCw, CheckCircle2,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CompanyConfig {
  id: string;
  company_id: string;
  shift_start: string | null;
  shift_end: string | null;
  checkin_open: string | null;
  checkin_close: string | null;
  rating_window_hours: number | null;
  min_trainers_per_truck: number | null;
  min_walkers_per_truck: number | null;
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

const CREW_REQUIREMENTS: FieldMeta[] = [
  {
    key: 'min_trainers_per_truck', label: 'Min Trainers per Truck', type: 'int',
    description: 'Minimum number of trainer-role employees required on a truck before dispatch considers it adequately staffed for training.',
    placeholder: '2', min: 0, max: 20,
  },
  {
    key: 'min_walkers_per_truck', label: 'Min Walkers per Truck', type: 'int',
    description: 'Minimum number of walker-role employees required on a truck. Dispatch will warn if this threshold isn\'t met.',
    placeholder: '3', min: 0, max: 20,
  },
];

const TRAINING_RULES: FieldMeta[] = [
  {
    key: 'graduation_assignments', label: 'Graduation Threshold (days)', type: 'int',
    description: 'Number of successfully completed training days required before a trainee is eligible for graduation to driver.',
    placeholder: '5', min: 1, max: 30,
  },
  {
    key: 'debt_escalation_threshold', label: 'Debt Escalation Threshold (days)', type: 'int',
    description: 'Number of consecutive dispatch days a mandatory training task can be carried as incomplete before the training record is flagged for manager review.',
    placeholder: '3', min: 1, max: 30,
  },
  {
    key: 'phase4_pass_score', label: 'Phase 4 Pass Score (%)', type: 'float',
    description: 'Minimum score a trainee must achieve on Phase 4 (practical observation) to pass and proceed to graduation.',
    placeholder: '90', min: 0, max: 100, step: 0.1,
  },
  {
    key: 'underperforming_trainer_threshold', label: 'Underperforming Trainer Threshold', type: 'int',
    description: 'Number of below-threshold training records before a trainer is flagged for review.',
    placeholder: '3', min: 1, max: 30,
  },
  {
    key: 'max_training_phase', label: 'Max Training Phase', type: 'int',
    description: 'The highest phase number in the training curriculum. Phase 5 is remediation-only and is never injected normally.',
    placeholder: '4', min: 1, max: 10,
  },
];

const DISPATCH_WEIGHTS: FieldMeta[] = [
  {
    key: 'dispatch_weight_driver', label: 'Driver Preference Weight', type: 'float',
    description: 'How heavily the dispatch algorithm weights a driver\'s preference history when scoring crew combinations. Higher = more loyal pairing.',
    placeholder: '0.70', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_weight_trainer', label: 'Trainer Preference Weight', type: 'float',
    description: 'Same as the driver weight above, applied to trainer-role employees.',
    placeholder: '0.50', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_weight_walker', label: 'Walker Preference Weight', type: 'float',
    description: 'Same as the driver weight above, applied to walker-role employees.',
    placeholder: '0.30', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_mutual_bonus', label: 'Mutual Preference Bonus', type: 'float',
    description: 'Bonus score added when two crew members have each other on their preference lists.',
    placeholder: '0.10', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_tridirectional_bonus', label: 'Three-Way Preference Bonus', type: 'float',
    description: 'Bonus score added when three crew members all mutually prefer each other.',
    placeholder: '0.20', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_consecutive_penalty', label: 'Consecutive Truck Penalty', type: 'float',
    description: 'Score deduction applied when an employee is assigned to the same truck they were on the previous day. Prevents crew fatigue from repetition.',
    placeholder: '0.05', min: 0, max: 1, step: 0.01,
  },
  {
    key: 'dispatch_weight_cap', label: 'Maximum Preference Score Cap', type: 'float',
    description: 'The highest score any crew member can receive from the preference algorithm. Prevents extreme preference lock-in.',
    placeholder: '0.85', min: 0, max: 1, step: 0.01,
  },
];

const WALKER_RATING: FieldMeta[] = [
  {
    key: 'rating_window_hours', label: 'Walker Rating Window (hours)', type: 'int',
    description: 'How many hours after the driver\'s departure a walker presence rating can be submitted. Submissions outside this window are rejected.',
    placeholder: '6', min: 1, max: 48,
  },
  {
    key: 'flag_threshold', label: 'Walker Rating Flag Threshold', type: 'float',
    description: 'Standard deviations below a driver\'s average walker rating that triggers an anomaly flag.',
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
}

function ConfigSection({ title, icon: Icon, fields, values, onChange }: SectionProps) {
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
            <label className="block text-xs font-medium text-foreground mb-1">
              {field.label}
            </label>
            <input
              className="input-field"
              type={field.type === 'time' ? 'text' : 'number'}
              value={values[field.key] ?? ''}
              onChange={e => onChange(field.key, e.target.value)}
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

function configToFormValues(config: CompanyConfig): Record<string, string> {
  const result: Record<string, string> = {};
  const keys: Array<keyof CompanyConfig> = [
    'shift_start', 'shift_end', 'checkin_open', 'checkin_close',
    'rating_window_hours', 'min_trainers_per_truck', 'min_walkers_per_truck',
    'graduation_assignments', 'debt_escalation_threshold', 'phase4_pass_score',
    'underperforming_trainer_threshold', 'max_training_phase',
    'dispatch_weight_driver', 'dispatch_weight_trainer', 'dispatch_weight_walker',
    'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus', 'dispatch_consecutive_penalty',
    'dispatch_weight_cap', 'flag_threshold', 'driver_checkin_count',
  ];
  for (const k of keys) {
    const v = config[k];
    result[k as string] = v !== null && v !== undefined ? String(v) : '';
  }
  return result;
}

function formValuesToPayload(values: Record<string, string>): Record<string, unknown> {
  const timeFields = new Set(['shift_start', 'shift_end', 'checkin_open', 'checkin_close']);
  const intFields = new Set([
    'rating_window_hours', 'min_trainers_per_truck', 'min_walkers_per_truck',
    'graduation_assignments', 'debt_escalation_threshold',
    'underperforming_trainer_threshold', 'max_training_phase', 'driver_checkin_count',
  ]);
  const floatFields = new Set([
    'phase4_pass_score', 'dispatch_weight_driver', 'dispatch_weight_trainer',
    'dispatch_weight_walker', 'dispatch_mutual_bonus', 'dispatch_tridirectional_bonus',
    'dispatch_consecutive_penalty', 'dispatch_weight_cap', 'flag_threshold',
  ]);

  const payload: Record<string, unknown> = {};
  for (const [k, raw] of Object.entries(values)) {
    if (raw === '' || raw === null || raw === undefined) continue;
    if (timeFields.has(k)) {
      payload[k] = raw;
    } else if (intFields.has(k)) {
      const n = parseInt(raw, 10);
      if (!isNaN(n)) payload[k] = n;
    } else if (floatFields.has(k)) {
      const n = parseFloat(raw);
      if (!isNaN(n)) payload[k] = n;
    }
  }
  return payload;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function CompanySettings() {
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

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const payload = formValuesToPayload(formValues);
      const res = await axiosClient.patch<CompanyConfig>('/companies/my-config', payload);
      setConfig(res.data);
      setFormValues(configToFormValues(res.data));
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
    { title: 'Crew Requirements', icon: Users, fields: CREW_REQUIREMENTS },
    { title: 'Training Rules', icon: BookOpen, fields: TRAINING_RULES },
    { title: 'Dispatch Weights', icon: Truck, fields: DISPATCH_WEIGHTS },
    { title: 'Walker Rating', icon: Star, fields: WALKER_RATING },
    { title: 'Driver Check-ins', icon: CheckSquare, fields: DRIVER_CHECKINS },
  ];

  return (
    <div className="space-y-6 animate-slide-up">
      <SectionHeader
        title="Company Settings"
        description="Operational configuration for your company. Blank fields use platform defaults."
        actions={
          <button onClick={load} className="btn-ghost flex items-center gap-1.5 text-sm">
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        }
      />

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
              />
            </motion.div>
          ))}

          <div className="flex items-center justify-end gap-3 pt-2">
            {saved && (
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
              <Save className="w-4 h-4" />
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
