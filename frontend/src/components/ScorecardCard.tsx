import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import type { Scorecard } from '../api/types';
import { Award, ChevronDown } from 'lucide-react';

/** Official Amazon (NYCD) weekly scorecard (ADR-204), surfaced to the employee on
 *  My Account. Read-only view of what the manager ingested; latest week shown,
 *  older weeks selectable. */
export default function ScorecardCard() {
  const [cards, setCards] = useState<Scorecard[]>([]);
  const [idx, setIdx] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axiosClient.get<Scorecard[]>('/scorecards/me')
      .then(({ data }) => setCards(data ?? []))
      .catch(e => { void errorText(e, ''); })
      .finally(() => setLoading(false));
  }, []);

  if (loading || cards.length === 0) return null;   // no scorecard yet → no card
  const sc = cards[idx];

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <Award className="w-4 h-4 text-primary" />
        </div>
        <h2 className="text-base font-bold text-foreground">Amazon Scorecard</h2>
        {cards.length > 1 ? (
          <div className="relative ml-auto">
            <select
              value={idx}
              onChange={e => setIdx(Number(e.target.value))}
              className="appearance-none text-xs border border-border rounded-lg pl-3 pr-7 py-1.5 bg-background"
            >
              {cards.map((c, i) => <option key={c.id} value={i}>{c.week}</option>)}
            </select>
            <ChevronDown className="w-3.5 h-3.5 absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          </div>
        ) : (
          <span className="ml-auto text-xs text-muted-foreground">{sc.week}</span>
        )}
      </div>

      {sc.overall_standing && (
        <div className="rounded-lg border border-emerald-300/40 bg-emerald-50 px-4 py-3 flex items-center justify-between">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Overall Standing</span>
          <span className="text-lg font-extrabold text-emerald-700">{sc.overall_standing}</span>
        </div>
      )}

      <div className="divide-y divide-border">
        {sc.metrics.map(m => (
          <div key={m.id} className="flex items-center gap-3 py-2.5">
            <span className="text-sm font-semibold text-foreground flex-1 min-w-0 truncate">{m.label}</span>
            <span className="text-sm font-bold text-foreground tabular-nums">
              {m.value}{m.unit && !m.value.includes(m.unit) ? ` ${m.unit}` : ''}
            </span>
            {m.flag && (
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                m.flag === 'excellent'
                  ? 'text-emerald-700 bg-emerald-50'
                  : 'text-amber-700 bg-amber-50'
              }`}>
                {m.flag === 'excellent' ? 'Excellent' : 'Needs Focus'}
              </span>
            )}
          </div>
        ))}
      </div>

      {sc.source_file_url && (
        <a href={sc.source_file_url} target="_blank" rel="noreferrer"
           className="text-xs text-primary hover:underline">View original scorecard</a>
      )}
    </div>
  );
}
