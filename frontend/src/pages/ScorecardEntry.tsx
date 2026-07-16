import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import ErrorBanner from '../components/ui/ErrorBanner';
import { Award, Plus, Trash2, Save, Upload } from 'lucide-react';
import type { Employee, ScorecardMetric } from '../api/types';

/** Management: enter an Amazon weekly scorecard (ADR-204 Phase B, structured entry).
 *  Phase C will add file upload + auto-extract that pre-fills this same form. */

type MetricRow = Omit<ScorecardMetric, 'id'>;

// The canonical NYCD metric rows (from the scorecard layout) as a starting template.
const TEMPLATE: MetricRow[] = [
  { key: 'packages_delivered', label: 'Packages Delivered', value: '', unit: null, tier: null, flag: null, sort_order: 0 },
  { key: 'dsb_dpmo_tier', label: 'DSB DPMO Tier', value: '', unit: null, tier: null, flag: null, sort_order: 1 },
  { key: 'delivery_success_behavior', label: 'Delivery Success Behavior', value: '', unit: null, tier: null, flag: null, sort_order: 2 },
  { key: 'delivery_completion_dpmo', label: 'Delivery Completion DPMO', value: '', unit: 'DPMO', tier: null, flag: null, sort_order: 3 },
  { key: 'cdf', label: 'CDF', value: '', unit: null, tier: null, flag: null, sort_order: 4 },
  { key: 'pod_tier', label: 'POD Tier', value: '', unit: null, tier: null, flag: null, sort_order: 5 },
  { key: 'pod_score', label: 'POD Score', value: '', unit: '%', tier: null, flag: null, sort_order: 6 },
  { key: 'pod_success', label: 'POD Success', value: '', unit: null, tier: null, flag: null, sort_order: 7 },
  { key: 'pod_rejects', label: 'POD Rejects', value: '', unit: null, tier: null, flag: null, sort_order: 8 },
];

function isoWeekNow(): string {
  const d = new Date();
  const target = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNr = (d.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - dayNr + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((target.getTime() - firstThursday.getTime()) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
  return `${target.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
}

export default function ScorecardEntry() {
  const [week, setWeek] = useState(isoWeekNow());
  const [scope, setScope] = useState<'individual' | 'company'>('individual');
  const [employeeId, setEmployeeId] = useState('');
  const [overall, setOverall] = useState('');
  const [metrics, setMetrics] = useState<MetricRow[]>(TEMPLATE.map(m => ({ ...m })));
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [parsing, setParsing] = useState(false);

  // Phase C: upload the Amazon scorecard image → Textract draft pre-fills the form.
  // The manager reviews/edits before Save (a misparse never saves unreviewed).
  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = '';   // allow re-selecting the same file
    if (!f) return;
    setError(null); setSaved(false); setParsing(true);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const { data } = await axiosClient.post('/scorecards/parse', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (data.week) setWeek(data.week);
      if (data.overall_standing) setOverall(data.overall_standing);
      if (Array.isArray(data.metrics) && data.metrics.length) {
        setMetrics(data.metrics.map((m: any, i: number) => ({
          key: m.key, label: m.label, value: m.value ?? '',
          unit: m.unit ?? null, tier: m.tier ?? null, flag: m.flag ?? null, sort_order: m.sort_order ?? i,
        })));
      }
    } catch (err: any) {
      const msg = errorText(err, 'Could not parse the scorecard.');
      setError(err?.response?.status === 503
        ? 'Auto-parse is unavailable here — enter the scorecard manually below.'
        : msg);
    } finally { setParsing(false); }
  };

  useEffect(() => {
    axiosClient.get<Employee[]>('/employees/')
      .then(({ data }) => setEmployees((data ?? []).filter(e => e.is_active)))
      .catch(() => setEmployees([]));
  }, []);

  const setMetric = (i: number, patch: Partial<MetricRow>) =>
    setMetrics(ms => ms.map((m, idx) => idx === i ? { ...m, ...patch } : m));
  const addMetric = () =>
    setMetrics(ms => [...ms, { key: '', label: '', value: '', unit: null, tier: null, flag: null, sort_order: ms.length }]);
  const removeMetric = (i: number) => setMetrics(ms => ms.filter((_, idx) => idx !== i));

  const save = async () => {
    setError(null); setSaved(false);
    if (scope === 'individual' && !employeeId) { setError('Pick an employee for an individual scorecard.'); return; }
    const filled = metrics.filter(m => m.key.trim() && m.label.trim() && m.value.trim());
    if (filled.length === 0) { setError('Fill in at least one metric.'); return; }
    setSaving(true);
    try {
      await axiosClient.post('/scorecards', {
        week: week.trim(),
        scope,
        employee_id: scope === 'individual' ? employeeId : null,
        overall_standing: overall.trim() || null,
        metrics: filled,
      });
      setSaved(true);
    } catch (e) {
      setError(errorText(e, 'Could not save the scorecard.'));
    } finally { setSaving(false); }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-5 animate-slide-up">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-accent">
          <Award className="w-4 h-4 text-primary" />
        </div>
        <h1 className="page-title">Enter Amazon Scorecard</h1>
      </div>

      {error && <ErrorBanner message={error} />}
      {saved && <div className="rounded-lg border border-emerald-300/40 bg-emerald-50 p-3 text-sm text-emerald-700">Scorecard saved.</div>}

      {/* Upload → auto-extract (Phase C). Pre-fills the form; review before saving. */}
      <label className="card flex items-center gap-3 cursor-pointer hover:border-primary transition-colors">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-accent shrink-0">
          <Upload className="w-4 h-4 text-primary" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium text-foreground">{parsing ? 'Reading scorecard…' : 'Upload scorecard image'}</p>
          <p className="text-xs text-muted-foreground">Auto-fills the fields below — review, then save. Or fill them manually.</p>
        </div>
        <input type="file" accept="image/*,.pdf" onChange={onUpload} disabled={parsing} className="hidden" />
      </label>

      <div className="card space-y-3">
        <div className="flex flex-wrap gap-3">
          <label className="text-sm flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Week</span>
            <input value={week} onChange={e => setWeek(e.target.value)} placeholder="2026-W28"
                   className="rounded-lg border border-border bg-background px-3 py-2 text-sm w-32" />
          </label>
          <label className="text-sm flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Scope</span>
            <select value={scope} onChange={e => { setScope(e.target.value as any); setSaved(false); }}
                    className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
              <option value="individual">Individual (DA)</option>
              <option value="company">Company (station)</option>
            </select>
          </label>
          {scope === 'individual' && (
            <label className="text-sm flex flex-col gap-1 flex-1 min-w-[180px]">
              <span className="text-xs font-semibold text-muted-foreground uppercase">Employee</span>
              <select value={employeeId} onChange={e => setEmployeeId(e.target.value)}
                      className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
                <option value="">Select…</option>
                {employees.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            </label>
          )}
          <label className="text-sm flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Overall Standing</span>
            <input value={overall} onChange={e => setOverall(e.target.value)} placeholder="PLATINUM"
                   className="rounded-lg border border-border bg-background px-3 py-2 text-sm w-36" />
          </label>
        </div>
      </div>

      <div className="card space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">Metrics</h2>
          <button onClick={addMetric} className="text-xs inline-flex items-center gap-1 text-primary hover:underline">
            <Plus className="w-3.5 h-3.5" /> Add metric
          </button>
        </div>
        <div className="space-y-2">
          {metrics.map((m, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-center">
              <input value={m.label} onChange={e => setMetric(i, { label: e.target.value })} placeholder="Label"
                     className="col-span-4 rounded border border-border bg-background px-2 py-1.5 text-sm" />
              <input value={m.value} onChange={e => setMetric(i, { value: e.target.value })} placeholder="Value"
                     className="col-span-3 rounded border border-border bg-background px-2 py-1.5 text-sm" />
              <select value={m.flag ?? ''} onChange={e => setMetric(i, { flag: (e.target.value || null) as any })}
                      className="col-span-4 rounded border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">No flag</option>
                <option value="excellent">Excellent</option>
                <option value="needs_focus">Needs Focus</option>
              </select>
              <button onClick={() => removeMetric(i)} className="col-span-1 text-muted-foreground hover:text-danger flex justify-center">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <button onClick={save} disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-primary text-white px-4 py-2 text-sm font-medium disabled:opacity-50">
        <Save className="w-4 h-4" /> {saving ? 'Saving…' : 'Save Scorecard'}
      </button>
    </div>
  );
}
