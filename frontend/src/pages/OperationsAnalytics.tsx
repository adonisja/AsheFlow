/**
 * Company scorecard trend.
 *
 * Repointed (ADR-241 follow-up) from four algorithm-introspection panels —
 * dispatch fill rate, ban-override frequency, trainer load, confirmation times.
 * Three of those measured AsheFlow rather than the operation, and none carried a
 * baseline, so every figure was an uncomparable absolute.
 *
 * Amazon's weekly scorecard is the number the business is judged on, and it is
 * the one dataset with an inherent baseline — Amazon's own tiers and flags.
 *
 * Fill rate and confirmation timing moved to components/dispatch/
 * DispatchProcessHealth, where they inform tomorrow's run. Trainer load already
 * existed on the Management dashboard via /training/pipeline-summary.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  BarChart2, RefreshCw, TrendingUp, TrendingDown, Minus, AlertTriangle,
  Award, ArrowRight, CircleAlert,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import type { ScorecardTrendResponse, MetricTrend } from '../api/types';
import { count } from '../utils/metric';

/** Amazon's standing ladder, best first — drives colour and movement detection. */
const STANDING_RANK = ['FANTASTIC', 'GREAT', 'FAIR', 'POOR', 'AT RISK'];

function standingTone(s?: string | null): string {
  if (!s) return 'text-muted-foreground';
  const u = s.toUpperCase();
  if (u.includes('FANTASTIC') || u.includes('PLATINUM')) return 'text-success';
  if (u.includes('GREAT') || u.includes('GOLD')) return 'text-info';
  if (u.includes('FAIR') || u.includes('SILVER')) return 'text-warning';
  return 'text-danger';
}

/**
 * Direction is pre-corrected server-side for lower-is-better metrics, so "up"
 * always means IMPROVED even when the number fell. Never re-derive from delta.
 */
function Direction({ dir }: { dir?: string | null }) {
  const c = 'w-3.5 h-3.5 shrink-0';
  if (dir === 'up') return <TrendingUp className={`${c} text-success`} />;
  if (dir === 'down') return <TrendingDown className={`${c} text-danger`} />;
  if (dir === 'flat') return <Minus className={`${c} text-muted-foreground`} />;
  return <Minus className={`${c} text-muted-foreground/40`} />;
}

/** Inline sparkline. A dozen divs beats a charting dependency at this size, and
 *  missing weeks render as a gap rather than interpolating over absent data. */
function Sparkline({ trend }: { trend: MetricTrend }) {
  const vals = trend.points.map(p => p.value).filter((v): v is number => v != null);
  if (vals.length < 2) return <span className="text-xs text-subtle">not enough history</span>;

  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;

  return (
    <div className="flex items-end gap-[2px] h-8">
      {trend.points.map((p, i) => {
        if (p.value == null) {
          return (
            <div key={i} className="w-1.5 h-full bg-border/30 rounded-sm"
                 title={`${p.week}: no data`} />
          );
        }
        const h = 20 + ((p.value - min) / span) * 80;
        const flagged = p.flag === 'needs_focus';
        return (
          <div
            key={i}
            className={`w-1.5 rounded-sm ${flagged ? 'bg-danger/70' : 'bg-primary/60'}`}
            style={{ height: `${h}%` }}
            title={`${p.week}: ${p.raw}${flagged ? ' (needs focus)' : ''}`}
          />
        );
      })}
    </div>
  );
}

export default function OperationsAnalytics() {
  const [data, setData]       = useState<ScorecardTrendResponse | null>(null);
  const [weeks, setWeeks]     = useState(12);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<ScorecardTrendResponse>(
        `/scorecards/company/trend?weeks=${weeks}`,
      );
      setData(res.data);
    } catch {
      setError('Failed to load scorecard trend.');
    } finally {
      setLoading(false);
    }
  }, [weeks]);

  useEffect(() => { load(); }, [load]);

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="page-title flex items-center gap-2">
          <BarChart2 className="w-5 h-5 text-primary" /> Company Scorecard
        </h1>
        <p className="text-subtle mt-1">Amazon's weekly standing and metric trend.</p>
      </div>
      <div className="flex items-center gap-2">
        <select
          value={weeks}
          onChange={e => setWeeks(Number(e.target.value))}
          className="px-3 py-2 rounded-lg border border-border bg-accent/20 text-sm"
          aria-label="Weeks of history"
        >
          <option value={6}>6 weeks</option>
          <option value={12}>12 weeks</option>
          <option value={26}>26 weeks</option>
        </select>
        <button onClick={load} className="btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>
    </div>
  );

  if (loading && !data) {
    return (
      <div className="space-y-8 animate-slide-up">
        {header}
        <div className="space-y-3">
          {[1, 2, 3].map(i => <div key={i} className="card animate-pulse h-24" />)}
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="space-y-8">{header}<ErrorBanner message={error} /></div>;
  }

  // Nothing entered yet — say so and point at the entry page, rather than
  // rendering an empty chart frame that looks broken.
  if (!data || data.weeks.length === 0) {
    return (
      <div className="space-y-8 animate-slide-up">
        {header}
        <div className="card flex flex-col items-center justify-center py-16 gap-3 text-center">
          <BarChart2 className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No company scorecards recorded yet.</p>
          <Link to="/scorecard-entry"
                className="text-sm text-primary hover:underline flex items-center gap-1">
            Enter a scorecard <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    );
  }

  const cur = (data.current_standing ?? '').toUpperCase();
  const prev = (data.previous_standing ?? '').toUpperCase();
  const standingMoved = Boolean(cur && prev && cur !== prev);
  const standingWorse = standingMoved &&
    STANDING_RANK.indexOf(cur) > STANDING_RANK.indexOf(prev);

  return (
    <div className="space-y-8 animate-slide-up">
      {header}

      {/* Standing — the headline the business is judged on */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-4">
          <Award className={`w-10 h-10 shrink-0 ${standingTone(data.current_standing)}`} />
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">
              Current standing · {data.weeks[data.weeks.length - 1]}
            </p>
            <p className={`text-3xl font-bold ${standingTone(data.current_standing)}`}>
              {data.current_standing ?? '—'}
            </p>
            {standingMoved ? (
              <p className={`text-xs mt-0.5 ${standingWorse ? 'text-danger' : 'text-success'}`}>
                {standingWorse ? '▼' : '▲'} from {data.previous_standing}
              </p>
            ) : data.previous_standing ? (
              <p className="text-xs text-subtle mt-0.5">unchanged from prior week</p>
            ) : null}
          </div>

          {/* Standing history, oldest -> newest */}
          <div className="ml-auto flex items-end gap-1">
            {data.standings.map(s => (
              <div
                key={s.week}
                title={`${s.week}: ${s.standing ?? 'no data'}`}
                className={`w-2.5 h-8 rounded-sm ${
                  s.standing ? standingTone(s.standing).replace('text-', 'bg-') : 'bg-border/30'
                }`}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Focus list — the to-do, rather than making the reader scan every row */}
      {(data.focus_now?.length ?? 0) > 0 && (
        <div className="card border-danger/30">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-3">
            <AlertTriangle className="w-5 h-5 text-danger" />
            <h2 className="text-base font-semibold text-foreground">
              Flagged this week ({count(data.focus_now?.length)})
            </h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {data.focus_now?.map(label => (
              <span key={label}
                    className="text-sm px-2.5 py-1 rounded-full bg-danger/10 text-danger border border-danger/20">
                {label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Gaps are operationally meaningful — somebody did not enter a scorecard */}
      {(data.missing_weeks?.length ?? 0) > 0 && (
        <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg bg-warning/10 border border-warning/30 text-warning text-sm">
          <CircleAlert className="w-4 h-4 shrink-0 mt-0.5" />
          <span>No scorecard recorded for {data.missing_weeks?.join(', ')} — the trend has gaps.</span>
        </div>
      )}

      {/* Metric trend */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <BarChart2 className="w-5 h-5 text-info" />
          <h2 className="text-base font-semibold text-foreground">
            Metric Trend · {data.weeks.length} weeks
          </h2>
          <Link to="/scorecard-entry"
                className="ml-auto text-xs text-primary hover:underline flex items-center gap-1">
            Enter scorecard <ArrowRight className="w-3 h-3" />
          </Link>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <th className="pb-2 pr-4">Metric</th>
                <th className="pb-2 pr-4">Trend</th>
                <th className="pb-2 pr-4 text-right">Latest</th>
                <th className="pb-2 pr-4 text-right">Change</th>
                <th className="pb-2 text-right">Weeks flagged</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.metrics.map(m => {
                const newest = m.points[m.points.length - 1];
                return (
                  <tr key={m.key} className={newest?.flag === 'needs_focus' ? 'bg-danger/5' : ''}>
                    <td className="py-2.5 pr-4">
                      <span className="font-medium text-foreground">{m.label}</span>
                      {newest?.tier && (
                        <span className={`ml-2 text-xs ${standingTone(newest.tier)}`}>
                          {newest.tier}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4"><Sparkline trend={m} /></td>
                    <td className="py-2.5 pr-4 text-right font-semibold text-foreground tabular-nums whitespace-nowrap">
                      {newest?.raw || '—'}
                    </td>
                    <td className="py-2.5 pr-4 text-right whitespace-nowrap">
                      <span className="inline-flex items-center gap-1 justify-end tabular-nums">
                        <Direction dir={m.direction} />
                        {m.delta != null
                          ? `${m.delta > 0 ? '+' : ''}${m.delta}`
                          : <span className="text-subtle">—</span>}
                      </span>
                    </td>
                    <td className="py-2.5 text-right tabular-nums">
                      {(m.weeks_flagged ?? 0) > 0
                        ? <span className="text-danger font-semibold">{m.weeks_flagged}</span>
                        : <span className="text-subtle">0</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-xs text-subtle">
          Arrows show whether the metric improved, already accounting for metrics
          where a lower number is better (DPMO, driver behaviour).
        </p>
      </div>
    </div>
  );
}
