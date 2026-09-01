/**
 * My Stats drill-down (ADR-271). Replaces RecentDaysSection and the 4-week trend.
 *
 * ZOOM OUT, not in. Entry is the most recent day WITH DATA; the user expands to
 * week, month, year, lifetime. Analyst tools drill inward from an aggregate
 * because they are hunting an anomaly nobody has spotted; personal-stats apps
 * expand outward because the user already knows what they are asking — "how did
 * I do, and is that normal for me?". This is the second kind, and the inward
 * model cost four clicks to reach the day they actually worked.
 *
 * ONE request drives every level: /me/stats returns an immutable daily series
 * (ends yesterday) that this aggregates on device. A second, period-scoped
 * request fetches top blocks and attendance, because "top 5 for week 1 may not
 * be top 5 for the month" — those cannot be precomputed for every period.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axiosClient from '../../api/axiosClient';
import type { MyStats, PeriodExtras } from '../../api/types';
import {
  ChevronLeft, ChevronRight, ChevronUp, TrendingUp, TrendingDown,
  Truck, Package, MapPin, CalendarCheck,
} from 'lucide-react';
import {
  attendanceIn, daysOfWeek, monthsOfYear, reasonsIn, weeksOfMonth, yearsFrom,
  lastWorkedDay, parseYMD, ymd, type Bucket, type Grain,
} from './aggregate';

/** One hue per role, so the eye can group the crew without reading the labels.
 *  Mirrors `roleTone()` in mobile/src/components/stats/crew.ts. */
const ROLE_DOT: Record<string, string> = {
  driver: 'bg-warning', captain: 'bg-gold', trainer: 'bg-info',
  trainee: 'bg-success', walker: 'bg-primary',
};
const ROLE_TINT: Record<string, string> = {
  driver: 'bg-warning/15 text-warning', captain: 'bg-gold/15 text-gold',
  trainer: 'bg-info/15 text-info', trainee: 'bg-success/15 text-success',
  walker: 'bg-primary/15 text-primary',
};

const EFFORT_BG: Record<string, string> = {
  easy: 'bg-info', standard: 'bg-success', heavy: 'bg-warning',
};

const LEVEL_NAME: Record<Grain, string> = {
  day: 'Day', week: 'Week', month: 'Month', year: 'Year', lifetime: 'Lifetime',
};

/** A delta, or NOTHING when there is no completed prior period. Deliberately
 *  renders null rather than a neutral arrow: "nothing to compare" and "no
 *  change" are different facts (ADR-271 D3). */
function Trend({ pct }: { pct: number | null }) {
  if (pct === null) return null;
  const up = pct >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[11px] font-bold
                      px-2 py-0.5 rounded-full ${
      up ? 'text-success bg-success/10' : 'text-danger bg-danger/10'}`}>
      <Icon className="w-3 h-3" />{Math.abs(pct).toFixed(1)}%
    </span>
  );
}

function Figures({ b, truckScoped }: { b: Bucket; truckScoped: boolean }) {
  const attempted = b.delivered + b.rts + b.missing;
  const success = attempted ? (b.delivered / attempted) * 100 : null;
  // Drivers and captains answer for damage reported on the TRUCK; walkers for
  // what they brought back. Never summed — different events (ADR-271 F).
  const damaged = truckScoped ? b.truckDamaged : b.damaged;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
      <div className="sm:col-span-2 rounded-xl border border-border bg-background p-4">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Delivered</p>
        <p className="text-3xl font-bold text-foreground tabular-nums mt-0.5">
          {b.delivered.toLocaleString()}
        </p>
        {success !== null && (
          <p className="text-[11px] text-muted-foreground mt-1">
            {success.toFixed(1)}% of {attempted.toLocaleString()} attempted
          </p>
        )}
      </div>
      <div className="sm:col-span-3 grid grid-cols-3 gap-2">
        {[
          { label: 'RTS', v: b.rts, tone: 'text-warning' },
          { label: truckScoped ? 'Truck damage' : 'Damaged', v: damaged, tone: 'text-danger' },
          { label: 'Missing', v: b.missing, tone: 'text-danger' },
        ].map(i => (
          <div key={i.label} className="rounded-xl bg-accent/25 p-3 flex flex-col justify-center">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{i.label}</p>
            <p className={`text-xl font-bold tabular-nums ${i.tone}`}>{i.v.toLocaleString()}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Bars({ data, onPick }: { data: Bucket[]; onPick: (b: Bucket) => void }) {
  const max = Math.max(1, ...data.map(d => d.delivered));
  if (!data.some(d => d.delivered > 0)) {
    return (
      <p className="text-[11px] text-muted-foreground italic text-center py-8">
        Nothing delivered in this period.
      </p>
    );
  }
  // A ROTATING PALETTE, one tone per bucket. Effort class only ever varies at
  // DAY grain — a week or month mixes efforts, so every coarse bar fell back to
  // one flat primary and the chart read as a single undifferentiated block.
  const TONES = ['bg-primary', 'bg-success', 'bg-info', 'bg-warning', 'bg-gold', 'bg-danger'];
  return (
    <div>
      <div className="flex items-end gap-3 h-48 border-b border-border">
        {data.map((d, i) => {
          const empty = d.delivered === 0;
          const pct = Math.max(4, (d.delivered / max) * 100);
          // THE LABEL GOES INSIDE ONCE THE BAR IS TALL. Rendered above the bar
          // in a fixed-height column, the tallest bar's number is pushed out of
          // the plot and collides with the heading above it.
          const inside = pct > 78;
          return (
            <button
              key={d.key}
              onClick={() => !empty && onPick(d)}
              disabled={empty}
              className="flex-1 h-full flex flex-col justify-end items-center gap-1
                         group disabled:cursor-default"
              title={`${d.label}: ${d.delivered.toLocaleString()} delivered`}
            >
              {!inside && (
                <span className={`text-[10px] tabular-nums transition-colors ${
                  empty ? 'text-transparent' : 'text-muted-foreground group-hover:text-foreground'}`}>
                  {d.delivered > 0 ? d.delivered.toLocaleString() : ''}
                </span>
              )}
              {empty ? (
                <div className="w-full h-[2px] bg-border rounded-full" />
              ) : (
                <div
                  className={`w-full rounded-t-md transition-all
                              ${d.effort ? EFFORT_BG[d.effort] : TONES[i % TONES.length]}
                              opacity-85 group-hover:opacity-100`}
                  style={{ height: `${pct}%` }}
                >
                  {inside && (
                    <span className="block text-[10px] font-bold tabular-nums text-background pt-1">
                      {d.delivered.toLocaleString()}
                    </span>
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>
      {/* A VISUAL AFFORDANCE, not just the instruction in the heading. Most
          people skim past a heading, so a clickable bucket has to LOOK
          clickable; an empty one stays flat, which doubles as its disabled
          state. */}
      <div className="flex gap-3 mt-2">
        {data.map(d => (
          <span key={d.key} className="flex-1 flex justify-center">
            {/* `label`, not `short`: web has the width for "Sun 26", and the
                date number is real information the phone has to drop. */}
            <span className={`text-[11px] px-1.5 py-0.5 rounded whitespace-nowrap ${
              d.delivered > 0
                ? 'bg-primary/10 text-primary font-semibold'
                : 'text-muted-foreground/40'}`}>
              {d.label}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Month-by-month as a LINE, not bars.
 *
 *  Twelve bars are too thin to carry a value label and too chunky to show a
 *  trend. A line answers the question a year view is actually asked — "which
 *  way is this going".
 *
 *  MONTHS WITH NO WORK ARE DRAWN AS ZERO, not as a break in the line. Field
 *  staff take breaks, so a quiet month is a REAL zero the person lived through;
 *  in this domain a gap reads as a data-collection failure, which would be the
 *  misleading reading rather than the honest one (ADR-271 §R).
 */
function LineChart({ data, onPick }: { data: Bucket[]; onPick: (b: Bucket) => void }) {
  const max = Math.max(1, ...data.map(d => d.delivered));
  if (!data.some(d => d.delivered > 0)) {
    return (
      <p className="text-[11px] text-muted-foreground italic text-center py-8">
        Nothing delivered in this period.
      </p>
    );
  }
  // TOP pad reserved for the peak's value label, drawn above its point.
  const W = 640, H = 200, PAD = 12, TOP = 28;
  // CELL CENTRES, not edge-to-edge. The label row below is a flex of N equal
  // cells with the text centred in each, so label i sits at (i + 0.5)/N of the
  // width. Spacing the points PAD..W-PAD instead put point 0 hard against the
  // left edge and point N-1 against the right, so the dots drifted out of line
  // with their labels — worst at the ends, invisible in the middle.
  const cell = W / data.length;
  const x = (i: number) => cell * (i + 0.5);
  const y = (v: number) => H - PAD - (v / max) * (H - PAD - TOP);
  const pts = data.map((d, i) => `${x(i)},${y(d.delivered)}`).join(' ');
  const area = `${x(0)},${H - PAD} ${pts} ${x(data.length - 1)},${H - PAD}`;
  const peak = data.reduce((b, d, i) => (d.delivered > data[b].delivered ? i : b), 0);
  return (
    <div>
      {/* preserveAspectRatio is NOT "none": stretching the viewBox to the
          container squashed the line flat on a wide screen and distorted the
          point markers into ellipses. The plot keeps its aspect and the
          container scales it. */}
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-52" preserveAspectRatio="xMidYMid meet">
        <line x1={x(0)} y1={H - PAD} x2={x(data.length - 1)} y2={H - PAD}
              className="stroke-border" strokeWidth="1" />
        <polyline points={area} className="fill-primary/15" />
        <polyline points={pts} className="stroke-primary fill-none"
                  strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        {/* Point markers, as on mobile: without them a reader cannot tell where
            a month actually falls, only the shape between months. */}
        {data.map((d, i) => (
          <circle key={d.key} cx={x(i)} cy={y(d.delivered)} r={i === peak ? 5 : 3.5}
                  className={i === peak ? 'fill-primary stroke-primary' : 'fill-card stroke-primary'}
                  strokeWidth="2" />
        ))}
        {/* The peak label lives INSIDE the svg, in the headroom reserved by
            TOP. On the axis row it pushed its own month chip down out of line
            with the other eleven. */}
        <text x={x(peak)} y={Math.max(13, y(data[peak].delivered) - 11)}
              textAnchor="middle" className="fill-foreground"
              fontSize="13" fontWeight="700">
          {data[peak].delivered.toLocaleString()}
        </text>
      </svg>
      {/* Hit targets OUTSIDE the svg: a full-height column is a better click
          target than a 5px circle. */}
      {/* NO gap: a gap narrows each cell, so the centres no longer match
          the svg's W/N cell centres and the dots drift off their labels. */}
      <div className="flex -mt-2">
        {data.map(d => (
          <button
            key={d.key}
            onClick={() => d.delivered > 0 && onPick(d)}
            disabled={d.delivered === 0}
            title={`${d.label}: ${d.delivered.toLocaleString()} delivered`}
            className="flex-1 text-center disabled:cursor-default group"
          >
            {/* THREE letters: Jan/Jun/Jul all start with J, so one letter made
                a third of the axis ambiguous. */}
            <span className={`inline-block text-[11px] px-1.5 py-0.5 rounded transition-colors ${
              d.delivered > 0
                ? 'bg-primary/10 text-primary font-semibold group-hover:bg-primary/20'
                : 'text-muted-foreground/40'}`}>
              {d.short}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Lifetime for an account with too little history to chart. One bar labelled
 *  "2026" is not a chart — it is a rectangle, and it reads as a rendering
 *  fault. Below two years, show the numbers and say when the chart arrives. */
function LifetimeSummary({ years, lt, onPick }: {
  years: Bucket[];
  lt: { delivered: number | null; trips: number };
  onPick: (b: Bucket) => void;
}) {
  const best = years.reduce<Bucket | null>(
    (b, y) => (!b || y.delivered > b.delivered ? y : b), null);
  const span = years.length === 1 ? years[0].label
             : `${years[0]?.label}–${years[years.length - 1]?.label}`;
  // ZOOMING IN MUST STILL BE POSSIBLE. Every other level offers a bar to click;
  // replacing the single year bar with figures removed the ONLY way back in
  // from Lifetime — and Lifetime has no zoom-out trail either, so the screen
  // became a dead end. The year tile is the control.
  const target = years.length === 1 ? years[0] : best;
  return (
    <div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {([
          // ADR-305: em-dash when the figure is not derivable, never 0.
          ['Delivered', lt.delivered !== null ? lt.delivered.toLocaleString() : '—', null],
          ['Best year', best ? best.delivered.toLocaleString() : '—', null],
          ['Trips', lt.trips.toLocaleString(), null],
          [years.length === 1 ? 'Only year' : 'Span', span || '—', target],
        ] as [string, string, Bucket | null][]).map(([l, v, tap]) => {
          const body = (
            <>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{l}</p>
              <p className="text-xl font-bold text-foreground tabular-nums">{v}</p>
              {!!tap && <p className="text-[10px] font-semibold text-primary mt-0.5">
                click to open →
              </p>}
            </>
          );
          return tap ? (
            <button key={l} onClick={() => onPick(tap)}
                    title={`Open ${tap.label}`}
                    className="rounded-lg border border-primary bg-background p-3 text-left
                               hover:bg-accent/30 transition-colors">
              {body}
            </button>
          ) : (
            <div key={l} className="rounded-lg border border-border bg-background p-3">
              {body}
            </div>
          );
        })}
      </div>
      <p className="text-[11px] text-muted-foreground italic text-center py-4">
        A year-by-year chart appears once you have two full years of history.
      </p>
    </div>
  );
}

const RTS_LABEL: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Customer rescheduled',
  customer_cancelled_order: 'Customer cancelled',
};

const DONUT_TONE = ['stroke-info', 'stroke-warning', 'stroke-success',
                    'stroke-danger', 'stroke-muted-foreground'];

/** Why packages came back, for the selected period.
 *
 *  stroke-dasharray, one circle per segment — no path math, no arc flags. Capped
 *  at top 4 + Other: the technique gets fiddly past ~6 segments and there are 6
 *  RTS types, and a five-slice donut is better information design regardless. */
function ReasonDonut({ reasons }: { reasons: { rts_type: string; count: number }[] }) {
  const total = reasons.reduce((n, r) => n + r.count, 0);
  if (!total) {
    return (
      <p className="text-[11px] text-muted-foreground italic">
        Nothing came back in this period.
      </p>
    );
  }
  const top = reasons.slice(0, 4);
  const rest = reasons.slice(4).reduce((n, r) => n + r.count, 0);
  const slices = rest > 0
    ? [...top, { rts_type: 'other', count: rest }]
    : top;

  let offset = 25;   // start at 12 o'clock
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-center">
      <div className="flex justify-center">
        <svg viewBox="0 0 42 42" className="w-56 h-56 max-w-full">
          <circle cx="21" cy="21" r="15.9" fill="none" className="stroke-border"
                  strokeWidth="6" />
          {slices.map((r, i) => {
            const pct = (r.count / total) * 100;
            const el = (
              <circle key={r.rts_type} cx="21" cy="21" r="15.9" fill="none"
                      className={DONUT_TONE[i % DONUT_TONE.length]} strokeWidth="6"
                      strokeDasharray={`${pct} ${100 - pct}`} strokeDashoffset={offset} />
            );
            offset -= pct;
            return el;
          })}
          <text x="21" y="20.5" textAnchor="middle" className="fill-foreground"
                fontSize="8" fontWeight="700">{total}</text>
          <text x="21" y="25.5" textAnchor="middle" className="fill-muted-foreground"
                fontSize="2.8" letterSpacing="0.3">RETURNED</text>
        </svg>
      </div>
      <ul className="space-y-3">
        {slices.map((r, i) => {
          const pct = (r.count / total) * 100;
          return (
            <li key={r.rts_type}>
              <div className="flex items-baseline gap-2 mb-1">
                <span className={`w-2.5 h-2.5 rounded-sm shrink-0
                                  ${DONUT_TONE[i % DONUT_TONE.length].replace('stroke-', 'bg-')}`} />
                <span className="text-[15px] text-foreground flex-1">
                  {r.rts_type === 'other' ? 'Other' : (RTS_LABEL[r.rts_type] ?? r.rts_type)}
                </span>
                <span className="text-[15px] font-semibold text-foreground tabular-nums">
                  {r.count}
                </span>
                <span className="text-xs text-muted-foreground tabular-nums w-10 text-right">
                  {Math.round(pct)}%
                </span>
              </div>
              <div className="h-2 rounded-full bg-accent/40 overflow-hidden">
                <div className={`h-full rounded-full ${DONUT_TONE[i % DONUT_TONE.length].replace('stroke-', 'bg-')}`}
                     style={{ width: `${pct}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Top blocks + attendance. Week outward only — at a single day "top blocks"
 *  is just "the blocks you worked", which belongs in the day detail. */
function PeriodPanels({ extras, attendance }: {
  extras: PeriodExtras | null;
  attendance: { present: number; late: number; ncns: number; total: number; rate: number | null };
}) {
  // Attendance is DERIVED from the cached series — no request. Only the block
  // ranking still needs one, because per-day blocks measured 141 KB across two
  // years and would have more than doubled the bulk payload for one panel.
  const a = attendance;
  const blocks = extras?.top_blocks ?? [];
  const blocks_apply = extras?.blocks_apply ?? true;
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 pt-5 border-t border-border">
      {/* Attendance — self-controlled and fair, and it appears nowhere else in
          the product for the person themselves. */}
      <div>
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3
                      flex items-center gap-1.5">
          <CalendarCheck className="w-3.5 h-3.5" /> Attendance
        </p>
        {a.total === 0 ? (
          /* Null rate, not 0% — "no roll calls" is not "0% attendance". */
          <p className="text-[11px] text-muted-foreground italic">
            No roll calls recorded for this period.
          </p>
        ) : (
          <>
            <p className="text-2xl font-bold text-foreground tabular-nums">
              {a.rate?.toFixed(0)}%
              <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                {a.present} of {a.total} shifts
              </span>
            </p>
            <div className="flex gap-4 mt-2 text-[11px]">
              <span className="text-success">{a.present} present</span>
              {a.late > 0 && <span className="text-warning">{a.late} late</span>}
              {a.ncns > 0 && <span className="text-danger">{a.ncns} no-show</span>}
            </div>
          </>
        )}
      </div>

      {/* Blocks — hidden entirely for driver/captain, who never own stops.
          An empty panel reads as broken, not as "not applicable to you". */}
      {blocks_apply && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3
                        flex items-center gap-1.5">
            <MapPin className="w-3.5 h-3.5" /> Hardest blocks
            <span className="normal-case tracking-normal text-muted-foreground/70">
              — most returns for the work done
            </span>
          </p>
          {blocks.length === 0 ? (
            <p className="text-[11px] text-muted-foreground italic">
              No blocks worked in this period.
            </p>
          ) : (
            <ul className="space-y-2">
              {blocks.map(b => (
                <li key={b.block_key} className="flex items-baseline gap-2 text-xs">
                  <span className="text-foreground flex-1 font-mono">
                    {b.block_key.replace(/_/g, ' ')}
                  </span>
                  <span className="text-muted-foreground">{b.stops} stops</span>
                  <span className={`tabular-nums font-semibold w-12 text-right ${
                    (b.rts_rate ?? 0) > 0.15 ? 'text-danger' : 'text-muted-foreground'}`}>
                    {b.rts_rate === null ? '—' : `${Math.round(b.rts_rate * 100)}%`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function StatsDrill() {
  const [stats, setStats] = useState<MyStats | null>(null);
  const [extras, setExtras] = useState<PeriodExtras | null>(null);
  const [level, setLevel] = useState<Grain>('day');
  const [cursor, setCursor] = useState<Bucket | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axiosClient.get<MyStats>('/assignment-history/me/stats')
      .then(({ data }) => setStats(data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  const days = stats?.series.days ?? [];
  const truckScoped = stats?.series.role === 'driver' || stats?.series.role === 'captain';

  // Entry point: the most recent day WITH data. Someone off yesterday would
  // otherwise land on an empty screen.
  const entry = useMemo(() => {
    const d = lastWorkedDay(days);
    if (!d) return null;
    const week = daysOfWeek(days, (() => {
      const dt = parseYMD(d.d); dt.setDate(dt.getDate() - dt.getDay()); return dt;
    })());
    return week.find(b => b.key === d.d) ?? null;
  }, [days]);

  useEffect(() => { if (entry && !cursor) setCursor(entry); }, [entry, cursor]);

  // Siblings and children of the current cursor, recomputed per level.
  const { siblings, charted } = useMemo(() => {
    if (!cursor || !stats) return { siblings: [] as Bucket[], charted: [] as Bucket[] };
    const dt = parseYMD(cursor.start);
    const weekStart = (() => { const s = new Date(dt); s.setDate(dt.getDate() - dt.getDay()); return s; })();
    switch (level) {
      case 'day':
        return { siblings: daysOfWeek(days, weekStart), charted: [] };
      case 'week':
        return { siblings: weeksOfMonth(days, dt.getFullYear(), dt.getMonth()),
                 charted: daysOfWeek(days, parseYMD(cursor.start)) };
      case 'month':
        return { siblings: monthsOfYear(days, dt.getFullYear()),
                 charted: weeksOfMonth(days, dt.getFullYear(), dt.getMonth()) };
      case 'year':
        return { siblings: yearsFrom(stats.years),
                 charted: monthsOfYear(days, dt.getFullYear()) };
      default:
        return { siblings: [], charted: yearsFrom(stats.years) };
    }
  }, [level, cursor, days, stats]);

  // Period extras: week outward only.
  // Fetched at EVERY level, including day. Blocks and attendance are week-
  // outward only (see PeriodPanels), but the REASON MIX is useful on a single
  // day too: the day view lists individual RTS rows, and the donut is what
  // turns nine rows into "mostly no-access".
  //
  // CACHED FOR THE SESSION. Every period this can be asked about ended
  // yesterday or earlier — the series never includes today (ADR-271 C) — so
  // the answer is IMMUTABLE and re-requesting it on every navigation is pure
  // latency. Stepping back and forth between two weeks previously refetched
  // both every time.
  const extrasCache = useRef<Map<string, PeriodExtras>>(new Map());

  const fetchExtras = useCallback((b: Bucket) => {
    const key = `${b.start}:${b.end}`;
    const hit = extrasCache.current.get(key);
    if (hit) { setExtras(hit); return; }          // no request at all
    axiosClient.get<PeriodExtras>('/assignment-history/me/stats/period',
      { params: { start_date: b.start, end_date: b.end } })
      .then(({ data }) => { extrasCache.current.set(key, data); setExtras(data); })
      .catch(() => setExtras(null));
  }, []);

  // Blocks alone still need the network. Reasons and attendance are computed
  // from the series already in memory — the bulk-fetch design as agreed.
  useEffect(() => {
    if (cursor && level !== 'day') fetchExtras(cursor);
  }, [cursor, level, fetchExtras]);

  const reasons = useMemo(
    () => (cursor ? reasonsIn(days, cursor.start, cursor.end) : []),
    [cursor, days]);
  const attendance = useMemo(
    () => (cursor ? attendanceIn(days, cursor.start, cursor.end)
                  : { present: 0, late: 0, ncns: 0, total: 0, rate: null }),
    [cursor, days]);

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!stats || !cursor) {
    return (
      <div className="card">
        <p className="text-sm text-muted-foreground">
          No completed work recorded yet. Your stats will appear after your first shift.
        </p>
      </div>
    );
  }

  const lt = stats.lifetime;
  const idx = siblings.findIndex(b => b.key === cursor.key);
  const prev = idx > 0 ? siblings[idx - 1] : null;
  const next = idx >= 0 && idx < siblings.length - 1 ? siblings[idx + 1] : null;

  const outer: Record<Grain, Grain | null> = {
    day: 'week', week: 'month', month: 'year', year: 'lifetime', lifetime: null,
  };
  // Which zoom-out levels are worth offering. Disabled where nothing is there:
  // zooming out to an empty screen is worse than having no control.
  const trail: { grain: Grain; enabled: boolean }[] = [];
  let g = outer[level];
  while (g) {
    const enabled = g === 'lifetime' ? stats.years.length > 0 : days.length > 0;
    trail.push({ grain: g, enabled });
    g = outer[g];
  }

  const zoomOut = (to: Grain) => {
    setLevel(to);
    const dt = parseYMD(cursor.start);
    if (to === 'week') {
      const s = new Date(dt); s.setDate(dt.getDate() - dt.getDay());
      const wk = weeksOfMonth(days, s.getFullYear(), s.getMonth());
      setCursor(wk.find(b => parseYMD(b.start) <= dt && parseYMD(b.end) >= dt) ?? wk[0]);
    } else if (to === 'month') {
      setCursor(monthsOfYear(days, dt.getFullYear())[dt.getMonth()]);
    } else if (to === 'year') {
      const ys = yearsFrom(stats.years);
      setCursor(ys.find(b => b.key === String(dt.getFullYear())) ?? ys[ys.length - 1]);
    } else {
      const ys = yearsFrom(stats.years);
      // START/END MUST SPAN EVERYTHING. This used to spread the LAST year
      // bucket (falling back to the current cursor when there were no years at
      // all), which left the range set to one year — or, in the fallback, to a
      // single DAY. Attendance and the reason donut are both derived from
      // cursor.start/end, so Lifetime reported "1 of 1 shifts" while the year
      // it came from had 101 of 110.
      const first = ys[0], last = ys[ys.length - 1];
      setCursor({
        key: 'lifetime', label: 'Lifetime', short: 'All',
        start: first ? first.start : days[0]?.d ?? cursor.start,
        end:   last  ? last.end    : days[days.length - 1]?.d ?? cursor.end,
        // ADR-305: null coalesces to 0 ONLY here, because `neverLoaded` already
        // reads delivered===0 && rts===0 as "no data" and renders the empty
        // state. Not a fabricated figure — it routes into the same path an
        // unloaded cursor takes. The DISPLAYED tile keeps the em-dash.
        delivered: lt.delivered ?? 0, rts: lt.rts,
        damaged: lt.damaged, truckDamaged: lt.truck_damaged,
        missing: lt.missing, total: 0, effort: null, trend: null,
      });
    }
  };

  const zoomIn = (b: Bucket) => {
    const inner: Record<Grain, Grain | null> = {
      lifetime: 'year', year: 'month', month: 'week', week: 'day', day: null,
    };
    const to = inner[level];
    if (to) { setLevel(to); setCursor(b); }
  };

  const isEntry = entry && cursor.key === entry.key && level === 'day';

  return (
    <div className="space-y-5">
      {/* LIFETIME HEADER — always visible, never changes with the drill. */}
      <div className="card">
        <div className="flex items-baseline gap-2 mb-3">
          <h2 className="section-title">Lifetime</h2>
          <span className="text-[11px] text-muted-foreground">all time</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            // ADR-305: null in workforce mode until a route is Flex-scanned.
            // Em-dash, never 0 — the same treatment success_pct already gets,
            // because "delivered nothing" is a different claim from "not
            // measured yet".
            ['Delivered', lt.delivered !== null ? lt.delivered.toLocaleString() : '—'],
            ['Success', lt.success_pct !== null ? `${lt.success_pct}%` : '—'],
            // TRIPS is a walker's measure: how many route runs they made. A
            // driver or captain runs the TRUCK, not their own routes, so the
            // figure is meaningless for them — they get RTS in that slot
            // instead, which is a number they do answer for.
            truckScoped
              ? ['RTS', lt.rts.toLocaleString()]
              : ['Trips', lt.trips.toLocaleString()],
            [truckScoped ? 'Truck damage' : 'Damaged',
             (truckScoped ? lt.truck_damaged : lt.damaged).toLocaleString()],
          ].map(([l, v]) => (
            <div key={l} className="rounded-lg border border-border bg-background p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{l}</p>
              <p className="text-xl font-bold text-foreground tabular-nums">{v}</p>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3 mt-3">
          {(truckScoped
            // RTS was promoted into the row above for these roles, so showing
            // it twice would just be noise.
            ? [['Missing', lt.missing] as [string, number]]
            : [['RTS', lt.rts] as [string, number], ['Missing', lt.missing]]
          ).map(([l, v]) => (
            <div key={l as string} className="rounded-lg bg-accent/20 p-2.5">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{l}</p>
              <p className="text-base font-bold text-foreground tabular-nums">
                {(v as number).toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* THE DRILL */}
      <div className="card space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1.5 flex-wrap text-sm">
            <span className="font-bold text-foreground">{cursor.label}</span>
            {trail.map(t => (
              <button
                key={t.grain}
                onClick={() => t.enabled && zoomOut(t.grain)}
                disabled={!t.enabled}
                title={t.enabled ? `Zoom out to ${LEVEL_NAME[t.grain].toLowerCase()}`
                                 : 'No data at this level yet'}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs
                           text-primary hover:bg-accent/40 disabled:opacity-30
                           disabled:text-muted-foreground disabled:hover:bg-transparent
                           transition-colors"
              >
                <ChevronUp className="w-3 h-3" />{LEVEL_NAME[t.grain]}
              </button>
            ))}
          </div>

          {siblings.length > 1 && (
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={() => prev && setCursor(prev)}
                style={{ visibility: prev ? 'visible' : 'hidden' }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs
                           text-foreground hover:bg-accent/40 transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" />{prev?.short}
              </button>
              <button
                onClick={() => next && setCursor(next)}
                style={{ visibility: next ? 'visible' : 'hidden' }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs
                           text-foreground hover:bg-accent/40 transition-colors"
              >
                {next?.short}<ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* HEADER — the date is the anchor of the card, so it owns its line at
            display size; status and trend sit on a metadata row BENEATH it
            rather than competing for the same baseline (ADR-271 §P). */}
        <div>
          <h3 className="text-2xl font-bold text-foreground tracking-tight">
            {level === 'day' || level === 'lifetime'
              ? cursor.label : `${LEVEL_NAME[level]} · ${cursor.label}`}
          </h3>
          <div className="flex items-center gap-2 flex-wrap mt-1">
            {isEntry && (
              /* A GREEN badge, not grey body text. "your last shift" as muted
                 prose read like a caveat; this is a positive status marker. */
              <span className="inline-flex items-center gap-1.5 text-[10px] font-bold
                               tracking-wider px-2 py-0.5 rounded-full
                               bg-success/15 text-success">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                LATEST
              </span>
            )}
            <Trend pct={cursor.trend} />
            {cursor.trend === null && level !== 'lifetime' && (
              <span className="text-[11px] text-muted-foreground">
                no earlier {LEVEL_NAME[level].toLowerCase()} to compare
              </span>
            )}
          </div>
        </div>

        <Figures b={cursor} truckScoped={truckScoped} />

        {/* OVERVIEW ABOVE, DETAIL BELOW. The donut summarises the period; the
            RTS list underneath can run to dozens of rows, so putting the
            summary after it buried the one element that makes a long list
            readable. */}
        {/* Rendered even when EMPTY. Hiding the whole block on a day with no
            returns makes the section look broken — the operator reported
            exactly that, having stepped onto days that genuinely had none.
            A stated "nothing came back" is an answer; a section that silently
            vanishes is not.

            THREE distinct states, and collapsing them loses the distinction
            the operator needs:
              carried, some back  -> the donut
              carried, none back  -> "nothing came back" (a GOOD day)
              never loaded        -> "rostered, no route assigned"
            The third is not a clean sheet: the person was on a truck and the
            day produced no route, which is an operational fact, not a zero. */}
        <div className="pt-4 border-t border-border">
          <div className="flex items-baseline gap-2 mb-4">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Why packages came back
            </p>
            <span className="text-[11px] text-muted-foreground/70">
              {truckScoped ? 'whole truck' : cursor.label}
            </span>
          </div>
          {cursor.total === 0 && cursor.delivered === 0 && cursor.rts === 0 ? (
            <p className="text-[13px] text-muted-foreground py-6 text-center">
              Rostered, but no route was assigned{level === 'day' ? ' this day' : ' in this period'}.
            </p>
          ) : (
            <ReasonDonut reasons={reasons} />
          )}
        </div>

        {level === 'day' ? (
          <DayDetail date={cursor.start} />
        ) : (
          <>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
                Delivered by {level === 'week' ? 'day' : level === 'month' ? 'week'
                              : level === 'year' ? 'month' : 'year'}
                {!(level === 'lifetime' && charted.length < 2) && (
                  <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/70">
                    — click {level === 'year' ? 'a month' : 'a bar'} to zoom in
                  </span>
                )}
              </p>
              {/* THREE presentations, because the levels ask different
                  questions and 12 thin bars answer none of them (ADR-271 §R). */}
              {level === 'year' ? (
                <LineChart data={charted} onPick={zoomIn} />
              ) : level === 'lifetime' && charted.length < 2 ? (
                <LifetimeSummary years={charted} lt={lt} onPick={zoomIn} />
              ) : (
                <Bars data={charted} onPick={zoomIn} />
              )}
            </div>
            <PeriodPanels extras={extras} attendance={attendance} />
          </>
        )}

      </div>
    </div>
  );
}

/** Day detail — truck, crew, RTS rows. Fetched on demand: this is the
 *  ~2 KB/day part deliberately kept out of the cached series (ADR-271 H). */
/** Module-level so it survives remounts: DayDetail unmounts every time the user
 *  zooms out and remounts when they return, which would otherwise re-request a
 *  day that ended yesterday and can never change. */
const dayCache = new Map<string, any>();

function DayDetail({ date }: { date: string }) {
  const [day, setDay] = useState<any | null>(() => dayCache.get(date) ?? null);
  const [loading, setLoading] = useState(!dayCache.has(date));

  useEffect(() => {
    if (dayCache.has(date)) {          // completed day — cannot have changed
      setDay(dayCache.get(date));
      setLoading(false);
      return;
    }
    setLoading(true);
    axiosClient.get('/assignment-history/me',
      { params: { start_date: date, end_date: date } })
      .then(({ data }) => {
        const d = (data.days ?? [])[0] ?? null;
        dayCache.set(date, d);
        setDay(d);
      })
      .catch(() => setDay(null))
      .finally(() => setLoading(false));
  }, [date]);

  if (loading) return <p className="text-[11px] text-muted-foreground italic">Loading day…</p>;
  if (!day) return null;

  const CREW_ORDER = ['driver', 'captain', 'trainer', 'walker', 'trainee'];
  const groups = new Map<string, string[]>();
  for (const m of day.crew ?? []) {
    if (!groups.has(m.role)) groups.set(m.role, []);
    groups.get(m.role)!.push(m.name);
  }
  const ordered = [...groups.entries()].sort(
    (a, b) => CREW_ORDER.indexOf(a[0]) - CREW_ORDER.indexOf(b[0]));

  return (
    <div className="space-y-4">
      {/* TRUCK BANNER — the truck is the identity of the day, so it gets a
          filled row with the vehicle glyph rather than a small outlined pill
          floating among chips. Effort and scope ride inside it as trailing
          metadata (ADR-271 §P). */}
      {(day.truck_name || day.counts_scope === 'truck') && (
        <div className="flex items-center gap-3 rounded-xl border border-border
                        bg-accent/20 p-3">
          <span className="w-9 h-9 rounded-lg bg-primary/15 text-primary
                           grid place-items-center shrink-0">
            <Truck className="w-4 h-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold text-foreground truncate">
              {day.truck_name ?? 'Assigned'}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {day.counts_scope === 'truck' ? 'whole truck' : 'your stops'}
              {day.slot_role && ` · ${day.slot_role}`}
            </p>
          </div>
          {/* Only exceptions get a chip — 'standard' on every row is noise. */}
          {day.effort_class && day.effort_class !== 'standard' && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full uppercase
                              tracking-wide font-bold shrink-0 ${
              day.effort_class === 'heavy' ? 'bg-warning/15 text-warning' : 'bg-info/10 text-info'}`}>
              {day.effort_class}
            </span>
          )}
        </div>
      )}

      {ordered.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
            Crew · {(day.crew ?? []).length}
          </p>
          <div className="space-y-3">
            {ordered.map(([role, names]) => (
              <div key={role}>
                {/* Role as a full-width header with a coloured dot, rule and
                    count — not a fixed-width gutter column, which left a ragged
                    channel down the middle (ADR-271 §P). */}
                <div className="flex items-center gap-2 mb-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${ROLE_DOT[role] ?? 'bg-primary'}`} />
                  <span className="text-[10px] uppercase tracking-wider font-bold
                                   text-muted-foreground">{role}</span>
                  <span className="flex-1 h-px bg-border" />
                  <span className="text-[10px] font-semibold text-muted-foreground">
                    {names.length}
                  </span>
                </div>
                {/* A GRID, not flex-wrap. Wrapping variable-width pills breaks
                    each row at a different point, so no name lines up with the
                    one above it — the zig-zag the operator flagged. */}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-4 gap-y-1.5">
                  {names.map(n => (
                    <span key={n} className="inline-flex items-center gap-1.5 min-w-0">
                      <span className={`w-6 h-6 rounded-full shrink-0 text-[9px] font-bold
                                        grid place-items-center
                                        ${ROLE_TINT[role] ?? 'bg-primary/15 text-primary'}`}>
                        {n.split(' ').map((x: string) => x[0]).join('').slice(0, 2).toUpperCase()}
                      </span>
                      <span className="text-[11px] text-foreground truncate">{n}</span>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(day.rts_details ?? []).length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
            {/* WHOSE returns. assignment_history reports counts_scope ("truck"
                for driver/captain, "own" otherwise) and the label must honour
                it: a driver's day legitimately lists the WHOLE truck's 144
                returns, which read as personal without this. */}
            {day.counts_scope === 'truck' ? 'Truck returned' : 'You returned'}{' '}
            {day.rts_details.length}
          </p>
          {/* Each return is a CARD with a coloured left edge keyed to the
              reason, not a run of flat text lines: nine identical grey
              paragraphs gave no way to scan for the one that matters. Damage
              is red — it is the reason with consequences (ADR-271 §P). */}
          {/* TWO COLUMNS on desktop. A card uses about a third of the width
              here, so a single column turned a driver's 125 returns into an
              enormous scroll of mostly-empty rows. Still one column on narrow
              viewports, where the card genuinely needs the full width.

              `items-start` matters: without it the grid stretches every card in
              a row to the tallest, so a one-line reason next to a wrapped
              explanation gets padded out. */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-1.5 items-start">
            {day.rts_details.map((r: any) => (
              <div key={r.tba_number}
                   className={`flex gap-2 text-[11px] rounded-r bg-accent/20 px-2 py-1.5
                               border-l-[3px] ${
                     r.rts_type === 'package_damaged' ? 'border-danger'
                     : r.is_reattemptable ? 'border-info' : 'border-warning'}`}>
                <Package className="w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5" />
                <div>
                  <p className="text-foreground font-semibold">
                    {RTS_LABEL[r.rts_type] ?? r.rts_type.replace(/_/g, ' ')}
                    {r.is_reattemptable && (
                      <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-info/10
                                       text-info uppercase tracking-wide">retryable</span>
                    )}
                  </p>
                  {/* THE TBA IS THE PACKAGE'S IDENTITY. It was carried only as
                      a React key, so a return could not be tied to an actual
                      package — the one field that makes the row actionable in
                      a dispute. Monospaced: a TBA is read digit by digit, and
                      a proportional font makes 1/l and 0/O ambiguous. */}
                  <p className="font-mono text-[10px] text-muted-foreground tracking-wide
                                select-all">
                    {r.tba_number}
                  </p>
                  {r.rts_explanation && (
                    <p className="text-muted-foreground italic">{r.rts_explanation}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SUPERVISED TRAINEES (ADR-269). Rendered SEPARATELY from the counts
          above — merging them resurrects the ADR-244 attribution bug, where a
          trainee's returns land on the trainer's own record.

          Nearly LOST in this rewrite: the block lived in RecentDaysSection,
          which ADR-271 absorbed, and the first cut of this drill simply did not
          carry it across. Nothing on web mounts RecentDaysSection any more, so
          the omission would have silently deleted a shipped trainer feature
          rather than failing loudly. `?? []` because the field is optional on
          the wire — a client can outrun the backend serving it. */}
      {(day.supervised ?? []).length > 0 && (
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mt-4 mb-1">
          You supervised · {(day.supervised ?? []).length}
        </p>
      )}
      {(day.supervised ?? []).map((sup: any) => {
        const pct = sup.packages_total
          ? Math.round((sup.packages_delivered / sup.packages_total) * 100) : null;
        return (
          /* A CARD, not a text run. This is the record the trainer answers for
             (ADR-269), so it gets the same weight as their own numbers: an
             identity row, a delivered/total figure with a progress bar, and the
             returns with their TBAs (ADR-271 §P). */
          <div key={sup.employee_id}
               className="rounded-xl border border-border bg-accent/20 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="w-7 h-7 rounded-full bg-success/15 text-success shrink-0
                               text-[10px] font-bold grid place-items-center">
                {sup.name.split(' ').map((x: string) => x[0]).join('').slice(0, 2).toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-bold text-foreground truncate">{sup.name}</p>
                <p className="text-[11px] text-muted-foreground">trainee you supervised</p>
              </div>
              {pct !== null && (
                <span className="text-lg font-bold text-foreground tabular-nums">{pct}%</span>
              )}
            </div>

            <div className="flex items-baseline justify-between">
              <p className="text-[13px] font-bold text-foreground tabular-nums">
                {sup.packages_delivered}
                <span className="font-normal text-muted-foreground">
                  {' / '}{sup.packages_total} delivered
                </span>
              </p>
              {sup.rts_count > 0 && (
                <span className="text-[11px] font-semibold text-warning">
                  {sup.rts_count} RTS
                </span>
              )}
            </div>

            {pct !== null && (
              <div className="h-1.5 rounded-full bg-border overflow-hidden">
                <div className="h-full rounded-full bg-success" style={{ width: `${pct}%` }} />
              </div>
            )}

            {/* Reason AND package: naming only the reason tells the trainer three
                came back but not WHICH three, and the point of the block is that
                they can discuss specific packages with the trainee (ADR-269). */}
            {(sup.rts_details ?? []).map((r: any) => (
              <p key={r.tba_number}
                 className="text-[11px] text-muted-foreground flex items-baseline gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  r.rts_type === 'package_damaged' ? 'bg-danger' : 'bg-warning'}`} />
                <span className="flex-1">
                  {RTS_LABEL[r.rts_type] ?? r.rts_type.replace(/_/g, ' ')}
                </span>
                <span className="font-mono text-[10px] tracking-wide select-all">
                  {r.tba_number}
                </span>
              </p>
            ))}
          </div>
        );
      })}
    </div>
  );
}
