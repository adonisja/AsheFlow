/**
 * Dispatch process-health panels.
 *
 * Moved off the Analytics page (ADR-241 follow-up), which was repointed at the
 * Amazon company scorecard. These two measure DISPATCH's own process, so they
 * belong where dispatch works:
 *
 *   Fill rate            how much of the roster the algorithm placed without
 *                        manual override. A rising manual share means the
 *                        algorithm is fighting the operator.
 *   Confirmation timing  how fast crew answer the dispatch DM. Slow responders
 *                        delay the whole run, so this informs tomorrow's
 *                        send time and follow-up order.
 *
 * The other two former panels were dropped rather than moved: ban-override
 * frequency counted a system event with no outcome attached, and trainer load
 * duplicated /training/pipeline-summary on the Management dashboard.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { BarChart2, Clock, TrendingUp, type LucideIcon } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import { today, nWeeksAgo } from '../../utils/date';


// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({ label, value, sub, color = 'text-foreground' }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="card-elevated">
      <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
      {sub && <p className="text-xs text-subtle mt-0.5">{sub}</p>}
    </div>
  );
}

function SectionHeader({ icon: Icon, title, subtitle, iconColor }: { icon: LucideIcon; title: string; subtitle?: string; iconColor: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
      <Icon className={`w-5 h-5 ${iconColor}`} />
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {subtitle && <span className="ml-auto text-xs text-subtle">{subtitle}</span>}
    </div>
  );
}

// Inline bar — value/max ratio maps to width
function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="flex-1 h-2 rounded-full bg-accent overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-bold text-foreground w-6 text-right">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel 1 — Dispatch Fill Rate
// ---------------------------------------------------------------------------

function Spinner() {
  return (
    <div className="flex h-32 items-center justify-center">
      <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return <p className="text-sm text-subtle text-center py-8">{text}</p>;
}

function FillRatePanel() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [weeks, setWeeks]     = useState(8);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const start = nWeeksAgo(weeks);
      const end   = today();
      const res   = await axiosClient.get('/analytics/dispatch-fill-rate', { params: { start_date: start, end_date: end } });
      setData(res.data);
    } catch { setError('Failed to load dispatch fill rate data.'); } finally { setLoading(false); }
  }, [weeks]);

  useEffect(() => { load(); }, [load]);

  const maxTotal = data ? Math.max(...data.by_date.map((d: any) => d.total), 1) : 1;

  return (
    <div className="card">
      <SectionHeader icon={TrendingUp} title="Dispatch Fill Rate" subtitle="algo vs manual placements" iconColor="text-primary" />
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-subtle">Last</span>
        {[4, 8, 12].map(w => (
          <button key={w} onClick={() => setWeeks(w)}
            className={`text-xs px-2 py-1 rounded-lg border transition-colors ${weeks === w ? 'bg-primary text-white border-primary' : 'border-border text-muted-foreground hover:border-primary'}`}>
            {w}w
          </button>
        ))}
      </div>
      {error ? <Empty text={error} /> : loading ? <Spinner /> : !data || data.by_date.length === 0 ? <Empty text="No dispatch data in range." /> : (
        <>
          <div className="grid grid-cols-3 gap-3 mb-6">
            <StatCard label="Total Slots" value={data.summary.total_slots} />
            <StatCard label="Algorithm" value={data.summary.algo_slots} color="text-success"
              sub={`${data.summary.algo_pct}%`} />
            <StatCard label="Manual" value={data.summary.manual_slots} color="text-warning" />
          </div>
          <div className="space-y-2">
            {data.by_date.slice(-14).map((row: any) => (
              <div key={row.date} className="flex items-center gap-3">
                <span className="text-xs text-subtle w-20 shrink-0">{row.date.slice(5)}</span>
                <div className="flex-1 flex flex-col gap-0.5">
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-success w-12">algo</span>
                    <Bar value={row.algo}   max={maxTotal} color="bg-success" />
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-warning w-12">manual</span>
                    <Bar value={row.manual} max={maxTotal} color="bg-warning" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel 2 — Trainer Load
// ---------------------------------------------------------------------------

function ConfirmationTimesPanel() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [weeks, setWeeks]     = useState(4);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const start = nWeeksAgo(weeks);
      const end   = today();
      const res   = await axiosClient.get('/analytics/confirmation-times', { params: { start_date: start, end_date: end } });
      setData(res.data);
    } catch { setError('Failed to load confirmation time data.'); } finally { setLoading(false); }
  }, [weeks]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="card">
      <SectionHeader icon={Clock} title="Confirmation Response Time" subtitle="median / p90 in minutes" iconColor="text-success" />
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-subtle">Last</span>
        {[2, 4, 8].map(w => (
          <button key={w} onClick={() => setWeeks(w)}
            className={`text-xs px-2 py-1 rounded-lg border transition-colors ${weeks === w ? 'bg-primary text-white border-primary' : 'border-border text-muted-foreground hover:border-primary'}`}>
            {w}w
          </button>
        ))}
      </div>
      {error ? <Empty text={error} /> : loading ? <Spinner /> : !data || data.overall.total_responses === 0 ? <Empty text="No confirmed responses in range." /> : (
        <>
          <div className="grid grid-cols-3 gap-3 mb-5">
            <StatCard label="Responses" value={data.overall.total_responses} />
            <StatCard label="Median" value={`${data.overall.median_minutes}m`}
              color={data.overall.median_minutes > 60 ? 'text-danger' : data.overall.median_minutes > 20 ? 'text-warning' : 'text-success'} />
            <StatCard label="P90" value={`${data.overall.p90_minutes}m`}
              color={data.overall.p90_minutes > 120 ? 'text-danger' : 'text-foreground'} />
          </div>
          <p className="text-xs text-subtle uppercase tracking-wider mb-3">By Role</p>
          <div className="space-y-2">
            {data.by_role.map((row: any) => (
              <div key={row.role} className="flex items-center gap-3 py-2 border-b border-border last:border-0">
                <span className="text-sm font-medium capitalize text-foreground w-20 shrink-0">{row.role}</span>
                <div className="flex-1 flex gap-4 text-xs">
                  <span className="text-subtle">med <span className="font-bold text-foreground">{row.median_minutes}m</span></span>
                  <span className="text-subtle">p90 <span className="font-bold text-foreground">{row.p90_minutes}m</span></span>
                  <span className="text-subtle">{row.count} resp.</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared micro-components
// ---------------------------------------------------------------------------

export default function DispatchProcessHealth() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <FillRatePanel />
      <ConfirmationTimesPanel />
    </div>
  );
}
