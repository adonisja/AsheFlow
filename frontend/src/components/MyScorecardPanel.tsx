/**
 * My Amazon scorecard — latest standing plus 12-week metric trend (ADR-270).
 *
 * Ported from mobile's MyScorecardScreen so the two surfaces show the same
 * thing. Web previously had only `ScorecardCard` (a `/scorecards/me` summary),
 * which is the latest row without the trend — so a web user could see their
 * current standing but not whether it was improving.
 *
 * This is AMAZON'S assessment, not AsheFlow's. The distinction is stated on
 * screen: My Stats is computed from our own DeliveryStop/RTS/rating records,
 * these figures come from Amazon's weekly scorecard. They are independent and
 * can legitimately disagree — that disagreement is what appeals exist to
 * contest, so presenting either as "the" number would be wrong.
 *
 * Self-scoped: /scorecards/me/trend filters on employee_id == caller.id and
 * carries no role gate. A driver sees their own row and nobody else's.
 */
import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { ScorecardTrendResponse, MetricTrend } from '../api/types';
import { Award, TrendingDown, TrendingUp, Minus } from 'lucide-react';

const DASH = '—';

/** Amazon's ladder, best first. */
function standingTone(s?: string | null): string {
  if (!s) return 'text-muted-foreground';
  const u = s.toUpperCase();
  if (u.includes('FANTASTIC') || u.includes('PLATINUM')) return 'text-success';
  if (u.includes('GREAT') || u.includes('GOLD')) return 'text-info';
  if (u.includes('FAIR') || u.includes('SILVER')) return 'text-warning';
  return 'text-danger';
}

/** Direction is pre-corrected server-side for lower-is-better metrics, so "up"
 *  always means IMPROVED even when the number fell. Never re-derive from delta. */
function Direction({ dir }: { dir?: string | null }) {
  const c = 'w-3.5 h-3.5 shrink-0';
  if (dir === 'up') return <TrendingUp className={`${c} text-success`} />;
  if (dir === 'down') return <TrendingDown className={`${c} text-danger`} />;
  return <Minus className={`${c} text-muted-foreground`} />;
}

function Sparkline({ trend }: { trend: MetricTrend }) {
  const vals = trend.points.map(p => p.value).filter((v): v is number => v != null);
  if (vals.length < 2) return <span className="text-[10px] text-muted-foreground">not enough history</span>;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  return (
    <div className="flex items-end gap-[2px] h-7">
      {trend.points.map((p, i) => {
        if (p.value == null) {
          // A missing week renders as a gap, never interpolated — pretending
          // continuity across absent data would misstate the trend.
          return <div key={i} className="w-1.5 h-full bg-border/30 rounded-sm" title={`${p.week}: no data`} />;
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

export default function MyScorecardPanel() {
  const [data, setData] = useState<ScorecardTrendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    axiosClient.get<ScorecardTrendResponse>('/scorecards/me/trend?weeks=12')
      .then(({ data }) => setData(data))
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  if (failed || !data || data.metrics.length === 0) {
    // Not an error state: most field staff have no Amazon scorecard until one
    // is entered for them, and an empty panel must not read as a failure.
    return (
      <div className="card">
        <div className="flex items-center gap-2 mb-2">
          <Award className="w-5 h-5 text-muted-foreground" />
          <h2 className="section-title">My Scorecard</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          No Amazon scorecard recorded for you yet.
        </p>
      </div>
    );
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-2">
        <Award className="w-5 h-5 text-primary" />
        <h2 className="section-title">My Scorecard</h2>
        {data.current_standing && (
          <span className={`ml-auto text-sm font-bold ${standingTone(data.current_standing)}`}>
            {data.current_standing}
          </span>
        )}
      </div>

      {/* The attribution is load-bearing, not boilerplate: two differing numbers
          on one account read as a bug unless the reader knows they come from
          different sources. */}
      <p className="text-xs text-muted-foreground">
        Amazon's weekly assessment of your work. My Stats is AsheFlow's own
        record — the two are measured separately and can differ.
      </p>

      {(data.focus_now ?? []).length > 0 && (
        <div className="rounded-lg bg-warning/10 border border-warning/20 p-3">
          <p className="text-xs font-semibold text-warning uppercase tracking-wider mb-1">
            Needs focus
          </p>
          <p className="text-sm text-foreground">{(data.focus_now ?? []).join(' · ')}</p>
        </div>
      )}

      <div className="space-y-2">
        {data.metrics.map(m => (
          <div key={m.key} className="flex items-center gap-3 py-1.5 border-t border-border first:border-t-0">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-foreground truncate">{m.label}</p>
              <p className="text-[11px] text-muted-foreground">
                {m.latest != null ? `${m.latest}${m.unit ?? ''}` : DASH}
                {m.previous != null && (
                  <span className="ml-1">
                    (prev {m.previous}{m.unit ?? ''})
                  </span>
                )}
              </p>
            </div>
            <Sparkline trend={m} />
            <Direction dir={m.direction} />
          </div>
        ))}
      </div>
    </div>
  );
}
