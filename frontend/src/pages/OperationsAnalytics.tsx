import React, { useState, useEffect, useCallback } from 'react';
import { BarChart2, Users, AlertTriangle, Clock, TrendingUp, RefreshCw } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import { today, nWeeksAgo } from '../utils/date';

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

function SectionHeader({ icon: Icon, title, subtitle, iconColor }: { icon: any; title: string; subtitle?: string; iconColor: string }) {
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
function TrainerLoadPanel() {
  const [data, setData]       = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get('/analytics/trainer-load')
      .then(r => setData(r.data))
      .catch(() => setError('Failed to load trainer load data.'))
      .finally(() => setLoading(false));
  }, []);

  const maxLoad = Math.max(...data.map(d => d.active_trainees), 1);

  return (
    <div className="card">
      <SectionHeader icon={Users} title="Trainer Load" subtitle="active trainees per trainer" iconColor="text-info" />
      {error ? <Empty text={error} /> : loading ? <Spinner /> : data.length === 0 ? <Empty text="No active training records." /> : (
        <div className="space-y-3">
          {data.map((t: any) => (
            <div key={t.trainer_id} className="p-3 rounded-xl border border-border">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-foreground">{t.trainer_name}</span>
                <span className={`text-sm font-bold ${t.active_trainees >= 3 ? 'text-danger' : t.active_trainees === 2 ? 'text-warning' : 'text-success'}`}>
                  {t.active_trainees} trainee{t.active_trainees !== 1 ? 's' : ''}
                </span>
              </div>
              <Bar value={t.active_trainees} max={maxLoad} color={t.active_trainees >= 3 ? 'bg-danger' : t.active_trainees === 2 ? 'bg-warning' : 'bg-success'} />
              <div className="flex gap-2 mt-2">
                {Object.entries(t.phases as Record<string, number>).map(([phase, count]) => count > 0 ? (
                  <span key={phase} className="text-xs text-subtle bg-accent px-2 py-0.5 rounded-full">
                    P{phase}: {count}
                  </span>
                ) : null)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel 3 — Ban Override Frequency
// ---------------------------------------------------------------------------
function BanOverridePanel() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [weeks, setWeeks]     = useState(8);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get('/analytics/ban-override-freq', { params: { weeks } });
      setData(res.data);
    } catch { setError('Failed to load ban override data.'); } finally { setLoading(false); }
  }, [weeks]);

  useEffect(() => { load(); }, [load]);

  const maxCount = data ? Math.max(...data.by_week.map((w: any) => w.count), 1) : 1;

  return (
    <div className="card">
      <SectionHeader icon={AlertTriangle} title="Ban Override Frequency" subtitle="algorithm fighting preferences?" iconColor="text-warning" />
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-subtle">Last</span>
        {[4, 8, 12].map(w => (
          <button key={w} onClick={() => setWeeks(w)}
            className={`text-xs px-2 py-1 rounded-lg border transition-colors ${weeks === w ? 'bg-primary text-white border-primary' : 'border-border text-muted-foreground hover:border-primary'}`}>
            {w}w
          </button>
        ))}
      </div>
      {error ? <Empty text={error} /> : loading ? <Spinner /> : !data ? <Empty text="No override data." /> : (
        <>
          <div className="grid grid-cols-2 gap-3 mb-5">
            <StatCard label="Total Overrides" value={data.total_overrides}
              color={data.total_overrides > 10 ? 'text-danger' : data.total_overrides > 4 ? 'text-warning' : 'text-success'} />
            <StatCard label="Period" value={`${data.weeks}w`} />
          </div>
          <div className="space-y-2">
            {data.by_week.map((row: any) => (
              <div key={row.week_start} className="flex items-center gap-3">
                <span className="text-xs text-subtle w-20 shrink-0">{row.week_start.slice(5)}</span>
                <Bar value={row.count} max={maxCount} color={row.count >= 3 ? 'bg-danger' : row.count > 0 ? 'bg-warning' : 'bg-accent'} />
              </div>
            ))}
          </div>
          {data.total_overrides === 0 && (
            <p className="text-xs text-success text-center mt-3">No overrides — algorithm and preferences are aligned.</p>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel 4 — Confirmation Response Time
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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function OperationsAnalytics() {
  const { groups } = useAuth();
  const canSeeTrainerLoad = groups.includes('management') || groups.includes('admin');

  return (
    <div className="space-y-8 animate-slide-up">
      <div>
        <h1 className="page-title flex items-center gap-2">
          <BarChart2 className="w-5 h-5 text-primary" /> Operations Analytics
        </h1>
        <p className="text-subtle mt-1">Dispatch health, crew dynamics, and response patterns.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <FillRatePanel />
        {canSeeTrainerLoad && <TrainerLoadPanel />}
        <BanOverridePanel />
        <ConfirmationTimesPanel />
      </div>
    </div>
  );
}
