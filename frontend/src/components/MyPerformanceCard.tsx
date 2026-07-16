import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import type { MyPerformance } from '../api/types';
import { Package, Star, TrendingUp, AlertTriangle } from 'lucide-react';

/** My Performance card (ADR-203). The caller's own live field-execution stats
 *  from OUR data (distinct from the official Amazon Scorecard). Role-adaptive:
 *  field workers see deliveries/RTS; everyone sees their rating. */
export default function MyPerformanceCard() {
  const [data, setData] = useState<MyPerformance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axiosClient.get<MyPerformance>('/field-ops/me/performance')
      .then(({ data }) => setData(data))
      .catch(e => setError(errorText(e, 'Could not load your performance.')))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return null;
  if (error) return null;   // silent — a stats card shouldn't error the page
  if (!data) return null;

  const isField = ['walker', 'trainee', 'driver'].includes(data.role);
  const maxDaily = Math.max(1, ...data.daily_last_week.map(d => Math.max(d.delivered, d.rts)));
  const maxWeek = Math.max(1, ...data.weekly_trend.map(w => w.delivered));

  return (
    <div className="card space-y-5">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <TrendingUp className="w-4 h-4 text-primary" />
        </div>
        <h2 className="text-base font-bold text-foreground">My Performance</h2>
        <span className="text-xs text-muted-foreground ml-auto">Your live stats</span>
      </div>

      {/* Headline tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {isField && (
          <Tile icon={<Package className="w-4 h-4" />} label="Delivered (lifetime)"
                value={data.lifetime_delivered.toLocaleString()} />
        )}
        {isField && (
          <Tile label="Success rate"
                value={data.success_pct != null ? `${data.success_pct}%` : '—'}
                accent={data.success_pct != null && data.success_pct < 90 ? 'warn' : 'ok'} />
        )}
        <Tile icon={<Star className="w-4 h-4" />} label="Peer rating"
              value={data.avg_stars != null ? `${data.avg_stars}★` : '—'}
              sub={data.grade ? `Grade ${data.grade}` : undefined} />
        {isField && (
          <Tile label="Trips this week" value={String(data.trips_this_week)}
                sub={data.trips_today ? `${data.trips_today} today` : undefined} />
        )}
      </div>

      {isField && (
        <>
          {/* Lifetime RTS / missing sub-line */}
          <p className="text-xs text-muted-foreground">
            {data.lifetime_rts.toLocaleString()} RTS · {data.lifetime_missing.toLocaleString()} missing (lifetime)
          </p>

          {/* Last 7 days delivered vs RTS */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Last 7 days</p>
            <div className="flex items-end gap-2 h-24">
              {data.daily_last_week.map(d => (
                <div key={d.day} className="flex-1 flex flex-col items-center justify-end gap-0.5">
                  <div className="w-full flex flex-col items-center justify-end gap-0.5" style={{ height: '100%' }}>
                    <div className="w-full rounded-t bg-emerald-500/80"
                         style={{ height: `${(d.delivered / maxDaily) * 100}%` }} title={`${d.delivered} delivered`} />
                    {d.rts > 0 && (
                      <div className="w-full rounded-t bg-amber-500/80"
                           style={{ height: `${(d.rts / maxDaily) * 100}%` }} title={`${d.rts} RTS`} />
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground">{d.day.slice(5)}</span>
                </div>
              ))}
            </div>
            <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground">
              <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500/80" /> Delivered</span>
              <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-500/80" /> RTS</span>
            </div>
          </div>

          {/* 4-week trend */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">4-week trend</p>
            <div className="flex items-end gap-3 h-16">
              {data.weekly_trend.map(w => (
                <div key={w.week_start} className="flex-1 flex flex-col items-center justify-end gap-1">
                  <span className="text-[10px] text-foreground font-medium">{w.delivered}</span>
                  <div className="w-full rounded-t bg-primary/70" style={{ height: `${(w.delivered / maxWeek) * 100}%` }} />
                  <span className="text-[10px] text-muted-foreground">{w.week_start.slice(5)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 30-day diagnostics */}
          {(data.rts_reasons_30d.length > 0 || data.troublesome_addresses_30d.length > 0) && (
            <div className="grid sm:grid-cols-2 gap-4">
              {data.rts_reasons_30d.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">RTS reasons (30d)</p>
                  <ul className="space-y-1">
                    {data.rts_reasons_30d.map(r => (
                      <li key={r.rts_type} className="flex justify-between text-xs">
                        <span className="text-foreground capitalize">{r.rts_type.replace(/_/g, ' ')}</span>
                        <span className="text-muted-foreground">{r.count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {data.troublesome_addresses_30d.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Troublesome addresses (30d)</p>
                  <ul className="space-y-1">
                    {data.troublesome_addresses_30d.map(a => (
                      <li key={a.normalised_address} className="flex justify-between text-xs gap-2">
                        <span className="inline-flex items-center gap-1 text-foreground truncate">
                          <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" />{a.normalised_address}
                        </span>
                        <span className="text-muted-foreground shrink-0">{a.count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Tile({ icon, label, value, sub, accent }: {
  icon?: React.ReactNode; label: string; value: string; sub?: string; accent?: 'ok' | 'warn';
}) {
  const valColor = accent === 'warn' ? 'text-amber-600' : 'text-foreground';
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
        {icon}<span className="text-[10px] uppercase tracking-wider">{label}</span>
      </div>
      <p className={`text-lg font-bold ${valColor}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}
