/**
 * DESIGN MOCK — My Stats drill-down (ADR-271). NOT WIRED TO DATA.
 *
 * Exists so the layout can be reviewed and corrected before it is built against
 * the real endpoint and mirrored to mobile. Every number below is fabricated;
 * the shapes, the navigation and the empty/absent states are the real proposal.
 *
 * Delete this file once the wired version lands.
 *
 * Navigation (settled 2026-08-13):
 *   the selector at each level picks the period you want to VIEW; the chart
 *   shows that period broken into its sub-units.
 *
 *     Lifetime → year-over-year,  selector: which year
 *     Year     → month-to-month,  selector: which month
 *     Month    → week-to-week,    selector: which week
 *     Week     → day-to-day,      selector: which day
 *     Day      → truck, crew, delivered, RTS rows (terminal)
 *
 * Trend rule: a delta is shown ONLY where a COMPLETED prior period of the same
 * grain exists. A first year/month/week/day shows figures with no delta —
 * rendering a neutral arrow would imply "no change" where the truth is
 * "nothing to compare".
 */
import { useState } from 'react';
import {
  ChevronLeft, ChevronRight, ChevronUp, TrendingUp, TrendingDown, Truck, Package,
} from 'lucide-react';

type Grain = 'lifetime' | 'year' | 'month' | 'week' | 'day';

type Bucket = {
  key: string;
  label: string;
  /** Compact form for the sibling arrows. "Aug 9–15" is too wide for a
   *  right-aligned prev/next pair, so weeks carry "W2", days carry "Sun". */
  short?: string;
  delivered: number;
  rts: number;
  damaged: number;
  missing: number;
  effort?: 'easy' | 'standard' | 'heavy';
  /** null = no completed prior period to compare against. */
  trend: number | null;
};

// ── fabricated data ─────────────────────────────────────────────────────────
//
// DELIBERATELY UNEVEN. An earlier version used near-identical values at every
// level, which made the drill-down look pointless — you cannot see a trend in a
// flat line. Real delivery data has bad weeks, seasonal peaks and days off, so
// the mock carries the same spread: a weak first year, a December peak, a slump
// in February, and days that swing 60-140.

const YEARS: Bucket[] = [
  { key: '2024', label: '2024', delivered: 9840,  rts: 612, damaged: 71, missing: 28, trend: null },
  { key: '2025', label: '2025', delivered: 24107, rts: 812, damaged: 64, missing: 22, trend: 145.0 },
  { key: '2026', label: '2026', delivered: 14733, rts: 498, damaged: 39, missing: 11, trend: null },
];

// A ramp, a summer dip, a December spike — not twelve equal bars.
const MONTHS: Bucket[] = [
  { key: 'jan', label: 'Jan', delivered: 1640, rts: 88,  damaged: 9, missing: 4, trend: null },
  { key: 'feb', label: 'Feb', delivered: 1105, rts: 61,  damaged: 4, missing: 1, trend: -32.6 },
  { key: 'mar', label: 'Mar', delivered: 2210, rts: 80,  damaged: 7, missing: 3, trend: 100.0 },
  { key: 'apr', label: 'Apr', delivered: 2380, rts: 66,  damaged: 5, missing: 1, trend: 7.7 },
  { key: 'may', label: 'May', delivered: 1890, rts: 71,  damaged: 6, missing: 2, trend: -20.6 },
  { key: 'jun', label: 'Jun', delivered: 1204, rts: 43,  damaged: 3, missing: 0, trend: -36.3 },
  { key: 'jul', label: 'Jul', delivered: 2264, rts: 88,  damaged: 8, missing: 2, trend: 88.0 },
  { key: 'aug', label: 'Aug', delivered: 2980, rts: 102, damaged: 11, missing: 5, trend: 31.6 },
  { key: 'sep', label: 'Sep', delivered: 2110, rts: 74,  damaged: 5, missing: 1, trend: -29.2 },
  { key: 'oct', label: 'Oct', delivered: 2455, rts: 69,  damaged: 4, missing: 2, trend: 16.4 },
  { key: 'nov', label: 'Nov', delivered: 1820, rts: 58,  damaged: 2, missing: 0, trend: -25.9 },
  { key: 'dec', label: 'Dec', delivered: 3249, rts: 121, damaged: 14, missing: 6, trend: 78.5 },
];

const WEEKS: Bucket[] = [
  { key: 'w1', label: 'Aug 2–8',   short: 'W1', delivered: 742, rts: 31, damaged: 3, missing: 1, trend: 12.4 },
  { key: 'w2', label: 'Aug 9–15',  short: 'W2', delivered: 588, rts: 21, damaged: 1, missing: 1, trend: -20.8 },
  { key: 'w3', label: 'Aug 16–22', short: 'W3', delivered: 905, rts: 38, damaged: 5, missing: 2, trend: 53.9 },
  { key: 'w4', label: 'Aug 23–29', short: 'W4', delivered: 401, rts: 12, damaged: 0, missing: 0, trend: -55.7 },
];

// Day labels carry the DATE, not a bare letter: "S M T W T F S" repeats two
// letters and tells the reader nothing about which week they are in.
// Sunday off, a light Tuesday, a heavy Friday — the shape of a real week.
const DAYS: Bucket[] = [
  { key: 'd0', label: 'Sun 9',  short: 'Sun', delivered: 0,   rts: 0, damaged: 0, missing: 0, trend: null },
  { key: 'd1', label: 'Mon 10', short: 'Mon', delivered: 118, rts: 4, damaged: 0, missing: 0, effort: 'heavy',    trend: 9.2 },
  { key: 'd2', label: 'Tue 11', short: 'Tue', delivered: 64,  rts: 9, damaged: 2, missing: 1, effort: 'standard', trend: -45.8 },
  { key: 'd3', label: 'Wed 12', short: 'Wed', delivered: 131, rts: 5, damaged: 0, missing: 1, effort: 'heavy',    trend: 104.7 },
  { key: 'd4', label: 'Thu 13', short: 'Thu', delivered: 97,  rts: 6, damaged: 1, missing: 0, effort: 'standard', trend: -26.0 },
  // Fri 14 is TODAY and Sat 15 is the future. The series excludes today
  // (ADR-271 C), so both are empty and the entry point is Thu 13 — the most
  // recent day that actually has data.
  { key: 'd5', label: 'Fri 14', short: 'Fri', delivered: 0,   rts: 0, damaged: 0, missing: 0, trend: null },
  { key: 'd6', label: 'Sat 15', short: 'Sat', delivered: 0,   rts: 0, damaged: 0, missing: 0, trend: null },
];

const REASONS = [
  { label: 'No access',          n: 8,  cls: 'stroke-info' },
  { label: 'Customer cancelled', n: 6,  cls: 'stroke-warning' },
  { label: 'Business closed',    n: 4,  cls: 'stroke-success' },
  { label: 'Damaged',            n: 2,  cls: 'stroke-danger' },
  { label: 'Other',              n: 1,  cls: 'stroke-muted-foreground' },
];

const EFFORT_BG: Record<string, string> = {
  easy: 'bg-info', standard: 'bg-success', heavy: 'bg-warning',
};

// ── pieces ──────────────────────────────────────────────────────────────────

/** A delta, or NOTHING when there is no completed prior period. Deliberately
 *  renders null rather than a neutral arrow: "nothing to compare" and "no
 *  change" are different facts. */
function Trend({ pct }: { pct: number | null }) {
  if (pct === null) return null;
  const up = pct >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[11px] font-semibold ${
      up ? 'text-success' : 'text-danger'}`}>
      <Icon className="w-3 h-3" />{Math.abs(pct).toFixed(1)}%
    </span>
  );
}

function Figures({ b }: { b: Bucket }) {
  const attempted = b.delivered + b.rts + b.missing;
  const success = attempted ? (b.delivered / attempted) * 100 : null;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
      {/* Delivered carries the weight — it is the number the page is about, and
          the top-left position gets the most attention. The three failure modes
          are grouped to its right so they read as one family. */}
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
          { label: 'RTS',     v: b.rts,     tone: 'text-warning' },
          { label: 'Damaged', v: b.damaged, tone: 'text-danger' },
          { label: 'Missing', v: b.missing, tone: 'text-danger' },
        ].map(i => (
          <div key={i.label} className="rounded-xl bg-accent/25 p-3 flex flex-col justify-center">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{i.label}</p>
            <p className={`text-xl font-bold tabular-nums ${i.tone}`}>
              {i.v.toLocaleString()}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Bars. Colour encodes difficulty where a bucket has one (day level); other
 *  levels mix efforts, so they stay neutral rather than implying a class. */
function Bars({ data, onPick }: { data: Bucket[]; onPick: (b: Bucket) => void }) {
  const max = Math.max(1, ...data.map(d => d.delivered));
  if (!data.some(d => d.delivered > 0)) {
    return (
      <p className="text-[11px] text-muted-foreground italic text-center py-8">
        No packages delivered in this period.
      </p>
    );
  }
  return (
    <div>
      {/* Full width, not max-w-md: a chart floating in the left third of a wide
          card wastes the space and reads as unfinished. */}
      <div className="flex items-end gap-3 h-48 border-b border-border pb-0">
        {data.map(d => {
          const pct = (d.delivered / max) * 100;
          const empty = d.delivered === 0;
          return (
            <button
              key={d.key}
              onClick={() => !empty && onPick(d)}
              disabled={empty}
              className="flex-1 h-full flex flex-col justify-end items-center gap-1
                         group disabled:cursor-default"
              title={`${d.label}: ${d.delivered.toLocaleString()} delivered`}
            >
              {/* Value above the bar — reading a number off an axis is work the
                  chart can do for you. */}
              <span className={`text-[10px] tabular-nums transition-colors ${
                empty ? 'text-transparent'
                      : 'text-muted-foreground group-hover:text-foreground'}`}>
                {d.delivered > 0 ? d.delivered.toLocaleString() : ''}
              </span>
              {empty ? (
                <div className="w-full h-[2px] bg-border rounded-full" />
              ) : (
                <div
                  className={`w-full rounded-t-md transition-all
                              ${d.effort ? EFFORT_BG[d.effort] : 'bg-primary'}
                              opacity-85 group-hover:opacity-100`}
                  style={{ height: `${Math.max(4, pct)}%` }}
                />
              )}
            </button>
          );
        })}
      </div>
      <div className="flex gap-3 mt-2">
        {data.map(d => (
          <span key={d.key} className="flex-1 text-center text-[11px] text-muted-foreground">
            {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Donut via stroke-dasharray — one circle per segment, no path math. Capped at
 *  top 4 + Other (ADR-271 G).
 *
 *  Sized to match the bar chart above it: a small donut floating beside a
 *  narrow legend reads as an afterthought next to a full-width chart. The two
 *  halves split the card evenly so the section carries the same weight as the
 *  one above.
 */
function ReasonDonut() {
  const total = REASONS.reduce((n, r) => n + r.n, 0);
  let offset = 25;   // start at 12 o'clock
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-center">
      <div className="flex justify-center">
        <svg viewBox="0 0 42 42" className="w-72 h-72 max-w-full">
          <circle cx="21" cy="21" r="15.9" fill="none" className="stroke-border"
                  strokeWidth="6" />
          {REASONS.map(r => {
            const pct = (r.n / total) * 100;
            const el = (
              <circle key={r.label} cx="21" cy="21" r="15.9" fill="none"
                      className={`${r.cls} transition-all`} strokeWidth="6"
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

      {/* Rows, not a cramped list: each reason gets its own bar so the
          proportions are readable without tracing colours back to the ring. */}
      <ul className="space-y-3.5">
        {REASONS.map(r => {
          const pct = (r.n / total) * 100;
          return (
            <li key={r.label}>
              <div className="flex items-baseline gap-2 mb-1">
                <span className={`w-2.5 h-2.5 rounded-sm shrink-0
                                  ${r.cls.replace('stroke-', 'bg-')}`} />
                <span className="text-[15px] text-foreground flex-1">{r.label}</span>
                <span className="text-[15px] font-semibold text-foreground tabular-nums">
                  {r.n}
                </span>
                <span className="text-xs text-muted-foreground tabular-nums w-10 text-right">
                  {Math.round(pct)}%
                </span>
              </div>
              <div className="h-2 rounded-full bg-accent/40 overflow-hidden">
                <div className={`h-full rounded-full ${r.cls.replace('stroke-', 'bg-')}`}
                     style={{ width: `${pct}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function DayDetail() {
  // NOTE: no <Figures> here — the level header above already renders them for
  // the current cursor. Duplicating produced two stat rows on the day view.
  const crew = [
    { role: 'Driver',   names: ['Driver Test'] },
    { role: 'Captain',  names: ['Marcus Vane'] },
    { role: 'Trainer',  names: ['Trainer One', 'Tanya Griffith'] },
    { role: 'Walkers',  names: ['Walker Test', 'Omar Khalil', 'Carla Reyes', 'Nia Bennett'] },
    { role: 'Trainees', names: ['Trainee Test'] },
  ];
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground
                         border border-border rounded-lg px-2 py-1">
          <Truck className="w-3.5 h-3.5" /> Atlas
        </span>
        <span className="text-[10px] px-2 py-0.5 rounded uppercase tracking-wide font-bold
                         bg-warning/15 text-warning">heavy</span>
      </div>

      {/* Crew: grouped by role with initials, not a comma-joined string that
          could not answer "who was driving". */}
      <div>
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Crew</p>
        <div className="space-y-2">
          {crew.map(g => (
            <div key={g.role} className="flex gap-3 items-start">
              <span className="w-16 shrink-0 text-[10px] uppercase tracking-wide font-bold
                               text-muted-foreground pt-1.5">{g.role}</span>
              <div className="flex flex-wrap gap-1.5">
                {g.names.map(n => (
                  <span key={n} className="inline-flex items-center gap-1.5 rounded-full
                                           bg-accent/30 pl-1 pr-2.5 py-0.5">
                    <span className="w-5 h-5 rounded-full bg-primary/20 text-primary
                                     text-[9px] font-bold grid place-items-center">
                      {n.split(' ').map(x => x[0]).join('').slice(0, 2)}
                    </span>
                    <span className="text-[11px] text-foreground">{n}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
          Returned 5
        </p>
        <div className="space-y-1.5">
          {[
            ['No access', 'Gate code did not work, no answer on buzzer.', true],
            ['Customer cancelled', 'Customer cancelled at the door.', false],
            ['Business closed', 'Business shut when attempted, no safe drop.', true],
          ].map(([t, why, retry]) => (
            <div key={t as string} className="flex gap-2 text-[11px]">
              <Package className="w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5" />
              <div>
                <p className="text-foreground">
                  {t}
                  {retry && (
                    <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-info/10
                                     text-info uppercase tracking-wide">retryable</span>
                  )}
                </p>
                <p className="text-muted-foreground italic">{why}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── the drill ───────────────────────────────────────────────────────────────

export default function StatsDrillMock() {
  // ZOOM-OUT model (ADR-271, revised).
  //
  // The drill now STARTS at the most recent worked day and expands outward:
  //
  //     Day  ->  Week  ->  Month  ->  Year  ->  Lifetime
  //
  // Analyst tools drill INWARD from an aggregate because they are hunting an
  // anomaly nobody has spotted yet (Hex, Bold BI). Personal-stats apps expand
  // OUTWARD from today because the user already knows what they are asking —
  // "how did I do, and is that normal for me?" (Apple Fitness, FitnessView).
  // My Stats is the second kind, and the old model made a walker click four
  // times to reach the day they actually worked.
  //
  // Entry is the most recent day WITH DATA, not literally yesterday: someone
  // who was off yesterday would otherwise land on an empty screen.
  const lastWorked = [...DAYS].reverse().find(d => d.delivered > 0) ?? DAYS[0];
  const isLastShift = (b: Bucket) => b.key === lastWorked.key;

  const [level, setLevel] = useState<Grain>('day');
  const [cursor, setCursor] = useState<Bucket>(lastWorked);

  const dataFor: Record<Grain, Bucket[]> = {
    day: DAYS, week: DAYS, month: WEEKS, year: MONTHS, lifetime: YEARS,
  };
  // Zooming OUT: each level's parent.
  const outer: Record<Grain, Grain | null> = {
    day: 'week', week: 'month', month: 'year', year: 'lifetime', lifetime: null,
  };
  const outerLabel: Record<Grain, string> = {
    day: 'This week', week: 'August', month: '2026', year: 'Lifetime', lifetime: '',
  };
  const levelName: Record<Grain, string> = {
    day: 'Day', week: 'Week', month: 'Month', year: 'Year', lifetime: 'Lifetime',
  };

  // Siblings of the CURRENT cursor, for lateral movement.
  const siblings = level === 'day' ? DAYS
                 : level === 'week' ? WEEKS
                 : level === 'month' ? MONTHS
                 : level === 'year' ? YEARS : [];
  const idx = siblings.findIndex(b => b.key === cursor.key);
  const prev = idx > 0 ? siblings[idx - 1] : null;
  const next = idx >= 0 && idx < siblings.length - 1 ? siblings[idx + 1] : null;

  // The buckets CHARTED at this level = its sub-units.
  const charted = level === 'day' ? []
                : level === 'week' ? DAYS
                : level === 'month' ? WEEKS
                : level === 'year' ? MONTHS : YEARS;

  const agg: Bucket = level === 'day' ? cursor : {
    key: 'agg', label: cursor.label, trend: cursor.trend,
    delivered: charted.reduce((n, b) => n + b.delivered, 0),
    rts: charted.reduce((n, b) => n + b.rts, 0),
    damaged: charted.reduce((n, b) => n + b.damaged, 0),
    missing: charted.reduce((n, b) => n + b.missing, 0),
  };

  // Zoom-out trail, innermost first. Disabled where there is nothing to see:
  // a level with no data is not worth a click, and an enabled control that
  // leads to an empty screen is worse than an absent one.
  const trail: { grain: Grain; label: string; enabled: boolean }[] = [];
  let g: Grain | null = outer[level];
  while (g) {
    const has = (dataFor[g] ?? []).some(b => b.delivered > 0);
    trail.push({ grain: g, label: outerLabel[level === 'day' && g === 'week'
      ? 'day' : Object.keys(outer).find(k => outer[k as Grain] === g) as Grain] ?? levelName[g],
      enabled: has });
    g = outer[g];
  }

  const zoomOut = (to: Grain) => {
    setLevel(to);
    const pool = to === 'week' ? WEEKS : to === 'month' ? MONTHS
               : to === 'year' ? YEARS : [];
    if (pool.length) setCursor(pool[pool.length - 1]);
  };

  const zoomIn = (b: Bucket) => {
    const inner: Record<Grain, Grain | null> = {
      lifetime: 'year', year: 'month', month: 'week', week: 'day', day: null,
    };
    const to = inner[level];
    if (!to || b.delivered === 0) return;
    setLevel(to);
    setCursor(b);
  };

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-warning/40 bg-warning/10 px-3 py-2">
        <p className="text-xs text-warning font-semibold">
          DESIGN MOCK — fabricated numbers, not wired to the API.
        </p>
      </div>

      {/* LIFETIME HEADER — always visible, never changes with the drill. */}
      <div className="card">
        <div className="flex items-baseline gap-2 mb-3">
          <h2 className="section-title">Lifetime</h2>
          <span className="text-[11px] text-muted-foreground">all time</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            ['Delivered', '55,260'], ['Success', '96.8%'],
            ['Rating', '4.6★'], ['Trips', '742'],
          ].map(([l, v]) => (
            <div key={l} className="rounded-lg border border-border bg-background p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{l}</p>
              <p className="text-xl font-bold text-foreground tabular-nums">{v}</p>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3 mt-3">
          {[['RTS', '2,251'], ['Missing', '64'], ['Damaged', '191']].map(([l, v]) => (
            <div key={l} className="rounded-lg bg-accent/20 p-2.5">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{l}</p>
              <p className="text-base font-bold text-foreground tabular-nums">{v}</p>
            </div>
          ))}
        </div>
      </div>

      {/* THE DRILL — zoom OUT from the most recent worked day */}
      <div className="card space-y-4">
        {/* Zoom-out trail left, siblings right. Disabled where a level has no
            data: zooming out to an empty screen is worse than no control. */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1.5 flex-wrap text-sm">
            <span className="font-bold text-foreground">{cursor.label}</span>
            {trail.map(t => (
              <button
                key={t.grain}
                onClick={() => t.enabled && zoomOut(t.grain)}
                disabled={!t.enabled}
                title={t.enabled ? `Zoom out to ${levelName[t.grain].toLowerCase()}`
                                 : 'No data at this level yet'}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg
                           text-xs text-primary hover:bg-accent/40
                           disabled:opacity-30 disabled:text-muted-foreground
                           disabled:hover:bg-transparent transition-colors"
              >
                <ChevronUp className="w-3 h-3" />{levelName[t.grain]}
              </button>
            ))}
          </div>

          {siblings.length > 1 && (
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={() => prev && setCursor(prev)}
                disabled={!prev}
                style={{ visibility: prev ? 'visible' : 'hidden' }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs
                           text-foreground hover:bg-accent/40 disabled:opacity-30
                           disabled:hover:bg-transparent transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                {prev ? (prev.short ?? prev.label) : ''}
              </button>
              <button
                onClick={() => next && setCursor(next)}
                disabled={!next}
                style={{ visibility: next ? 'visible' : 'hidden' }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs
                           text-foreground hover:bg-accent/40 disabled:opacity-30
                           disabled:hover:bg-transparent transition-colors"
              >
                {next ? (next.short ?? next.label) : ''}
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        <div className="flex items-baseline gap-2">
          <h3 className="text-lg font-bold text-foreground">
            {level === 'day' ? cursor.label : `${levelName[level]} · ${cursor.label}`}
          </h3>
          {level === 'day' && isLastShift(cursor) && (
            /* Landing on a date with no explanation reads as arbitrary. */
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-accent/40
                             text-muted-foreground">your last shift</span>
          )}
          <Trend pct={agg.trend} />
          {agg.trend === null && (
            <span className="text-[11px] text-muted-foreground">
              no earlier {levelName[level].toLowerCase()} to compare
            </span>
          )}
        </div>

        <Figures b={agg} />

        {level === 'day' ? (
          <DayDetail />
        ) : (
          <>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
                Delivered by {level === 'week' ? 'day' : level === 'month' ? 'week'
                              : level === 'year' ? 'month' : 'year'}
                <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/70">
                  — click a bar to zoom in
                </span>
              </p>
              <Bars data={charted} onPick={zoomIn} />
            </div>

            <div className="pt-5 mt-1 border-t border-border">
              <div className="flex items-baseline gap-2 mb-4">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Why packages came back
                </p>
                <span className="text-[11px] text-muted-foreground/70">{cursor.label}</span>
              </div>
              <ReasonDonut />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
