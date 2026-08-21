/**
 * Client-side aggregation for the My Stats drill-down (ADR-271 B).
 *
 * The server sends ONE immutable daily series capped at 24 months; year, month
 * and week are all groupings of the same rows, so there is no reason to ask it
 * four times for four views of one dataset. Measured: 114 bytes/day, ~58 KB for
 * the full window, against 71.5 KB for a SINGLE year of the full history
 * payload.
 *
 * The cost of that choice is this file: aggregation now lives on the client and
 * must be kept identical between web and mobile. Any change here lands on both
 * in the same commit — the same rule ADR-269 set for the supervised block.
 *
 * Dates are handled as LOCAL Y/M/D throughout. `new Date('2026-08-07')` is
 * midnight UTC and lands on the 6th in any timezone behind it, which would put
 * a day in the wrong week and silently shift every bucket.
 */
import type { DayStat, YearStat } from '../../api/types';

export type Grain = 'day' | 'week' | 'month' | 'year' | 'lifetime';

export interface Bucket {
  key: string;
  label: string;
  /** Compact form for the sibling arrows — "W2", "Tue". A full "Aug 9–15" pair
   *  is too wide for a right-aligned prev/next. */
  short: string;
  start: string;          // inclusive, YYYY-MM-DD
  end: string;            // inclusive
  delivered: number;
  total: number;
  rts: number;
  damaged: number;
  truckDamaged: number;
  missing: number;
  /** Only meaningful at day grain; coarser buckets mix efforts. */
  effort: string | null;
  /** % change in delivered against the previous bucket of the SAME grain.
   *  Null where there is no completed prior bucket — a first year/month/week/
   *  day shows figures with NO delta. Rendering a neutral arrow would imply
   *  "no change" where the truth is "nothing to compare" (ADR-271 D3). */
  trend: number | null;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Parse YYYY-MM-DD as a LOCAL date. */
export function parseYMD(s: string): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function ymd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function sundayOf(d: Date): Date {
  const s = new Date(d);
  s.setDate(d.getDate() - d.getDay());
  return s;
}

function empty(key: string, label: string, short: string,
               start: string, end: string): Bucket {
  return { key, label, short, start, end, delivered: 0, total: 0, rts: 0,
           damaged: 0, truckDamaged: 0, missing: 0, effort: null, trend: null };
}

function add(b: Bucket, d: DayStat): void {
  b.delivered += d.delivered;
  b.total += d.total;
  b.rts += d.rts;
  b.damaged += d.damaged;
  b.truckDamaged += d.truck_damaged;
  b.missing += d.missing;
}

/**
 * Attach a trend to each bucket, comparing against its immediate predecessor.
 *
 * TWO conditions, both required (ADR-271 D3):
 *   1. a PRIOR bucket must exist — the first one has nothing to compare to
 *   2. the prior bucket must have delivered something — dividing by zero, or
 *      reporting "+infinity% since last month", is not a trend
 *
 * `buckets` must already be in chronological order.
 */
function withTrends(buckets: Bucket[]): Bucket[] {
  return buckets.map((b, i) => {
    if (i === 0) return b;                       // nothing before it
    const prev = buckets[i - 1];
    if (prev.delivered === 0) return b;          // no baseline to divide by
    return { ...b, trend: ((b.delivered - prev.delivered) / prev.delivered) * 100 };
  });
}

/** Days of one week, Sunday-anchored, INCLUDING days not worked.
 *  A gap is information ("you did not work Tuesday"); dropping the slot would
 *  silently reflow the week. */
export function daysOfWeek(days: DayStat[], weekStart: Date): Bucket[] {
  const byDate = new Map(days.map(d => [d.d, d]));
  const out: Bucket[] = [];
  for (let i = 0; i < 7; i++) {
    const dt = new Date(weekStart);
    dt.setDate(weekStart.getDate() + i);
    const key = ymd(dt);
    const b = empty(key, `${DOW[dt.getDay()]} ${dt.getDate()}`,
                    DOW[dt.getDay()], key, key);
    const day = byDate.get(key);
    if (day) { add(b, day); b.effort = day.effort; }
    out.push(b);
  }
  return withTrends(out);
}

/** Sunday-anchored weeks overlapping one month. */
export function weeksOfMonth(days: DayStat[], year: number, month: number): Bucket[] {
  const first = new Date(year, month, 1);
  const last = new Date(year, month + 1, 0);
  const buckets: Bucket[] = [];
  let cur = sundayOf(first);
  let n = 1;
  while (cur <= last) {
    const end = new Date(cur);
    end.setDate(cur.getDate() + 6);
    const b = empty(ymd(cur),
                    `${MONTHS[cur.getMonth()]} ${cur.getDate()}–${MONTHS[end.getMonth()]} ${end.getDate()}`,
                    `W${n}`, ymd(cur), ymd(end));
    for (const d of days) {
      const dt = parseYMD(d.d);
      if (dt >= cur && dt <= end) add(b, d);
    }
    buckets.push(b);
    cur = new Date(cur); cur.setDate(cur.getDate() + 7); n++;
  }
  return withTrends(buckets);
}

/** All twelve months of a year, so a chart has a stable shape. */
export function monthsOfYear(days: DayStat[], year: number): Bucket[] {
  const buckets = MONTHS.map((label, m) => {
    const start = new Date(year, m, 1);
    const end = new Date(year, m + 1, 0);
    return empty(`${year}-${String(m + 1).padStart(2, '0')}`,
                 label, label, ymd(start), ymd(end));
  });
  for (const d of days) {
    const dt = parseYMD(d.d);
    if (dt.getFullYear() === year) add(buckets[dt.getMonth()], d);
  }
  return withTrends(buckets);
}

/** Years come from the server, NOT from the daily series: that series is capped
 *  at 24 months, so folding it would silently drop a long-tenured employee's
 *  early years (ADR-271 D2). */
export function yearsFrom(years: YearStat[]): Bucket[] {
  const buckets = years.map(y => ({
    ...empty(String(y.year), String(y.year), String(y.year),
             `${y.year}-01-01`, `${y.year}-12-31`),
    delivered: y.delivered, total: y.total, rts: y.rts,
    damaged: y.damaged, truckDamaged: y.truck_damaged, missing: y.missing,
  }));
  return withTrends(buckets);
}

/** The most recent day WITH DATA — not literally yesterday, since someone who
 *  was off would land on an empty screen (ADR-271, revised entry point). */
export function lastWorkedDay(days: DayStat[]): DayStat | null {
  for (let i = days.length - 1; i >= 0; i--) {
    if (days[i].delivered > 0 || days[i].rts > 0) return days[i];
  }
  return days.length ? days[days.length - 1] : null;
}

/** Expand the abbreviated reason keys the wire uses back to rts_type. */
const REASON_FULL: Record<string, string> = {
  na: 'no_access',
  bc: 'business_closed',
  pd: 'package_damaged',
  iw: 'inclement_weather',
  cr: 'customer_requested_future_delivery',
  cc: 'customer_cancelled_order',
};

/** Reason mix for a date range, derived ENTIRELY from the cached series.
 *
 *  This is the bulk-fetch design working as intended (ADR-271 B): the per-day
 *  `rz` map ships once, and every level's donut is a sum over it. No request,
 *  no per-period endpoint, no cache to invalidate.
 *
 *  Measured before choosing this: reasons cost 7.1 KB across two years, so
 *  folding them in was cheap. Per-day BLOCKS were 141 KB, which is why those
 *  alone remain an on-demand fetch.
 */
export function reasonsIn(days: DayStat[], start: string, end: string):
    { rts_type: string; count: number }[] {
  const acc = new Map<string, number>();
  for (const d of days) {
    if (d.d < start || d.d > end) continue;
    for (const [k, n] of Object.entries(d.rz ?? {})) {
      const full = REASON_FULL[k] ?? k;
      acc.set(full, (acc.get(full) ?? 0) + n);
    }
  }
  return [...acc.entries()]
    .map(([rts_type, count]) => ({ rts_type, count }))
    .sort((a, b) => b.count - a.count);
}

/** Attendance for a date range, derived from the cached series.
 *
 *  `rate` is null — never 0 — when nothing was recorded: "no roll calls" and
 *  "0% attendance" are different facts.
 */
export function attendanceIn(days: DayStat[], start: string, end: string):
    { present: number; late: number; ncns: number; total: number; rate: number | null } {
  let present = 0, late = 0, ncns = 0;
  for (const d of days) {
    if (d.d < start || d.d > end || !d.rc) continue;
    if (d.rc === 'ncns') ncns++;
    else if (d.rc === 'late') late++;
    else present++;
  }
  const total = present + late + ncns;
  return { present, late, ncns, total,
           rate: total ? Math.round((present / total) * 1000) / 10 : null };
}
