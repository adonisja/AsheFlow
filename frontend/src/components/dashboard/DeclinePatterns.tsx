/**
 * Where the operation loses capacity to declines (ADR-268).
 *
 * WHY IT LIVES ON THE MANAGEMENT DASHBOARD AND NOT ON SCORECARDS
 * Scorecards is one subject end to end — Amazon's weekly scorecard, its crew
 * breakdown, entry, and appeals. Declines are an internal rota signal with no
 * Amazon relationship, so a fifth sub-tab there would break the page's stated
 * single subject. This dashboard already carries crew reliability (no-shows,
 * roll-call, coverage depth), which is the same question one step earlier.
 *
 * THE ONE RULE THIS COMPONENT MUST NOT BREAK
 * A slice with `gated: true` has no trustworthy rate. Render the COUNT for
 * those, never a percentage — the backend returns `rate: null` precisely so
 * this cannot happen by accident, and `pct(null)` renders "—" rather than
 * "0%". A gated slice showing "100% declines" off three Fridays is the exact
 * finding that gets screenshotted into a meeting without its caveat.
 *
 * Weekday is shown first because it is the actionable slice: a weekday cluster
 * is a rota fix. Truck and person are collapsed behind a toggle — per-person
 * decline counts are a conversation starter, not a leaderboard, and putting
 * them on screen by default invites reading them as one.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { CalendarX2, ChevronDown, RefreshCw, Truck, User } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import type { DeclineAnalysis, DeclineSlice } from '../../api/types';
import { pct } from '../../utils/metric';

/** Ordered Mon–Sun so the row reads as a week, not as a ranking. The API sorts
 *  worst-first, which is right for truck/person but wrong for a calendar. */
const WEEK_ORDER = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
];

function GateNote({ slice }: { slice: DeclineSlice }) {
  if (!slice.gated) return null;
  return (
    <span
      className="text-xs text-subtle"
      title={`Seen ${slice.occurrences} time${slice.occurrences === 1 ? '' : 's'} — not enough history for a rate yet`}
    >
      {slice.occurrences}× seen
    </span>
  );
}

/** A gated slice gets its count and no colour: it is information, not a verdict. */
function rateTone(slice: DeclineSlice): string {
  if (slice.gated || slice.rate == null) return 'text-muted-foreground';
  if (slice.rate >= 0.2) return 'text-danger';
  if (slice.rate >= 0.1) return 'text-warning';
  return 'text-foreground';
}

function SliceRow({ slice, icon: Icon }: { slice: DeclineSlice; icon: typeof Truck }) {
  return (
    <div className="flex items-center gap-2 p-2 rounded-lg bg-accent/10">
      <Icon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
      <span className="text-sm text-foreground truncate flex-1">{slice.key}</span>
      <GateNote slice={slice} />
      <span className={`text-sm font-semibold tabular-nums ${rateTone(slice)}`}>
        {/* The gate, enforced at the point of render. */}
        {slice.gated ? `${slice.declines} declined` : pct(slice.rate! * 100)}
      </span>
    </div>
  );
}

export default function DeclinePatterns() {
  const [data, setData]       = useState<DeclineAnalysis | null>(null);
  const [days, setDays]       = useState(90);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed]   = useState(false);
  const [showDetail, setShowDetail] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const res = await axiosClient.get<DeclineAnalysis>(
        `/dashboards/management/declines?days=${days}`,
      );
      setData(res.data);
    } catch {
      setFailed(true);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  // Nothing to show is not an error state and must not render as one: a company
  // with no declines in the window is a GOOD outcome, not a broken panel.
  const nothingRecorded = data != null && data.total_confirmations === 0;

  const weekday = (data?.by_weekday ?? [])
    .slice()
    .sort((a, b) => WEEK_ORDER.indexOf(a.key) - WEEK_ORDER.indexOf(b.key));

  return (
    <div className="card">
      <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
        <CalendarX2 className="w-5 h-5 text-warning" />
        <h2 className="text-base font-semibold text-foreground">Decline Patterns</h2>
        <select
          value={days}
          onChange={e => setDays(Number(e.target.value))}
          className="ml-auto px-2 py-1 rounded-lg border border-border bg-accent/20 text-xs"
          aria-label="Lookback window"
        >
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
          <option value={180}>180 days</option>
        </select>
        <button
          onClick={load}
          disabled={loading}
          className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {failed ? (
        <p className="text-sm text-subtle">Could not load decline patterns.</p>
      ) : nothingRecorded ? (
        <p className="text-sm text-subtle">
          No dispatch confirmations recorded in this window.
        </p>
      ) : data ? (
        <>
          <p className="text-sm text-subtle mb-3">
            <span className="font-semibold text-foreground tabular-nums">
              {data.total_declines}
            </span>{' '}
            declines across{' '}
            <span className="tabular-nums">{data.total_confirmations}</span>{' '}
            confirmations. A weekday cluster is a rota fix, not a people problem.
          </p>

          <div className="space-y-1.5">
            {weekday.map(s => (
              <SliceRow key={s.key} slice={s} icon={CalendarX2} />
            ))}
          </div>

          {/* Per-truck and per-person sit behind a toggle. Both are only
              interpretable ALONGSIDE the weekday view above, so they should not
              be the first thing read. */}
          <button
            onClick={() => setShowDetail(v => !v)}
            className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground
                       hover:text-foreground transition-colors"
          >
            <ChevronDown
              className={`w-3.5 h-3.5 transition-transform ${showDetail ? 'rotate-180' : ''}`}
            />
            {showDetail ? 'Hide' : 'Show'} by truck and person
          </button>

          {showDetail && (
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
                  By truck
                </p>
                <div className="space-y-1.5">
                  {data.by_truck.length === 0 ? (
                    <p className="text-xs text-subtle">No truck-linked declines.</p>
                  ) : data.by_truck.slice(0, 6).map(s => (
                    <SliceRow key={s.key} slice={s} icon={Truck} />
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
                  By person
                </p>
                <div className="space-y-1.5">
                  {data.by_person.length === 0 ? (
                    <p className="text-xs text-subtle">No declines recorded.</p>
                  ) : data.by_person.slice(0, 6).map(s => (
                    <SliceRow key={s.key} slice={s} icon={User} />
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-subtle">Loading…</p>
      )}
    </div>
  );
}