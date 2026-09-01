import { errorText } from '../../utils/errorText';
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ArrowLeft, Building2, Settings2, Save, RotateCcw,
  ShieldCheck, ShieldAlert, Pencil, X, Users, AlertTriangle,
  CheckCircle2, XCircle, UserCheck, UserX, Clock, Bot, PackageCheck, PackageX,
} from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../../components/ui/ErrorBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CompanyConfig {
  id: string;
  company_id: string;
  is_configured: boolean;
  /** ADR-289. Read-only here — set via the Operating Mode card, which is the
   *  only writer. Optional so an older API response still parses. */
  operating_mode?: 'full' | 'workforce';
  shift_start: string | null;
  shift_end: string | null;
  checkin_open: string | null;
  checkin_close: string | null;
  rating_window_hours: number | null;
  invite_expiry_days: number | null;
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
  // Route-sort tuning (ADR-273). null = the algorithm's built-in default.
  sort_w_dense: number | null;
  sort_w_time: number | null;
  sort_w_diff: number | null;
  sort_w_doorman: number | null;
  sort_walk_budget_m: number | null;
  sort_span_cap_m: number | null;
  sort_max_consecutive_no_fit: number | null;
  sort_f5_load_floor_hs: number | null;
  sort_f5_max_hops: number | null;
  sort_f5_walk_radius_km: number | null;
  route_assembly_mode: string | null;
}

interface CompanyDetail {
  id: string;
  name: string;
  slug: string;
  amazon_dsp_code: string | null;
  timezone: string;
  is_active: boolean;
  created_at: string;
  config: CompanyConfig | null;
}

interface AdminSummary {
  employee_id: string;
  name: string;
  email: string | null;
  account_status: string;
}

interface EmployeeSummary {
  total: number;
  by_role: Record<string, number>;
  admins: AdminSummary[];
}

// ---------------------------------------------------------------------------
// Platform defaults (mirrors backend PLATFORM_DEFAULTS)
// ---------------------------------------------------------------------------

const PLATFORM_DEFAULTS: Record<string, string> = {
  rating_window_hours: '6',
  invite_expiry_days: '7',
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

// ---------------------------------------------------------------------------
// Config field metadata
// ---------------------------------------------------------------------------

type FieldType = 'time' | 'int' | 'float' | 'select';

interface ConfigFieldMeta {
  key: keyof CompanyConfig;
  label: string;
  type: FieldType;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
  /** For type 'select'. */
  options?: { value: string; label: string }[];
  /** The algorithm default, shown when the field is null. */
  placeholder?: string;
  /** One-line explanation under the input while editing. */
  hint?: string;
}

const CONFIG_SECTIONS: { heading: string; description?: string; fields: ConfigFieldMeta[] }[] = [
  {
    heading: 'Shift Timing',
    description: 'Optional — used by check-in and scheduling features.',
    fields: [
      { key: 'shift_start',   label: 'Shift Start',    type: 'time' },
      { key: 'shift_end',     label: 'Shift End',      type: 'time' },
      { key: 'checkin_open',  label: 'Check-in Open',  type: 'time' },
      { key: 'checkin_close', label: 'Check-in Close', type: 'time' },
    ],
  },
  {
    heading: 'Operational',
    fields: [
      { key: 'rating_window_hours',  label: 'Rating Window (hours)', type: 'int',   required: true, min: 1,  max: 48 },
      { key: 'invite_expiry_days',   label: 'Invite Expiry (days)',  type: 'int',   required: true, min: 1,  max: 90 },
      { key: 'driver_checkin_count', label: 'Driver Check-ins',      type: 'int',   min: 0, max: 10 },
    ],
  },
  {
    heading: 'Training',
    fields: [
      { key: 'graduation_assignments',            label: 'Graduation Assignments',    type: 'int',   required: true, min: 1,  max: 30 },
      { key: 'debt_escalation_threshold',         label: 'Debt Escalation Threshold', type: 'int',   required: true, min: 1,  max: 30 },
      { key: 'phase4_pass_score',                 label: 'Phase 4 Pass Score (%)',     type: 'float', required: true, min: 0,  max: 100, step: 0.1 },
      { key: 'underperforming_trainer_threshold', label: 'Underperforming Threshold', type: 'int',   required: true, min: 1,  max: 30 },
      { key: 'max_training_phase',                label: 'Max Training Phase',        type: 'int',   required: true, min: 1,  max: 10 },
    ],
  },
  {
    heading: 'Dispatch Weights',
    description: 'Controls how assignment preferences are weighted during dispatch.',
    fields: [
      { key: 'dispatch_weight_driver',        label: 'Driver Weight',        type: 'float', required: true, min: 0, max: 1, step: 0.01 },
      { key: 'dispatch_weight_trainer',       label: 'Trainer Weight',       type: 'float', required: true, min: 0, max: 1, step: 0.01 },
      { key: 'dispatch_weight_walker',        label: 'Walker Weight',        type: 'float', required: true, min: 0, max: 1, step: 0.01 },
      { key: 'dispatch_mutual_bonus',         label: 'Mutual Bonus',         type: 'float', required: true, min: 0, max: 1, step: 0.01 },
      { key: 'dispatch_tridirectional_bonus', label: 'Tridirectional Bonus', type: 'float', required: true, min: 0, max: 1, step: 0.01 },
      { key: 'dispatch_consecutive_penalty',  label: 'Consecutive Penalty',  type: 'float', required: true, min: 0, max: 1, step: 0.01 },
      { key: 'dispatch_weight_cap',           label: 'Weight Cap',           type: 'float', required: true, min: 0, max: 1, step: 0.01 },
    ],
  },
  {
    heading: 'Walker Rating',
    fields: [
      { key: 'flag_threshold', label: 'Flag Threshold', type: 'float', required: true, min: 0, max: 10, step: 0.1 },
    ],
  },
  {
    heading: 'Route Sort Tuning',
    description:
      'Advanced. Blank means the algorithm default — these are not required, and a company ' +
      'that never touches them sorts exactly as before. Change one at a time and read Sort ' +
      'Metrics before and after; the telemetry records which values produced which routes.',
    fields: [
      { key: 'route_assembly_mode', label: 'Assembly Mode', type: 'select', placeholder: 'block_completion',
        hint: 'group_first pulls a block\'s totes whole before crawling (ADR-272).',
        options: [
          { value: 'block_completion', label: 'Block completion (default)' },
          { value: 'group_first',      label: 'Group first (ADR-272)' },
        ] },
      { key: 'sort_w_dense',   label: 'Seed Weight — Density', type: 'float', min: 0, max: 5, step: 0.05, placeholder: '1.0',
        hint: 'Baseline. The other two must stay at or above this.' },
      { key: 'sort_w_time',    label: 'Seed Weight — Urgency',    type: 'float', min: 0, max: 5, step: 0.05, placeholder: '1.5',
        hint: 'Must be >= density, so a known-urgent block outranks the densest unknown one.' },
      { key: 'sort_w_diff',    label: 'Seed Weight — Difficulty', type: 'float', min: 0, max: 5, step: 0.05, placeholder: '1.3',
        hint: 'Must be >= density.' },
      { key: 'sort_w_doorman', label: 'Seed Weight — Doorman',    type: 'float', min: 0, max: 5, step: 0.05, placeholder: '0.5',
        hint: 'Subtracted: defers easy doorman-heavy blocks to later routes.' },
      { key: 'sort_walk_budget_m', label: 'Walk Budget (m)', type: 'float', min: 100, max: 10000, step: 50, placeholder: '900',
        hint: 'Cumulative metres along a route\'s traversal. Inert when blocks have no coordinates.' },
      { key: 'sort_span_cap_m',    label: 'Span Cap (m)',    type: 'float', min: 100, max: 10000, step: 50, placeholder: '700',
        hint: 'Straight-line diameter of a route. Also inert without coordinates.' },
      { key: 'sort_max_consecutive_no_fit', label: 'Max Steps Without Collecting', type: 'int', min: 1, max: 20, placeholder: '2',
        hint: 'Closes a route that keeps stepping to blocks whose totes do not fit.' },
      { key: 'sort_f5_load_floor_hs', label: 'F5 Load Floor (half-slots)', type: 'int', min: 0, max: 40, placeholder: '6',
        hint: 'Thin-block consolidation fires below this load. 6 = about 3 totes.' },
      { key: 'sort_f5_max_hops',      label: 'F5 Max Hops',      type: 'int',   min: 1, max: 6,  placeholder: '2',
        hint: 'Street steps the consolidation may bridge.' },
      { key: 'sort_f5_walk_radius_km', label: 'F5 Walk Radius (km)', type: 'float', min: 0.1, max: 5, step: 0.1, placeholder: '0.8',
        hint: 'Sanity cap on a hop-reachable block. Adjacency is the primary gate.' },
    ],
  },
];

const REQUIRED_CONFIG_KEYS = new Set(
  CONFIG_SECTIONS.flatMap(s => s.fields.filter(f => f.required).map(f => String(f.key)))
);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function displayValue(val: string | number | null, type: FieldType): string {
  if (val === null || val === undefined) return '—';
  if (type === 'float' && typeof val === 'number') return val.toFixed(2);
  return String(val);
}

function configToEditDraft(config: CompanyConfig): Record<string, string> {
  const d: Record<string, string> = {};
  for (const section of CONFIG_SECTIONS) {
    for (const f of section.fields) {
      const v = config[f.key];
      d[String(f.key)] = v !== null && v !== undefined ? String(v) : '';
    }
  }
  return d;
}

const ROLE_ORDER = ['admin', 'dispatch', 'management', 'driver', 'walker', 'trainer', 'trainee'];

const ACCOUNT_STATUS_BADGE: Record<string, { label: string; className: string; icon: React.ReactNode }> = {
  active: {
    label: 'Active',
    className: 'bg-success/10 text-success',
    icon: <UserCheck className="w-3 h-3" />,
  },
  pending_verification: {
    label: 'Pending',
    className: 'bg-warning/10 text-warning',
    icon: <Clock className="w-3 h-3" />,
  },
  deactivated: {
    label: 'Deactivated',
    className: 'bg-muted/40 text-muted-foreground',
    icon: <UserX className="w-3 h-3" />,
  },
};

// ---------------------------------------------------------------------------
// Section card wrapper
// ---------------------------------------------------------------------------

function SectionCard({ title, action, children }: {
  title: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="card space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">{title}</div>
        {action}
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Operating mode card (ADR-289)
// ---------------------------------------------------------------------------

/** The two directions are NOT mirror images, and the copy must say which.
 *  full -> workforce removes automated routing but leaves a working manual path.
 *  workforce -> full removes that manual path and replaces it with a pipeline
 *  that produces NOTHING until a manifest is uploaded and enriched — so the
 *  direction that sounds like an upgrade is the one that can leave a tenant with
 *  no routes at all on a shift morning. */
const MODE_COPY = {
  workforce: {
    heading: 'Turn package sorting OFF',
    stops: 'Manifest upload, station sort, route sort, package scanning and per-package returns stop being available.',
    keeps: 'Crews, dispatch, training, scheduling, compliance and scorecards keep working exactly as they do now.',
    warn: null as string | null,
  },
  full: {
    heading: 'Turn package sorting ON',
    stops: 'Manual tote entry is replaced by manifest-driven sorting.',
    keeps: 'Everything else is unchanged.',
    warn: 'There will be no routes until a manifest is uploaded and enriched. Switch this on the evening before a shift, not on the morning of one.',
  },
} as const;

function OperatingModeCard({
  detail,
  onChanged,
}: {
  detail: CompanyDetail;
  onChanged: (mode: 'full' | 'workforce') => void;
}) {
  const current = detail.config?.operating_mode ?? 'workforce';
  const target: 'full' | 'workforce' = current === 'full' ? 'workforce' : 'full';
  const copy = MODE_COPY[target];

  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Typed confirmation, not a checkbox: a super admin has several tenants open
  // at once and the realistic mistake is flipping the wrong one.
  const confirmed = typed.trim() === detail.slug;

  const reset = () => { setOpen(false); setTyped(''); setError(null); };

  const submit = async () => {
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    try {
      const res = await axiosClient.patch<{ operating_mode: 'full' | 'workforce'; notified: number }>(
        `/admin/companies/${detail.id}/operating-mode`,
        { operating_mode: target, confirm_slug: typed.trim() },
      );
      onChanged(res.data.operating_mode);
      setNotice(
        `Switched to ${res.data.operating_mode} mode. ${res.data.notified} admin(s) notified.`
      );
      reset();
    } catch (err: unknown) {
      // A 409 is the in-flight guard, not a failure of the request — it means
      // routes are still out and flipping now would strand a walker mid-route.
      setError(errorText(err, 'Could not change operating mode.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard
      title={
        <>
          {current === 'full'
            ? <PackageCheck className="w-4 h-4 text-success" />
            : <PackageX className="w-4 h-4 text-warning" />}
          <span className="font-semibold text-foreground text-sm">Operating Mode</span>
        </>
      }
      action={
        // Same treatment as the Configured / Connected badges above, so the
        // three read as one family. The first version used `accent`, which is a
        // pale violet in the light theme and rendered near-invisible.
        current === 'full' ? (
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-success/10 text-success font-medium">
            <PackageCheck className="w-3 h-3" /> Package sorting ON
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-warning/10 text-warning font-medium">
            <PackageX className="w-3 h-3" /> Package sorting OFF
          </span>
        )
      }
    >
      {error && <ErrorBanner message={error} />}
      {notice && (
        <div className="text-xs text-success bg-success/10 border border-success/20 rounded-lg px-3 py-2">
          {notice}
        </div>
      )}

      {!open ? (
        // Mirrors the Danger Zone's row: what it is on the left, the action on
        // the right. Previously a bare sentence with a grey button underneath,
        // which read as less consequential than the Discord card above it.
        <div className={`flex items-center justify-between gap-4 flex-wrap p-3 rounded-xl border ${
          current === 'full'
            ? 'border-success/20 bg-success/5'
            : 'border-warning/20 bg-warning/5'
        }`}>
          <div>
            <p className="text-sm font-medium text-foreground">
              {current === 'full'
                ? 'Package sorting is available to this company'
                : 'This company runs without a package feed'}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {current === 'full'
                ? 'Manifest upload, station sort, route sort and package scanning are all live.'
                : 'Those surfaces are hidden in the apps and their endpoints return 404. Crews, training and scheduling are unaffected.'}
            </p>
          </div>
          <button
            onClick={() => setOpen(true)}
            className={`flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-lg transition-colors ${
              current === 'full'
                ? 'bg-warning/10 text-warning hover:bg-warning/20'
                : 'bg-success/10 text-success hover:bg-success/20'
            }`}
          >
            {current === 'full'
              ? <><PackageX className="w-3.5 h-3.5" /> Turn OFF</>
              : <><PackageCheck className="w-3.5 h-3.5" /> Turn ON</>}
          </button>
        </div>
      ) : (
        <div className="space-y-3 p-3 rounded-xl border border-warning/30 bg-warning/5">
          <p className="text-sm font-semibold text-foreground">{copy.heading}</p>

          <ul className="text-xs text-muted-foreground space-y-1 list-disc pl-4">
            <li>{copy.stops}</li>
            <li>{copy.keeps}</li>
            <li><strong className="text-foreground">Nothing is deleted.</strong> Records from the other mode are kept and simply stop appearing.</li>
          </ul>

          {copy.warn && (
            <p className="text-xs text-warning font-medium border-l-2 border-warning pl-2">
              {copy.warn}
            </p>
          )}

          <div>
            <label className="text-xs text-muted-foreground">
              Type <code className="text-foreground font-mono">{detail.slug}</code> to confirm
            </label>
            <input
              value={typed}
              onChange={e => setTyped(e.target.value)}
              placeholder={detail.slug}
              autoFocus
              className="input mt-1 w-full font-mono text-sm"
            />
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={submit}
              disabled={!confirmed || busy}
              className="text-sm font-medium px-3 py-1.5 rounded-lg bg-warning/15 text-warning hover:bg-warning/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {busy ? 'Switching…' : copy.heading}
            </button>
            <button
              onClick={reset}
              disabled={busy}
              className="text-sm font-medium px-3 py-1.5 rounded-lg text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// 1. Company identity card
// ---------------------------------------------------------------------------

function IdentityCard({
  detail,
  onUpdated,
}: {
  detail: CompanyDetail;
  onUpdated: (d: Partial<CompanyDetail>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(detail.name);
  const [slug, setSlug] = useState(detail.slug);
  const [dspCode, setDspCode] = useState(detail.amazon_dsp_code ?? '');
  const [timezone, setTimezone] = useState(detail.timezone);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setName(detail.name);
    setSlug(detail.slug);
    setDspCode(detail.amazon_dsp_code ?? '');
    setTimezone(detail.timezone);
    setError(null);
    setEditing(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await axiosClient.patch(`/admin/companies/${detail.id}`, {
        name: name.trim(),
        slug: slug.trim(),
        amazon_dsp_code: dspCode.trim() || null,
        timezone,
      });
      onUpdated(res.data);
      setEditing(false);
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to save.'));
    } finally {
      setSaving(false);
    }
  };

  const icon = (
    <div className={`flex items-center justify-center w-10 h-10 rounded-xl shrink-0 ${
      detail.is_active ? 'bg-success/10' : 'bg-muted/30'
    }`}>
      <Building2 className={`w-5 h-5 ${detail.is_active ? 'text-success' : 'text-muted-foreground'}`} />
    </div>
  );

  if (editing) {
    return (
      <div className="card space-y-4">
        <div className="flex items-center gap-3">
          {icon}
          <p className="font-semibold text-foreground">Edit Company</p>
        </div>
        {error && <ErrorBanner message={error} />}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Company Name</label>
            <input className="input-field" value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Slug</label>
            <input className="input-field font-mono text-sm" value={slug} onChange={e => setSlug(e.target.value.toLowerCase())} />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Amazon DSP Code</label>
            <input className="input-field" value={dspCode} onChange={e => setDspCode(e.target.value)} placeholder="optional" />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Timezone</label>
            <select className="input-field" value={timezone} onChange={e => setTimezone(e.target.value)}>
              <option value="America/New_York">America/New_York (ET)</option>
              <option value="America/Chicago">America/Chicago (CT)</option>
              <option value="America/Denver">America/Denver (MT)</option>
              <option value="America/Los_Angeles">America/Los_Angeles (PT)</option>
              <option value="America/Phoenix">America/Phoenix (AZ)</option>
              <option value="America/Anchorage">America/Anchorage (AKT)</option>
              <option value="Pacific/Honolulu">Pacific/Honolulu (HT)</option>
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={() => setEditing(false)} className="btn-ghost flex items-center gap-1.5 text-sm">
            <X className="w-3.5 h-3.5" /> Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-1.5 text-sm">
            <Save className="w-3.5 h-3.5" />
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          {icon}
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-lg font-bold text-foreground">{detail.name}</h1>
              {detail.is_active ? (
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-success/10 text-success font-medium">Active</span>
              ) : (
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-muted/40 text-muted-foreground font-medium">Inactive</span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1 flex-wrap">
              <span className="text-xs text-muted-foreground font-mono">{detail.slug}</span>
              {detail.amazon_dsp_code && (
                <span className="text-xs text-muted-foreground">{detail.amazon_dsp_code}</span>
              )}
              <span className="text-xs text-muted-foreground">{detail.timezone}</span>
              <span className="text-xs text-muted-foreground">
                Created {new Date(detail.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        </div>
        <button
          onClick={startEdit}
          className="flex items-center gap-1.5 text-sm text-violet-500 hover:text-violet-400 transition-colors font-medium"
        >
          <Pencil className="w-3.5 h-3.5" /> Edit
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. Config status breakdown
// ---------------------------------------------------------------------------

function ConfigStatusCard({ config }: { config: CompanyConfig }) {
  const missingRequired = Array.from(REQUIRED_CONFIG_KEYS).filter(
    key => config[key as keyof CompanyConfig] === null
  );

  // Find a human label for each missing key
  const allFields = CONFIG_SECTIONS.flatMap(s => s.fields);
  const missingLabels = missingRequired.map(key => {
    const meta = allFields.find(f => String(f.key) === key);
    return meta?.label ?? key;
  });

  return (
    <SectionCard
      title={
        <>
          <Settings2 className="w-4 h-4 text-violet-500" />
          <span className="font-semibold text-foreground text-sm">Setup Status</span>
          {config.is_configured ? (
            <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-success/10 text-success font-medium">
              <ShieldCheck className="w-3 h-3" /> Configured
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-warning/10 text-warning font-medium">
              <ShieldAlert className="w-3 h-3" /> Incomplete
            </span>
          )}
        </>
      }
    >
      {missingRequired.length === 0 ? (
        <p className="text-sm text-success flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" />
          All required fields are set.
        </p>
      ) : (
        <div>
          <p className="text-xs text-muted-foreground mb-2">
            {missingRequired.length} required {missingRequired.length === 1 ? 'field' : 'fields'} not yet configured:
          </p>
          <div className="flex flex-wrap gap-1.5">
            {missingLabels.map(label => (
              <span key={label} className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-danger/10 text-danger font-medium">
                <AlertTriangle className="w-3 h-3" />
                {label}
              </span>
            ))}
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// 3. Employee snapshot
// ---------------------------------------------------------------------------

function EmployeeCard({ companyId }: { companyId: string }) {
  const [summary, setSummary] = useState<EmployeeSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient
      .get<EmployeeSummary>(`/admin/companies/${companyId}/employees/summary`)
      .then(res => setSummary(res.data))
      .catch(() => setError('Failed to load employee data.'))
      .finally(() => setLoading(false));
  }, [companyId]);

  const roles = summary
    ? ROLE_ORDER.filter(r => summary.by_role[r])
    : [];

  return (
    <SectionCard
      title={
        <>
          <Users className="w-4 h-4 text-violet-500" />
          <span className="font-semibold text-foreground text-sm">Employees</span>
          {summary && (
            <span className="text-xs text-muted-foreground">
              {summary.total} total
            </span>
          )}
        </>
      }
    >
      {loading && (
        <div className="grid grid-cols-4 gap-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-14 bg-accent/60 rounded-xl animate-pulse" />
          ))}
        </div>
      )}
      {error && <ErrorBanner message={error} />}
      {summary && (
        <div className="space-y-5">
          {/* Role breakdown */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
            {roles.length === 0 ? (
              <p className="col-span-4 text-sm text-muted-foreground">No employees yet.</p>
            ) : (
              roles.map(role => (
                <div key={role} className="bg-accent/40 rounded-xl p-3">
                  <p className="text-xs text-muted-foreground capitalize mb-1">{role}</p>
                  <p className="text-xl font-bold text-foreground">{summary.by_role[role]}</p>
                </div>
              ))
            )}
          </div>

          {/* Admin list */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Company Admins
            </p>
            {summary.admins.length === 0 ? (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-warning/5 border border-warning/20">
                <UserX className="w-4 h-4 text-warning shrink-0" />
                <p className="text-sm text-warning">No admin bootstrapped yet — use the Bootstrap Admin action from the companies list.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {summary.admins.map(admin => {
                  const badge = ACCOUNT_STATUS_BADGE[admin.account_status] ?? {
                    label: admin.account_status,
                    className: 'bg-muted/40 text-muted-foreground',
                    icon: null,
                  };
                  return (
                    <div key={admin.employee_id} className="flex items-center justify-between gap-3 p-2.5 rounded-xl bg-accent/40 border border-border/40">
                      <div>
                        <p className="text-sm font-medium text-foreground">{admin.name}</p>
                        {admin.email && (
                          <p className="text-xs text-muted-foreground font-mono">{admin.email}</p>
                        )}
                      </div>
                      <span className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${badge.className}`}>
                        {badge.icon}
                        {badge.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// 4. Configuration editor
// ---------------------------------------------------------------------------

function ConfigEditorCard({
  companyId,
  config,
  onUpdated,
}: {
  companyId: string;
  config: CompanyConfig;
  onUpdated: (cfg: CompanyConfig) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const startEdit = () => {
    setDraft(configToEditDraft(config));
    setSaveError(null);
    setEditing(true);
  };

  const fillDefaults = () => {
    setDraft(prev => ({ ...prev, ...PLATFORM_DEFAULTS }));
  };

  const handleSave = async () => {
    setSaveError(null);
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const section of CONFIG_SECTIONS) {
        for (const f of section.fields) {
          const raw = draft[String(f.key)];
          if (raw === '' || raw === undefined) continue;
          if (f.type === 'int') payload[String(f.key)] = parseInt(raw, 10);
          else if (f.type === 'float') payload[String(f.key)] = parseFloat(raw);
          else payload[String(f.key)] = raw;   // time + select are sent as strings
        }
      }
      const res = await axiosClient.patch<CompanyConfig>(
        `/admin/companies/${companyId}/config`,
        payload,
      );
      onUpdated(res.data);
      setEditing(false);
    } catch (err: unknown) {
      setSaveError(errorText(err, 'Failed to save config.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SectionCard
      title={
        <>
          <Settings2 className="w-4 h-4 text-violet-500" />
          <span className="font-semibold text-foreground text-sm">Configuration</span>
        </>
      }
      action={
        !editing ? (
          <button
            onClick={startEdit}
            className="flex items-center gap-1.5 text-sm text-violet-500 hover:text-violet-400 transition-colors font-medium"
          >
            <Pencil className="w-3.5 h-3.5" /> Edit
          </button>
        ) : undefined
      }
    >
      {saveError && <ErrorBanner message={saveError} />}

      <div className="space-y-8">
        {CONFIG_SECTIONS.map(section => (
          <div key={section.heading}>
            <div className="mb-3">
              <p className="text-sm font-semibold text-foreground">{section.heading}</p>
              {section.description && (
                <p className="text-xs text-muted-foreground mt-0.5">{section.description}</p>
              )}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {section.fields.map(f => (
                <div key={String(f.key)} className="bg-accent/40 rounded-xl p-3">
                  <p className="text-xs text-muted-foreground mb-1.5">
                    {f.label}
                    {f.required && <span className="text-danger ml-0.5">*</span>}
                  </p>
                  {editing ? (
                    f.type === 'select' ? (
                      <select
                        className="w-full bg-background border border-border rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
                        value={draft[String(f.key)] ?? ''}
                        onChange={e => setDraft(prev => ({ ...prev, [String(f.key)]: e.target.value }))}
                      >
                        <option value="">Default{f.placeholder ? ` (${f.placeholder})` : ''}</option>
                        {(f.options ?? []).map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={f.type === 'time' ? 'time' : 'number'}
                        step={f.step ?? (f.type === 'int' ? 1 : undefined)}
                        min={f.min}
                        max={f.max}
                        className="w-full bg-background border border-border rounded-lg px-2.5 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-violet-500"
                        value={draft[String(f.key)] ?? ''}
                        onChange={e => setDraft(prev => ({ ...prev, [String(f.key)]: e.target.value }))}
                        placeholder={f.required ? 'required' : f.placeholder ?? 'optional'}
                      />
                    )
                  ) : (
                    <p className={`text-sm font-mono font-semibold ${config[f.key] === null ? 'text-muted-foreground' : 'text-foreground'}`}>
                      {config[f.key] === null && f.placeholder
                        ? `${f.placeholder} (default)`
                        : displayValue(config[f.key] as string | number | null, f.type)}
                    </p>
                  )}
                  {editing && f.hint && (
                    <p className="text-[11px] leading-snug text-muted-foreground mt-1.5">{f.hint}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <div className="flex items-center justify-between pt-4 border-t border-border/40">
          <button
            onClick={fillDefaults}
            className="flex items-center gap-1.5 text-sm text-violet-400 hover:text-violet-300 transition-colors font-medium"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Fill with platform defaults
          </button>
          <div className="flex items-center gap-2">
            <button onClick={() => setEditing(false)} className="btn-ghost flex items-center gap-1.5 text-sm">
              <X className="w-3.5 h-3.5" /> Cancel
            </button>
            <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-1.5 text-sm">
              <Save className="w-3.5 h-3.5" />
              {saving ? 'Saving…' : 'Save Config'}
            </button>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// 5. Discord configuration
// ---------------------------------------------------------------------------

interface DiscordConfig {
  discord_guild_id:            number | null;
  discord_drivers_channel_id:  number | null;
  discord_trainers_channel_id: number | null;
  discord_captains_channel_id: number | null;
  discord_general_channel_id:  number | null;
  discord_invite_channel_id:   number | null;
  discord_role_admin:          number | null;
  discord_role_manager:        number | null;
  discord_role_asheflow:       number | null;
  discord_role_bot:            number | null;
  discord_role_dispatch:       number | null;
  discord_role_driver:         number | null;
  discord_role_trainer:        number | null;
  discord_role_captain:        number | null;
  discord_role_walker:         number | null;
}

type DiscordDraft = Record<keyof DiscordConfig, string>;

const DISCORD_FIELDS: { key: keyof DiscordConfig; label: string; hint: string }[] = [
  { key: 'discord_guild_id',            label: 'Guild ID',              hint: 'Server snowflake ID' },
  { key: 'discord_general_channel_id',  label: 'General Channel',       hint: '#general channel ID' },
  { key: 'discord_drivers_channel_id',  label: 'Drivers Channel',       hint: '#drivers-chat ID' },
  { key: 'discord_trainers_channel_id', label: 'Trainers Channel',      hint: '#trainers-chat ID' },
  { key: 'discord_captains_channel_id', label: 'Captains Channel',      hint: '#captains ID' },
  { key: 'discord_invite_channel_id',   label: 'Invite Channel',        hint: 'Channel used for onboarding invites' },
  { key: 'discord_role_admin',          label: 'Admin Role',            hint: 'Role ID' },
  { key: 'discord_role_manager',        label: 'Manager Role',          hint: 'Role ID' },
  { key: 'discord_role_asheflow',       label: 'AsheFlow Role',         hint: 'Base member role ID' },
  { key: 'discord_role_bot',            label: 'Bot Role',              hint: 'Role ID' },
  { key: 'discord_role_dispatch',       label: 'Dispatch Role',         hint: 'Role ID' },
  { key: 'discord_role_driver',         label: 'Driver Role',           hint: 'Role ID' },
  { key: 'discord_role_trainer',        label: 'Trainer Role',          hint: 'Trainer role ID (was "Captain")' },
  { key: 'discord_role_captain',        label: 'Captain Role',          hint: 'Captain role ID (route leads)' },
  { key: 'discord_role_walker',         label: 'Walker/Trainee Role',   hint: 'Role ID' },
];

function discordConfigToEditDraft(cfg: DiscordConfig): DiscordDraft {
  const d = {} as DiscordDraft;
  for (const f of DISCORD_FIELDS) {
    const v = cfg[f.key];
    d[f.key] = v !== null && v !== undefined ? String(v) : '';
  }
  return d;
}

function DiscordConfigCard({ companyId }: { companyId: string }) {
  const [cfg, setCfg] = useState<DiscordConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DiscordDraft>({} as DiscordDraft);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient
      .get<DiscordConfig>(`/admin/companies/${companyId}/discord-config`)
      .then(res => setCfg(res.data))
      .catch(() => setLoadError('Failed to load Discord config.'))
      .finally(() => setLoading(false));
  }, [companyId]);

  const startEdit = () => {
    if (!cfg) return;
    setDraft(discordConfigToEditDraft(cfg));
    setSaveError(null);
    setEditing(true);
  };

  const handleSave = async () => {
    setSaveError(null);
    setSaving(true);
    try {
      const payload: Record<string, string> = {};
      for (const f of DISCORD_FIELDS) {
        const raw = draft[f.key];
        if (raw && /^\d+$/.test(raw)) payload[f.key] = raw;
      }
      const res = await axiosClient.patch<DiscordConfig>(
        `/admin/companies/${companyId}/discord-config`,
        payload,
      );
      setCfg(res.data);
      setEditing(false);
    } catch (err: unknown) {
      setSaveError(errorText(err, 'Failed to save Discord config.'));
    } finally {
      setSaving(false);
    }
  };

  const isConnected = cfg?.discord_guild_id != null;

  return (
    <SectionCard
      title={
        <>
          <Bot className="w-4 h-4 text-violet-500" />
          <span className="font-semibold text-foreground text-sm">Discord Integration</span>
          {!loading && (
            isConnected ? (
              <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-success/10 text-success font-medium">
                <ShieldCheck className="w-3 h-3" /> Connected
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-muted/40 text-muted-foreground font-medium">
                Not configured
              </span>
            )
          )}
        </>
      }
      action={
        !loading && !editing ? (
          <button
            onClick={startEdit}
            className="flex items-center gap-1.5 text-sm text-violet-500 hover:text-violet-400 transition-colors font-medium"
          >
            <Pencil className="w-3.5 h-3.5" /> {isConnected ? 'Edit' : 'Configure'}
          </button>
        ) : undefined
      }
    >
      {loading && <div className="h-8 w-32 bg-accent/60 rounded animate-pulse" />}
      {loadError && <ErrorBanner message={loadError} />}
      {saveError && <ErrorBanner message={saveError} />}

      {cfg && !editing && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {DISCORD_FIELDS.map(f => (
            <div key={f.key} className="bg-accent/40 rounded-xl p-3">
              <p className="text-xs text-muted-foreground mb-1">{f.label}</p>
              <p className={`text-xs font-mono font-semibold ${cfg[f.key] !== null ? 'text-foreground' : 'text-muted-foreground/50'}`}>
                {cfg[f.key] !== null ? String(cfg[f.key]) : '—'}
              </p>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {DISCORD_FIELDS.map(f => (
              <div key={f.key}>
                <label className="block text-xs text-muted-foreground mb-1">
                  {f.label}
                  <span className="ml-1 text-muted-foreground/50">({f.hint})</span>
                </label>
                <input
                  className="input-field font-mono text-sm"
                  type="number"
                  step="1"
                  value={draft[f.key]}
                  onChange={e => setDraft(prev => ({ ...prev, [f.key]: e.target.value }))}
                  placeholder="snowflake ID"
                />
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setEditing(false)} className="btn-ghost flex items-center gap-1.5 text-sm">
              <X className="w-3.5 h-3.5" /> Cancel
            </button>
            <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-1.5 text-sm">
              <Save className="w-3.5 h-3.5" />
              {saving ? 'Saving…' : 'Save Discord Config'}
            </button>
          </div>
        </>
      )}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// 6. Danger zone
// ---------------------------------------------------------------------------

function DangerZoneCard({
  detail,
  onToggled,
}: {
  detail: CompanyDetail;
  onToggled: (active: boolean) => void;
}) {
  const [toggling, setToggling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleToggle = async () => {
    setToggling(true);
    setError(null);
    try {
      const action = detail.is_active ? 'deactivate' : 'reactivate';
      await axiosClient.patch(`/admin/companies/${detail.id}/${action}`);
      onToggled(!detail.is_active);
    } catch (err: unknown) {
      setError(errorText(err, 'Action failed.'));
    } finally {
      setToggling(false);
    }
  };

  return (
    <SectionCard
      title={
        <>
          <AlertTriangle className="w-4 h-4 text-danger" />
          <span className="font-semibold text-foreground text-sm">Danger Zone</span>
        </>
      }
    >
      {error && <ErrorBanner message={error} />}
      <div className="flex items-center justify-between gap-4 flex-wrap p-3 rounded-xl border border-danger/20 bg-danger/5">
        <div>
          <p className="text-sm font-medium text-foreground">
            {detail.is_active ? 'Deactivate company' : 'Reactivate company'}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {detail.is_active
              ? 'Prevents employees from accessing the platform. No data is deleted.'
              : 'Restores platform access for all employees of this company.'}
          </p>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggling}
          className={`flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-lg transition-colors ${
            detail.is_active
              ? 'bg-danger/10 text-danger hover:bg-danger/20'
              : 'bg-success/10 text-success hover:bg-success/20'
          }`}
        >
          {detail.is_active
            ? <><XCircle className="w-3.5 h-3.5" /> Deactivate</>
            : <><CheckCircle2 className="w-3.5 h-3.5" /> Reactivate</>
          }
        </button>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function CompanyDetailPage() {
  const { companyId } = useParams<{ companyId: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!companyId) return;
    axiosClient
      .get<CompanyDetail>(`/admin/companies/${companyId}`)
      .then(res => setDetail(res.data))
      .catch(() => setError('Failed to load company details.'))
      .finally(() => setLoading(false));
  }, [companyId]);

  if (loading) {
    return (
      <div className="space-y-6 animate-slide-up">
        <div className="h-5 w-32 bg-accent rounded animate-pulse" />
        <div className="card">
          <div className="h-8 w-48 bg-accent rounded animate-pulse mb-2" />
          <div className="h-4 w-72 bg-accent/60 rounded animate-pulse" />
        </div>
        <div className="card">
          <div className="h-5 w-24 bg-accent rounded animate-pulse mb-4" />
          <div className="grid grid-cols-4 gap-3">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-16 bg-accent/60 rounded-xl animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="space-y-4">
        <button onClick={() => navigate('/superadmin/companies')} className="btn-ghost flex items-center gap-2 text-sm">
          <ArrowLeft className="w-4 h-4" /> Back to Companies
        </button>
        <ErrorBanner message={error ?? 'Company not found.'} />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-5"
    >
      {/* Breadcrumb strip */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <button
          onClick={() => navigate('/superadmin/companies')}
          className="flex items-center gap-1.5 hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Companies
        </button>
        <span className="text-border">/</span>
        <span className="text-foreground font-medium truncate">{detail.name}</span>
      </div>

      {/* 1. Identity */}
      <IdentityCard
        detail={detail}
        onUpdated={patch => setDetail(prev => prev ? { ...prev, ...patch } : prev)}
      />

      {/* 2. Setup status */}
      {detail.config && <ConfigStatusCard config={detail.config} />}

      {/* 3. Employees */}
      {companyId && <EmployeeCard companyId={companyId} />}

      {/* 4. Config editor */}
      {detail.config && (
        <ConfigEditorCard
          companyId={detail.id}
          config={detail.config}
          onUpdated={cfg => setDetail(prev => prev ? { ...prev, config: cfg } : prev)}
        />
      )}

      {/* 5. Discord integration */}
      {companyId && <DiscordConfigCard companyId={companyId} />}

      {/* 6. Danger zone */}
      {/* ADR-289: sits ABOVE the Danger Zone deliberately. It is a high-impact
          change but a reversible, non-destructive one — grouping it with
          deactivation would overstate it, and burying it below would understate
          how much of the product it decides. */}
      <OperatingModeCard
        detail={detail}
        onChanged={mode => setDetail(prev =>
          prev && prev.config
            ? { ...prev, config: { ...prev.config, operating_mode: mode } }
            : prev
        )}
      />

      <DangerZoneCard
        detail={detail}
        onToggled={active => setDetail(prev => prev ? { ...prev, is_active: active } : prev)}
      />
    </motion.div>
  );
}
