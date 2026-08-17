import React, { useState, useEffect, useCallback } from 'react';
import { Route as RouteIcon, RefreshCw, AlertTriangle, Info } from 'lucide-react';
import axiosClient from '../api/axiosClient';

/**
 * Sort Metrics (ADR-273) — the raw telemetry series.
 *
 * DELIBERATELY A TABLE, NOT CHARTS.
 * Sorts run roughly every other day across 6 trucks, so a month is ~120
 * truck-days. Trend lines and "vs last week" deltas drawn over that little data
 * imply a confidence the sample does not support — the exact mistake ADR-272
 * documents twice, where a single day pointed opposite to ten simulated ones.
 * Charts come once the series is long enough to carry them.
 *
 * Every number is shown next to its sample size for the same reason. A sample
 * count that is always visible beats a rule someone has to remember.
 */

interface SortDaily {
  route_date: string;
  truck_id: string | null;
  truck_name: string | null;
  algorithm_version: string | null;
  sort_runs: number;
  routes: number;
  blocks_split: number;
  orphan_blocks: number;
  runt_routes: number;
  blocks_per_route_avg: number | null;
  blocks_per_route_hist: Record<string, number> | null;
  capacity_util_pct: number | null;
  packages: number;
  stops: number;
  route_minutes_avg: number | null;
  route_minutes_p90: number | null;
  routes_timed: number;
  by_effort_class: Record<string, EffortClassSlot> | null;
  rts_total: number;
  missing_total: number;
  help_requests: number;
}

interface EffortClassSlot {
  routes: number;
  packages: number;
  minutes_avg: number | null;
  routes_timed: number;
  rts: number;
  missing: number;
}

interface SortMetricsSummary {
  days: number;
  trucks: number;
  routes: number;
  packages: number;
  blocks_split: number;
  orphan_blocks: number;
  runt_routes: number;
  help_requests: number;
  blocks_per_route_avg: number | null;
  capacity_util_pct: number | null;
  route_minutes_avg: number | null;
  truck_days_by_version: Record<string, number>;
  blocks_per_route_hist: Record<string, number>;
}

interface SortMetricsResponse {
  start: string;
  end: string;
  summary: SortMetricsSummary;
  series: SortDaily[];
}

const WINDOWS = [
  { days: 28,  label: '4 weeks' },
  { days: 91,  label: '3 months' },
  { days: 365, label: '1 year' },
];

/** Below this, a summary is an anecdote. Drives the thin-data warning. */
const THIN_SAMPLE_TRUCK_DAYS = 30;

function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return '—';
  return v.toFixed(digits);
}

function fmtDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function SortMetrics() {
  const [windowDays, setWindowDays] = useState(28);
  const [data, setData] = useState<SortMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const end = new Date();
      end.setDate(end.getDate() - 1);            // series ends yesterday
      const start = new Date(end);
      start.setDate(start.getDate() - (windowDays - 1));
      const iso = (d: Date) => d.toISOString().slice(0, 10);
      const res = await axiosClient.get<SortMetricsResponse>('/sort-metrics', {
        params: { start: iso(start), end: iso(end) },
      });
      setData(res.data);
    } catch {
      setError('Could not load sort metrics.');
    } finally {
      setLoading(false);
    }
  }, [windowDays]);

  useEffect(() => { load(); }, [load]);

  const truckDays = data?.series.length ?? 0;
  const thin = truckDays > 0 && truckDays < THIN_SAMPLE_TRUCK_DAYS;
  const versions = Object.entries(data?.summary.truck_days_by_version ?? {});
  const mixedVersions = versions.length > 1;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <RouteIcon className="w-5 h-5 text-violet-500" />
          <h1 className="text-lg font-semibold text-foreground">Sort Metrics</h1>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-border overflow-hidden">
            {WINDOWS.map(w => (
              <button
                key={w.days}
                onClick={() => setWindowDays(w.days)}
                className={`px-3 py-1.5 text-sm transition-colors ${
                  windowDays === w.days
                    ? 'bg-violet-500 text-white'
                    : 'bg-background text-muted-foreground hover:text-foreground'
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
          <button onClick={load} className="btn-ghost flex items-center gap-1.5 text-sm" disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      {!loading && truckDays === 0 && !error && (
        <div className="rounded-xl border border-border bg-accent/30 px-4 py-6 text-center">
          <p className="text-sm text-foreground font-medium">No sort telemetry yet.</p>
          <p className="text-xs text-muted-foreground mt-1 max-w-lg mx-auto">
            A row appears the morning after each committed sort — the rollup only writes
            completed days, so today never appears here.
          </p>
        </div>
      )}

      {thin && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 flex gap-2.5">
          <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <div className="text-xs text-foreground/90 leading-relaxed">
            <span className="font-semibold">Small sample — {truckDays} truck-days.</span>{' '}
            Read these as individual days, not as a trend. Sorts run every other day or so
            across the fleet, so a month is roughly {THIN_SAMPLE_TRUCK_DAYS * 4} truck-days.
          </div>
        </div>
      )}

      {mixedVersions && (
        <div className="rounded-xl border border-border bg-accent/30 px-4 py-3 flex gap-2.5">
          <Info className="w-4 h-4 text-violet-400 shrink-0 mt-0.5" />
          <div className="text-xs text-foreground/90 leading-relaxed">
            <span className="font-semibold">This window spans more than one algorithm.</span>{' '}
            {versions.map(([v, n]) => `${v} (${n} truck-days)`).join(', ')}. Compare within a
            version, not across the boundary — the totals below pool them.
          </div>
        </div>
      )}

      {data && truckDays > 0 && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <Stat label="Truck-days" value={String(truckDays)} sub={`${data.summary.days} dates · ${data.summary.trucks} trucks`} />
            <Stat label="Routes" value={String(data.summary.routes)} sub={`${data.summary.packages.toLocaleString()} packages`} />
            <Stat label="Blocks / route" value={num(data.summary.blocks_per_route_avg, 2)} sub="lower is tighter" />
            <Stat label="Split blocks" value={String(data.summary.blocks_split)} tone={data.summary.blocks_split > 0 ? 'warn' : 'good'} sub="on >1 route" />
            <Stat label="Orphan blocks" value={String(data.summary.orphan_blocks)} tone={data.summary.orphan_blocks > 0 ? 'warn' : 'good'} sub="no adjacent sibling" />
            <Stat label="Route minutes" value={num(data.summary.route_minutes_avg, 0)} sub="avg, timed routes only" />
          </div>

          <BlocksPerRouteBar hist={data.summary.blocks_per_route_hist} />

          <div className="rounded-xl border border-border overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[900px]">
                <thead className="bg-accent/50">
                  <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <Th>Date</Th><Th>Truck</Th><Th>Algorithm</Th>
                    <Th right>Routes</Th><Th right>Blk/rt</Th>
                    <Th right>Split</Th><Th right>Orphan</Th><Th right>Runts</Th>
                    <Th right>Util %</Th><Th right>Min avg</Th>
                    <Th right>RTS</Th><Th right>Help</Th><Th right>Re-sorts</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.series.map((r, i) => (
                    <tr key={`${r.route_date}-${r.truck_id ?? i}`} className="border-t border-border/50 hover:bg-accent/20">
                      <Td>{fmtDate(r.route_date)}</Td>
                      <Td>{r.truck_name ?? '—'}</Td>
                      <Td><span className="font-mono text-xs text-muted-foreground">{r.algorithm_version ?? '—'}</span></Td>
                      <Td right>{r.routes}</Td>
                      <Td right>{num(r.blocks_per_route_avg, 2)}</Td>
                      <Td right tone={r.blocks_split > 0 ? 'warn' : undefined}>{r.blocks_split}</Td>
                      <Td right tone={r.orphan_blocks > 0 ? 'warn' : undefined}>{r.orphan_blocks}</Td>
                      <Td right tone={r.runt_routes > 0 ? 'warn' : undefined}>{r.runt_routes}</Td>
                      <Td right>{num(r.capacity_util_pct, 1)}</Td>
                      <Td right>{r.routes_timed > 0 ? num(r.route_minutes_avg, 0) : '—'}</Td>
                      <Td right>{r.rts_total}</Td>
                      <Td right>{r.help_requests}</Td>
                      <Td right tone={r.sort_runs > 1 ? 'warn' : undefined}>{r.sort_runs}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <p className="text-[11px] text-muted-foreground leading-relaxed max-w-3xl">
            <span className="font-semibold">Split</span> counts a block listed on more than one
            route — how many walkers show up on it.{' '}
            <span className="font-semibold">Orphan</span> counts a block on a route with no
            adjacent sibling block; it omits cross-street links, so it can over-report but never
            under-report. <span className="font-semibold">Min avg</span> covers only routes that
            recorded both departure and return.
          </p>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'good' | 'warn';
}) {
  const color = tone === 'warn' ? 'text-amber-500' : tone === 'good' ? 'text-emerald-500' : 'text-foreground';
  return (
    <div className="bg-accent/40 rounded-xl p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-xl font-semibold font-mono ${color}`}>{value}</p>
      {sub && <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

/** The ADR-272 acceptance criterion: how many blocks a walker gets per trip. */
function BlocksPerRouteBar({ hist }: { hist: Record<string, number> }) {
  const entries = Object.entries(hist).sort((a, b) => Number(a[0]) - Number(b[0]));
  const total = entries.reduce((s, [, n]) => s + n, 0);
  if (!total) return null;
  const tight = entries.filter(([k]) => Number(k) <= 2).reduce((s, [, n]) => s + n, 0);

  return (
    <div className="rounded-xl border border-border p-4">
      <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <p className="text-sm font-semibold text-foreground">Blocks per route</p>
        <p className="text-xs text-muted-foreground">
          <span className="font-mono font-semibold text-foreground">
            {((100 * tight) / total).toFixed(1)}%
          </span>{' '}
          of {total} routes carry 1–2 blocks
        </p>
      </div>
      <div className="space-y-1.5">
        {entries.map(([blocks, n]) => (
          <div key={blocks} className="flex items-center gap-2">
            <span className="w-6 text-xs text-muted-foreground font-mono text-right">{blocks}</span>
            <div className="flex-1 bg-accent/40 rounded h-4 overflow-hidden">
              <div
                className={`h-full ${Number(blocks) <= 2 ? 'bg-emerald-500/70' : 'bg-amber-500/70'}`}
                style={{ width: `${(100 * n) / total}%` }}
              />
            </div>
            <span className="w-12 text-xs text-muted-foreground font-mono text-right">{n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-3 py-2 font-medium ${right ? 'text-right' : ''}`}>{children}</th>;
}

function Td({ children, right, tone }: {
  children: React.ReactNode; right?: boolean; tone?: 'warn';
}) {
  return (
    <td className={`px-3 py-2 ${right ? 'text-right font-mono' : ''} ${tone === 'warn' ? 'text-amber-500 font-semibold' : 'text-foreground'}`}>
      {children}
    </td>
  );
}
