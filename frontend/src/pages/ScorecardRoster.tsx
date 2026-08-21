/**
 * Individual scorecard roster — Tier 3, management and admin only.
 *
 * Named deliberately, matching /field-ops/walker-leaderboard which already shows
 * named performance to this same audience. Anonymising it would make it
 * unactionable for the only people authorised to act on it.
 *
 * Sorted worst-first (flagged metric count, then declining standing): the point
 * of a roster is finding who needs attention, not alphabetical browsing.
 *
 * See docs/SCORECARD_ACCESS_MODEL.md — dispatch is excluded from this tier.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Users, RefreshCw, AlertTriangle, TrendingUp, TrendingDown, Minus, X,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import type {
  IndividualRosterResponse, IndividualRosterRow, IndividualTrendResponse,
} from '../api/types';
import { count, pct } from '../utils/metric';

function standingTone(s?: string | null): string {
  if (!s) return 'text-muted-foreground';
  const u = s.toUpperCase();
  if (u.includes('FANTASTIC') || u.includes('PLATINUM')) return 'text-success';
  if (u.includes('GREAT') || u.includes('GOLD')) return 'text-info';
  if (u.includes('FAIR') || u.includes('SILVER')) return 'text-warning';
  return 'text-danger';
}

/** Standing movement. Not metric direction — this is ladder position, where
 *  "improved" means a better tier, so it needs its own renderer. */
function Movement({ dir }: { dir?: string | null }) {
  const c = 'w-3.5 h-3.5 shrink-0';
  if (dir === 'improved') return <TrendingUp className={`${c} text-success`} />;
  if (dir === 'declined') return <TrendingDown className={`${c} text-danger`} />;
  if (dir === 'unchanged') return <Minus className={`${c} text-muted-foreground`} />;
  return <Minus className={`${c} text-muted-foreground/40`} />;
}

export default function ScorecardRoster() {
  const [data, setData] = useState<IndividualRosterResponse | null>(null);
  const [weeks, setWeeks] = useState(4);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<IndividualTrendResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<IndividualRosterResponse>(
        `/scorecards/individual/roster?weeks=${weeks}`,
      );
      setData(res.data);
    } catch {
      setError('Failed to load the scorecard roster.');
    } finally {
      setLoading(false);
    }
  }, [weeks]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (row: IndividualRosterRow) => {
    try {
      const res = await axiosClient.get<IndividualTrendResponse>(
        `/scorecards/individual/${row.employee_id}/trend?weeks=12`,
      );
      setDetail(res.data);
    } catch {
      setError(`Could not load ${row.employee_name}'s trend.`);
    }
  };

  return (
    <div className="space-y-8 animate-slide-up">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Users className="w-5 h-5 text-primary" /> Scorecard Roster
          </h1>
          <p className="text-subtle mt-1">
            Individual Amazon standings, worst first.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={weeks}
            onChange={e => setWeeks(Number(e.target.value))}
            className="px-3 py-2 rounded-lg border border-border bg-accent/20 text-sm"
            aria-label="Weeks considered"
          >
            <option value={2}>2 weeks</option>
            <option value={4}>4 weeks</option>
            <option value={12}>12 weeks</option>
          </select>
          <button onClick={load} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
      </div>

      <ErrorBanner message={error} />

      {/* Coverage. A thin roster should read as missing data, not a small team —
          without this the page silently understates the crew. */}
      {data && (data.employees_without_scorecards ?? 0) > 0 && (
        <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg bg-warning/10 border border-warning/30 text-warning text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {count(data.employees_without_scorecards)} active field staff have no
            scorecard in this window — they are absent from the list below, not
            performing well.
          </span>
        </div>
      )}

      {loading ? (
        <div className="space-y-3">{[1, 2, 3].map(i => <div key={i} className="card animate-pulse h-16" />)}</div>
      ) : !data || data.rows.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-14 gap-3 text-center">
          <Users className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No individual scorecards recorded in the last {weeks} weeks.
          </p>
        </div>
      ) : (
        <div className="card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-4">Employee</th>
                  <th className="pb-2 pr-4">Standing</th>
                  <th className="pb-2 pr-4 text-right">Flagged</th>
                  <th className="pb-2 pr-4 text-right">Weeks</th>
                  <th className="pb-2">Latest</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.rows.map(r => (
                  <tr
                    key={r.employee_id}
                    onClick={() => openDetail(r)}
                    className={`cursor-pointer hover:bg-accent/20 transition-colors ${
                      (r.flagged_metric_count ?? 0) > 0 ? 'bg-danger/5' : ''
                    }`}
                  >
                    <td className="py-2.5 pr-4">
                      <span className="font-medium text-foreground">{r.employee_name}</span>
                      {r.employee_role && (
                        <span className="text-xs text-subtle ml-2 capitalize">{r.employee_role}</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className="inline-flex items-center gap-1.5">
                        <Movement dir={r.trend_direction} />
                        <span className={`font-semibold ${standingTone(r.standing)}`}>
                          {r.standing ?? '—'}
                        </span>
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 text-right tabular-nums">
                      {(r.flagged_metric_count ?? 0) > 0
                        ? <span className="text-danger font-semibold">{count(r.flagged_metric_count)}</span>
                        : <span className="text-subtle">0</span>}
                    </td>
                    <td className="py-2.5 pr-4 text-right tabular-nums text-muted-foreground">
                      {count(r.weeks_recorded)}
                    </td>
                    <td className="py-2.5 text-muted-foreground tabular-nums">{r.latest_week ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-subtle">
            Sorted worst first — most flagged metrics, then declining standings.
          </p>
        </div>
      )}

      {detail && <TrendDrawer trend={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function TrendDrawer({
  trend, onClose,
}: {
  trend: IndividualTrendResponse;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-6">
      <div className="bg-background border border-border rounded-t-2xl sm:rounded-2xl w-full sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-background border-b border-border px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-foreground">{trend.employee_name ?? 'Employee'}</h2>
            <p className="text-xs text-subtle mt-0.5">
              {trend.weeks.length} week{trend.weeks.length === 1 ? '' : 's'} ·
              current standing{' '}
              <span className={standingTone(trend.current_standing)}>
                {trend.current_standing ?? '—'}
              </span>
            </p>
          </div>
          <button onClick={onClose} className="btn-ghost p-1 shrink-0" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {(trend.focus_now?.length ?? 0) > 0 && (
            <div className="p-3 rounded-lg bg-danger/10 border border-danger/20">
              <p className="text-xs font-semibold text-danger uppercase tracking-wider mb-1">
                Flagged this week
              </p>
              <p className="text-sm text-foreground">{trend.focus_now!.join(', ')}</p>
            </div>
          )}

          {trend.metrics.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No metrics recorded.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                    <th className="pb-2 pr-4">Metric</th>
                    <th className="pb-2 pr-4 text-right">Latest</th>
                    <th className="pb-2 text-right">Change</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {trend.metrics.map(m => {
                    const newest = m.points[m.points.length - 1];
                    return (
                      <tr key={m.key} className={newest?.flag === 'needs_focus' ? 'bg-danger/5' : ''}>
                        <td className="py-2 pr-4 text-foreground">{m.label}</td>
                        <td className="py-2 pr-4 text-right font-semibold text-foreground tabular-nums">
                          {newest?.raw || '—'}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {/* Direction is corrected server-side for
                              lower-is-better metrics, so "up" always means
                              improved. Never re-derive it from delta. */}
                          <span className={
                            m.direction === 'up' ? 'text-success'
                            : m.direction === 'down' ? 'text-danger'
                            : 'text-subtle'
                          }>
                            {m.direction === 'up' ? '↑ ' : m.direction === 'down' ? '↓ ' : ''}
                            {m.delta != null ? `${m.delta > 0 ? '+' : ''}${m.delta}` : '—'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="sticky bottom-0 bg-background border-t border-border px-5 py-3 flex justify-end">
          <button onClick={onClose} className="btn-ghost text-sm">Close</button>
        </div>
      </div>
    </div>
  );
}
