/**
 * Company standing — Tier 1, visible to EVERY role.
 *
 * A driver knowing the DSP is at FANTASTIC this week is the same class of
 * information as a company announcement: it is a shared fact about the
 * operation and contains nobody's individual numbers. The restriction that
 * matters is Tier 3 — a person sees their own scorecard and no one else's.
 *
 * See docs/SCORECARD_ACCESS_MODEL.md.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Award, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import type { CompanyStandingCard as StandingData } from '../api/types';

/** Amazon's ladder, best first — index order drives the colour. */
function standingTone(s?: string | null): string {
  if (!s) return 'text-muted-foreground';
  const u = s.toUpperCase();
  if (u.includes('FANTASTIC') || u.includes('PLATINUM')) return 'text-success';
  if (u.includes('GREAT') || u.includes('GOLD')) return 'text-info';
  if (u.includes('FAIR') || u.includes('SILVER')) return 'text-warning';
  return 'text-danger';
}

export default function CompanyStandingCard({ compact = false }: { compact?: boolean }) {
  const [data, setData] = useState<StandingData | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await axiosClient.get<StandingData>('/scorecards/company/current');
      setData(res.data);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Fail closed: this is a supplementary card on someone else's dashboard, so a
  // backend without the endpoint hides it rather than showing an error row.
  if (failed || !data || !data.has_data) return null;

  const tone = standingTone(data.standing);
  const Icon =
    data.direction === 'improved' ? TrendingUp
    : data.direction === 'declined' ? TrendingDown
    : Minus;
  const dirTone =
    data.direction === 'improved' ? 'text-success'
    : data.direction === 'declined' ? 'text-danger'
    : 'text-muted-foreground';

  return (
    <div className={`card flex items-center gap-4 ${compact ? 'py-3' : ''}`}>
      <Award className={`w-8 h-8 shrink-0 ${tone}`} />

      <div className="min-w-0">
        <p className="text-xs text-muted-foreground uppercase tracking-wider">
          Company standing · {data.week}
        </p>
        <p className={`text-2xl font-bold ${tone}`}>{data.standing ?? '—'}</p>
      </div>

      <div className="ml-auto text-right shrink-0">
        <div className={`flex items-center justify-end gap-1 ${dirTone}`}>
          <Icon className="w-4 h-4" />
          <span className="text-sm font-medium">
            {data.direction === 'improved' ? 'Improved'
              : data.direction === 'declined' ? 'Declined'
              : data.direction === 'unchanged' ? 'Unchanged'
              : '—'}
          </span>
        </div>
        {/* A streak says something the current tier alone does not:
            "FANTASTIC, 6 weeks running" is a different fact from "FANTASTIC". */}
        {(data.consecutive_weeks ?? 0) > 1 && (
          <p className="text-xs text-subtle mt-0.5 tabular-nums">
            {data.consecutive_weeks} weeks running
          </p>
        )}
        {data.previous_standing && data.direction !== 'unchanged' && (
          <p className="text-xs text-subtle tabular-nums">from {data.previous_standing}</p>
        )}
      </div>
    </div>
  );
}
