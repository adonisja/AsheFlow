import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import SelectMenu from '../components/ui/SelectMenu';
import ScorecardBulkImport from '../components/ScorecardBulkImport';
import { errorText } from '../utils/errorText';
import ErrorBanner from '../components/ui/ErrorBanner';
import { Award, Plus, Trash2, Save, Upload } from 'lucide-react';
import type { Employee, ScorecardMetric, ScorecardCrossCheck } from '../api/types';
import { Link } from 'react-router-dom';

/** Management: enter an Amazon weekly scorecard (ADR-204 Phase B, structured entry).
 *  Phase C will add file upload + auto-extract that pre-fills this same form. */

type MetricRow = Omit<ScorecardMetric, 'id'>;

/* The rows on a real DA card, in card order (ADR-475 D1/D2).
 *
 * KEYS MATCH THE BACKEND REGISTRY. The previous template used a parallel
 * vocabulary -- pod_score, cdf, delivery_completion_dpmo -- that existed
 * nowhere else, so a stored target could never match an ingested metric and
 * ADR-473's targets were wired to nothing.
 *
 * ONE LIST FOR BOTH TRACKS, deliberately. Management enters cards for walkers
 * and drivers alike, and a real walker card carries all six safety rows reading
 * "No Data" (ADR-474). Filtering the form would hide fields the reviewer needs
 * and make our card harder to reconcile against Amazon's.
 */
const NO_DATA = 'No Data';

const TEMPLATE: MetricRow[] = [
  // Quality
  { key: 'dc_dpmo', label: 'Delivery Completion DPMO', value: '', unit: 'DPMO', tier: null, flag: null, sort_order: 0 },
  { key: 'dsb_dpmo', label: 'Delivery Success Behaviors', value: '', unit: 'DPMO', tier: null, flag: null, sort_order: 1 },
  { key: 'ces_dpmo', label: 'Customer Escalations Defect', value: '', unit: 'DPMO', tier: null, flag: null, sort_order: 2 },
  { key: 'cdf_dpmo', label: 'Customer Delivery Feedback (CDF DPMO)', value: '', unit: 'DPMO', tier: null, flag: null, sort_order: 3 },
  { key: 'cdf_negative', label: 'Customer Delivery Feedback - Negative', value: '', unit: null, tier: null, flag: null, sort_order: 4 },
  { key: 'pod', label: 'POD Acceptance Rate', value: '', unit: '%', tier: null, flag: null, sort_order: 5 },
  // Safety. Present for BOTH tracks -- a walker card shows these as "No Data"
  // rather than omitting them.
  { key: 'fico', label: 'Safe Driving Metric', value: '', unit: null, tier: null, flag: null, sort_order: 6 },
  { key: 'seatbelt_rate', label: 'Seatbelt-Off Rate', value: '', unit: null, tier: null, flag: null, sort_order: 7 },
  { key: 'speeding_rate', label: 'Speeding Event Rate', value: '', unit: null, tier: null, flag: null, sort_order: 8 },
  { key: 'distractions_rate', label: 'Distractions Rate', value: '', unit: null, tier: null, flag: null, sort_order: 9 },
  { key: 'following_distance_rate', label: 'Following Distance Rate', value: '', unit: null, tier: null, flag: null, sort_order: 10 },
  { key: 'signsignal_rate', label: 'Sign/Signal Violations', value: '', unit: null, tier: null, flag: null, sort_order: 11 },
  // Context, not a scored metric.
  { key: 'packages_delivered', label: 'Packages Delivered', value: '', unit: null, tier: null, flag: null, sort_order: 12 },
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
  const [crossCheck, setCrossCheck] = useState<ScorecardCrossCheck | null>(null);
  // ADR-243: which contestable metrics to carry into an appeal. Pre-selected
  // from the backend's `contestable` flag — the manager can deselect, but the
  // default is what our own records actually dispute.
  const [appealPick, setAppealPick] = useState<Set<string>>(new Set());
  const [appealBusy, setAppealBusy] = useState(false);
  const [appealId, setAppealId] = useState<string | null>(null);

/** Open a draft appeal from the cross-check.
   *
   * Values are SNAPSHOTTED into the appeal now rather than referenced: a
   * corrected scorecard re-upload clears and rewrites scorecard_metrics, which
   * would otherwise silently rewrite the evidence the appeal was built on.
   * The RTS reason counts travel as per-item evidence, since that is the
   * substance of a delivery-defect dispute.
   */
  const createAppeal = async () => {
    if (!crossCheck) return;
    setAppealBusy(true);
    setError(null);
    try {
      const items = crossCheck.items
        .filter(i => appealPick.has(i.metric))
        .map((i, idx) => ({
          metric_key: i.metric,
          metric_label: i.metric.replace(/_/g, ' '),
          amazon_value: i.amazon_value != null ? String(i.amazon_value) : null,
          our_value: i.our_value != null ? String(i.our_value) : null,
          delta: i.delta,
          evidence: {
            rts_reasons: crossCheck.rts_evidence,
            // ADR-301: whichever side actually has a number. Workforce mode
            // reports carried parcels, not deliveries, and null when no route
            // that week had a recorded count — an appeal must not cite a
            // figure we do not hold.
            our_delivered: crossCheck.our_delivered,
            our_carried: crossCheck.our_carried,
            routes_unrecorded: crossCheck.routes_unrecorded,
            precision: crossCheck.precision,
            our_rts: crossCheck.our_rts,
            our_missing: crossCheck.our_missing,
            week_start: crossCheck.week_start,
            week_end: crossCheck.week_end,
          },
          claim: i.note || null,
          sort_order: idx,
        }));
      const { data } = await axiosClient.post('/scorecard-appeals', {
        scorecard_id: crossCheck.scorecard_id,
        title: `Week ${crossCheck.week} — ${items.length} contested metric${items.length === 1 ? '' : 's'}`,
        rationale: null,
        items,
      });
      setAppealId(data.id);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } };
      // Surfaces the 409 "an open appeal already exists" rather than a generic
      // failure, since that guard has a specific and actionable explanation.
      setError(e.response?.data?.detail ?? 'Could not open an appeal.');
    } finally {
      setAppealBusy(false);
    }
  };

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
        ? 'Auto-parse is unavailable here. Enter the scorecard manually below.'
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
    setSaving(true); setCrossCheck(null);
    try {
      const { data } = await axiosClient.post('/scorecards', {
        week: week.trim(),
        scope,
        employee_id: scope === 'individual' ? employeeId : null,
        overall_standing: overall.trim() || null,
        metrics: filled,
      });
      setSaved(true);
      // Individual scorecards: immediately cross-check against our data.
      if (scope === 'individual' && data?.id) {
        try {
          const xc = await axiosClient.get<ScorecardCrossCheck>(`/scorecards/${data.id}/cross-check`);
          setAppealPick(new Set(xc.data.items.filter(i => i.contestable).map(i => i.metric)));
          setAppealId(null);
          setCrossCheck(xc.data);
        } catch { /* cross-check is best-effort */ }
      }
    } catch (e) {
      setError(errorText(e, 'Could not save the scorecard.'));
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-5 animate-slide-up">
      {/* ADR-476. Bulk first: one export covers a whole week, so this is the
          normal path and the form below is for a single correction. Putting the
          form first would make the exception look like the workflow. */}
      <ScorecardBulkImport />

      <div className="border-t border-border pt-6">
        <h3 className="text-sm font-semibold text-foreground">Enter one scorecard</h3>
        <p className="text-xs text-muted-foreground mt-0.5 mb-4">
          For a single card, or a correction to one person's week.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-accent">
          <Award className="w-4 h-4 text-primary" />
        </div>
        <h1 className="page-title">Enter Amazon Scorecard</h1>
      </div>

      {error && <ErrorBanner message={error} />}
      {saved && <div className="rounded-lg border border-emerald-300/40 bg-emerald-50 p-3 text-sm text-emerald-700">Scorecard saved.</div>}

      {/* Cross-check vs our data (ADR-204 Phase D) — surfaces contestable defects. */}
      {crossCheck && (
        <div className="card space-y-3">
          <h2 className="text-sm font-bold text-foreground">Cross-check vs our records</h2>
          <p className="text-xs text-muted-foreground">
            Week {crossCheck.week} · our data:{' '}
            {crossCheck.our_delivered != null
              ? `${crossCheck.our_delivered} delivered`
              : crossCheck.our_carried != null
                ? `${crossCheck.our_carried} carried`
                : '— no parcel count recorded'}{' '}
            · {crossCheck.our_rts} RTS · {crossCheck.our_missing} missing
          </p>
          {crossCheck.routes_unrecorded > 0 && (
            <p className="text-xs text-warning">
              {crossCheck.routes_unrecorded} route(s) this week have no Flex parcel
              count recorded, so the comparison is withheld rather than estimated.
            </p>
          )}
          {crossCheck.precision_note && (
            <p className="text-xs text-muted-foreground italic">
              {crossCheck.precision_note}
            </p>
          )}
          <div className="space-y-2">
            {crossCheck.items.map(it => (
              <div key={it.metric}
                   className={`rounded-lg border p-3 ${it.contestable ? 'border-amber-400/50 bg-amber-50' : 'border-border bg-background'}`}>
                <div className="flex items-center justify-between gap-2">
                  <label className="flex items-center gap-2 min-w-0 cursor-pointer">
                    {/* Any metric may be contested, not only the flagged ones —
                        the flag is our data's opinion, not a gate. */}
                    <input
                      type="checkbox"
                      checked={appealPick.has(it.metric)}
                      disabled={!!appealId}
                      onChange={e => setAppealPick(prev => {
                        const next = new Set(prev);
                        e.target.checked ? next.add(it.metric) : next.delete(it.metric);
                        return next;
                      })}
                      className="shrink-0"
                    />
                    <span className="text-sm font-semibold text-foreground capitalize truncate">{it.metric.replace(/_/g, ' ')}</span>
                  </label>
                  {it.contestable && <span className="text-[10px] font-bold text-amber-700 bg-amber-100 px-2 py-0.5 rounded shrink-0">CONTESTABLE</span>}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Amazon: <span className="font-medium text-foreground">{it.amazon_value ?? '—'}</span>
                  {' · '}Ours: <span className="font-medium text-foreground">{it.our_value ?? '—'}</span>
                  {it.delta != null && ` · Δ ${it.delta}`}
                </p>
                <p className="text-xs text-muted-foreground mt-1">{it.note}</p>
              </div>
            ))}
          </div>
          {crossCheck.rts_evidence.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">RTS evidence (appeal support)</p>
              <ul className="space-y-0.5">
                {crossCheck.rts_evidence.map(e => (
                  <li key={e.rts_type} className="flex justify-between text-xs">
                    <span className="text-foreground capitalize">{e.rts_type.replace(/_/g, ' ')}</span>
                    <span className="text-muted-foreground">{e.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Appeal creation — the entry point the appeals page tells users to
              start from. Without this, /scorecard-appeals had no way to create
              anything. */}
          <div className="border-t border-border pt-3">
            {appealId ? (
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <p className="text-xs text-emerald-700">
                  Draft appeal opened with {appealPick.size} metric{appealPick.size === 1 ? '' : 's'}.
                </p>
                <Link to="/scorecard-appeals" className="text-xs text-primary hover:underline">
                  Open in Appeals →
                </Link>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <p className="text-xs text-muted-foreground">
                  {appealPick.size === 0
                    ? 'Select at least one metric to contest.'
                    : `${appealPick.size} metric${appealPick.size === 1 ? '' : 's'} selected. Values and RTS evidence are copied into the draft.`}
                </p>
                <button
                  onClick={createAppeal}
                  disabled={appealBusy || appealPick.size === 0}
                  className="btn-primary text-sm disabled:opacity-40"
                >
                  {appealBusy ? 'Opening…' : 'Open draft appeal'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Upload → auto-extract (Phase C). Pre-fills the form; review before saving. */}
      <label className="card flex items-center gap-3 cursor-pointer hover:border-primary transition-colors">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-accent shrink-0">
          <Upload className="w-4 h-4 text-primary" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium text-foreground">{parsing ? 'Reading scorecard…' : 'Upload scorecard image'}</p>
          <p className="text-xs text-muted-foreground">Auto-fills the fields below. Review, then save, or fill them in manually.</p>
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
            <div className="w-56">
              <SelectMenu
                value={scope}
                options={[
                  { value: 'individual', label: 'Individual (DA)' },
                  { value: 'company',    label: 'Company (station)' },
                ]}
                placeholder="Select a scope"
                ariaLabel="Scorecard scope"
                onChange={v => { setScope(v as any); setSaved(false); }}
              />
            </div>
          </label>
          {scope === 'individual' && (
            <label className="text-sm flex flex-col gap-1 flex-1 min-w-[180px]">
              <span className="text-xs font-semibold text-muted-foreground uppercase">Employee</span>
              <div className="w-64">
                <SelectMenu
                  value={employeeId}
                  options={employees.map(e => ({ value: e.id, label: e.name }))}
                  placeholder="Select…"
                  ariaLabel="Employee"
                  onChange={setEmployeeId}
                />
              </div>
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
              <div className="col-span-4">
                <SelectMenu
                  value={m.flag ?? ''}
                  options={[
                    { value: '',            label: 'No flag' },
                    { value: 'excellent',   label: 'Excellent' },
                    { value: 'needs_focus', label: 'Needs Focus' },
                  ]}
                  placeholder="No flag"
                  ariaLabel="Metric flag"
                  onChange={v => setMetric(i, { flag: (v || null) as any })}
                />
              </div>
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
