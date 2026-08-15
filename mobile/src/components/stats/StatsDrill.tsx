/**
 * My Stats drill-down — MOBILE (ADR-271). Mirror of
 * `frontend/src/components/stats/StatsDrill.tsx`.
 *
 * ZOOM OUT, not in. Entry is the most recent day WITH DATA; the user expands to
 * week, month, year, lifetime. Analyst tools drill inward from an aggregate
 * because they are hunting an anomaly nobody has spotted; personal-stats apps
 * expand outward because the user already knows what they are asking — "how did
 * I do, and is that normal for me?".
 *
 * ONE request drives every level: /me/stats returns an immutable daily series
 * (ends yesterday) that `aggregate.ts` buckets on device. Reasons and
 * attendance ride in that payload; only top BLOCKS still need the network
 * (141 KB across two years, against 7.1 KB for reasons).
 *
 * PARITY: the aggregation module is a verbatim copy of the web one and the two
 * must change together. This file is a native re-render of the same model, not
 * a copy — Tailwind classes become StyleSheet, the SVG donut becomes
 * react-native-svg, and touch targets are sized for a thumb in a van.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, ActivityIndicator, StyleSheet,
  Platform,
} from 'react-native';
import Svg, { Circle, Line, Polyline, Text as SvgText } from 'react-native-svg';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import {
  attendanceIn, daysOfWeek, monthsOfYear, reasonsIn, weeksOfMonth, yearsFrom,
  lastWorkedDay, parseYMD, type Bucket, type Grain,
} from './aggregate';
import type { AssignmentDay, MyStats, PeriodExtras } from './types';
import { groupCrew, roleTone } from './crew';

const LEVEL_NAME: Record<Grain, string> = {
  day: 'Day', week: 'Week', month: 'Month', year: 'Year', lifetime: 'Lifetime',
};

const RTS_LABEL: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Customer rescheduled',
  customer_cancelled_order: 'Customer cancelled',
};



/** Module-level so it survives remounts: the day detail unmounts every time the
 *  user zooms out and remounts when they return, which would otherwise
 *  re-request a day that ended yesterday and can never change. */
const dayCache = new Map<string, AssignmentDay | null>();

function initials(name: string): string {
  return name.split(' ').map(x => x[0]).join('').slice(0, 2).toUpperCase();
}

export default function StatsDrill() {
  const c = useColors();
  const s = styles(c);

  const [stats, setStats] = useState<MyStats | null>(null);
  const [extras, setExtras] = useState<PeriodExtras | null>(null);
  const [level, setLevel] = useState<Grain>('day');
  const [cursor, setCursor] = useState<Bucket | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.get<MyStats>('/assignment-history/me/stats')
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
    const dt = parseYMD(d.d);
    const weekStart = new Date(dt);
    weekStart.setDate(dt.getDate() - dt.getDay());
    return daysOfWeek(days, weekStart).find(b => b.key === d.d) ?? null;
  }, [days]);

  useEffect(() => { if (entry && !cursor) setCursor(entry); }, [entry, cursor]);

  const { siblings, charted } = useMemo(() => {
    if (!cursor || !stats) return { siblings: [] as Bucket[], charted: [] as Bucket[] };
    const dt = parseYMD(cursor.start);
    const weekStart = new Date(dt);
    weekStart.setDate(dt.getDate() - dt.getDay());
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

  // CACHED FOR THE SESSION. Every period this can be asked about ended
  // yesterday or earlier — the series never includes today — so the answer is
  // IMMUTABLE and re-requesting it on every navigation is pure latency.
  const extrasCache = useRef<Map<string, PeriodExtras>>(new Map());

  const fetchExtras = useCallback((b: Bucket) => {
    const key = `${b.start}:${b.end}`;
    const hit = extrasCache.current.get(key);
    if (hit) { setExtras(hit); return; }            // no request at all
    apiClient.get<PeriodExtras>('/assignment-history/me/stats/period',
      { params: { start_date: b.start, end_date: b.end } })
      .then(({ data }) => { extrasCache.current.set(key, data); setExtras(data); })
      .catch(() => setExtras(null));
  }, []);

  // Blocks alone still need the network. Reasons and attendance are computed
  // from the series already in memory.
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

  if (loading) {
    return <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.lg }} />;
  }
  if (!stats || !cursor) {
    return (
      <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
        <Text style={[s.muted, { color: c.mutedForeground }]}>
          No completed work recorded yet. Your stats will appear after your first shift.
        </Text>
      </View>
    );
  }

  const lt = stats.lifetime;
  const idx = siblings.findIndex(b => b.key === cursor.key);
  const prev = idx > 0 ? siblings[idx - 1] : null;
  const next = idx >= 0 && idx < siblings.length - 1 ? siblings[idx + 1] : null;

  const outer: Record<Grain, Grain | null> = {
    day: 'week', week: 'month', month: 'year', year: 'lifetime', lifetime: null,
  };
  const trail: { grain: Grain; enabled: boolean }[] = [];
  let g = outer[level];
  while (g) {
    trail.push({ grain: g, enabled: g === 'lifetime' ? stats.years.length > 0 : days.length > 0 });
    g = outer[g];
  }

  const zoomOut = (to: Grain) => {
    setLevel(to);
    const dt = parseYMD(cursor.start);
    if (to === 'week') {
      const st = new Date(dt); st.setDate(dt.getDate() - dt.getDay());
      const wk = weeksOfMonth(days, st.getFullYear(), st.getMonth());
      setCursor(wk.find(b => parseYMD(b.start) <= dt && parseYMD(b.end) >= dt) ?? wk[0]);
    } else if (to === 'month') {
      setCursor(monthsOfYear(days, dt.getFullYear())[dt.getMonth()]);
    } else if (to === 'year') {
      const ys = yearsFrom(stats.years);
      setCursor(ys.find(b => b.key === String(dt.getFullYear())) ?? ys[ys.length - 1]);
    } else {
      const ys = yearsFrom(stats.years);
      setCursor({ ...(ys[ys.length - 1] ?? cursor), key: 'lifetime', label: 'Lifetime',
                  short: 'All', delivered: lt.delivered, rts: lt.rts,
                  damaged: lt.damaged, truckDamaged: lt.truck_damaged,
                  missing: lt.missing, total: 0, effort: null, trend: null });
    }
  };

  const zoomIn = (b: Bucket) => {
    const inner: Record<Grain, Grain | null> = {
      lifetime: 'year', year: 'month', month: 'week', week: 'day', day: null,
    };
    const to = inner[level];
    if (to) { setLevel(to); setCursor(b); }
  };

  const isEntry = !!entry && cursor.key === entry.key && level === 'day';
  // Three states, not one: a section that silently vanishes reads as broken.
  const neverLoaded = cursor.total === 0 && cursor.delivered === 0 && cursor.rts === 0;

  return (
    <ScrollView contentContainerStyle={s.wrap}>
      {/* LIFETIME HEADER — always visible, never changes with the drill. */}
      <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
        <Text style={[s.cardTitle, { color: c.foreground }]}>Lifetime</Text>
        <Text style={[s.cardHint, { color: c.mutedForeground }]}>all time</Text>
        <View style={s.tileRow}>
          {([
            ['Delivered', lt.delivered.toLocaleString()],
            ['Success', lt.success_pct !== null ? `${lt.success_pct}%` : '—'],
            // TRIPS is a walker's measure. A driver or captain runs the TRUCK,
            // not their own routes, so they get RTS in that slot instead — a
            // number they do answer for.
            truckScoped ? ['RTS', lt.rts.toLocaleString()]
                        : ['Trips', lt.trips.toLocaleString()],
            [truckScoped ? 'Truck damage' : 'Damaged',
             (truckScoped ? lt.truck_damaged : lt.damaged).toLocaleString()],
          ] as [string, string][]).map(([l, v]) => (
            <View key={l} style={[s.tile, { backgroundColor: c.background, borderColor: c.border }]}>
              <Text style={[s.tileLabel, { color: c.mutedForeground }]}>{l}</Text>
              <Text style={[s.tileValue, { color: c.foreground }]}>{v}</Text>
            </View>
          ))}
        </View>
      </View>

      {/* THE DRILL */}
      <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
        {/* Zoom-out trail. Disabled where nothing is there: zooming out to an
            empty screen is worse than having no control. */}
        <View style={s.trailRow}>
          {trail.map(t => (
            <TouchableOpacity
              key={t.grain}
              onPress={() => t.enabled && zoomOut(t.grain)}
              disabled={!t.enabled}
              style={[s.trailBtn, { backgroundColor: c.surface, borderColor: c.border,
                                    opacity: t.enabled ? 1 : 0.35 }]}
              accessibilityRole="button"
              accessibilityLabel={`Zoom out to ${LEVEL_NAME[t.grain].toLowerCase()}`}
            >
              <Text style={[s.trailText, { color: c.primary }]}>↑ {LEVEL_NAME[t.grain]}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* HEADER — the date is the anchor of the card, so it owns its line at
            display size. The status badge and the trend sit on a metadata row
            BENEATH it rather than competing with it for the same baseline:
            three items on one line at phone width is what made this read as
            cluttered. */}
        <View style={s.titleBlock}>
          <Text style={[s.drillTitle, { color: c.foreground }]}>
            {level === 'day' || level === 'lifetime'
              ? cursor.label : `${LEVEL_NAME[level]} · ${cursor.label}`}
          </Text>
          <View style={s.metaRow}>
            {isEntry && (
              /* A GREEN badge, not grey body text. "your last shift" as muted
                 prose read like a caveat; this is a positive status marker and
                 should look like one. */
              <View style={[s.badge, { backgroundColor: c.success + '22' }]}>
                <View style={[s.badgeDot, { backgroundColor: c.success }]} />
                <Text style={[s.badgeText, { color: c.success }]}>LATEST</Text>
              </View>
            )}
            {/* A delta, or NOTHING when there is no completed prior period.
                "Nothing to compare" and "no change" are different facts. */}
            {cursor.trend !== null ? (
              <View style={[s.trendPill, {
                backgroundColor: (cursor.trend >= 0 ? c.success : c.danger) + '1A',
              }]}>
                <Text style={[s.trendText, {
                  color: cursor.trend >= 0 ? c.success : c.danger,
                }]}>
                  {cursor.trend >= 0 ? '↑' : '↓'} {Math.abs(cursor.trend).toFixed(1)}%
                </Text>
              </View>
            ) : level !== 'lifetime' ? (
              <Text style={[s.metaNote, { color: c.mutedForeground }]}>
                no earlier {LEVEL_NAME[level].toLowerCase()} to compare
              </Text>
            ) : null}
          </View>
        </View>

        {/* Sibling navigation — prev/next within the current grain. */}
        {siblings.length > 1 && (
          <View style={s.navRow}>
            <TouchableOpacity
              onPress={() => prev && setCursor(prev)}
              disabled={!prev}
              style={[s.navBtn, { borderColor: c.border, opacity: prev ? 1 : 0 }]}
            >
              <Text style={[s.navText, { color: c.foreground }]}>‹ {prev?.short ?? ''}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => next && setCursor(next)}
              disabled={!next}
              style={[s.navBtn, { borderColor: c.border, opacity: next ? 1 : 0 }]}
            >
              <Text style={[s.navText, { color: c.foreground }]}>{next?.short ?? ''} ›</Text>
            </TouchableOpacity>
          </View>
        )}

        <Figures b={cursor} truckScoped={truckScoped} c={c} s={s} />

        {/* OVERVIEW ABOVE, DETAIL BELOW. The donut summarises the period; the
            RTS list underneath can run to dozens of rows, so putting the
            summary after it buried the one element that makes a long list
            readable. Rendered even when EMPTY — see `neverLoaded`. */}
        <View style={[s.section, { borderTopColor: c.border }]}>
          <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>
            WHY PACKAGES CAME BACK{truckScoped ? ' · whole truck' : ''}
          </Text>
          {neverLoaded ? (
            <Text style={[s.emptyNote, { color: c.mutedForeground }]}>
              Rostered, but no route was assigned
              {level === 'day' ? ' this day' : ' in this period'}.
            </Text>
          ) : (
            <ReasonDonut reasons={reasons} c={c} s={s} />
          )}
        </View>

        {level === 'day' ? (
          <DayDetail date={cursor.start} c={c} s={s} />
        ) : (
          <>
            <View style={[s.section, { borderTopColor: c.border }]}>
              <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>
                DELIVERED BY {level === 'week' ? 'DAY' : level === 'month' ? 'WEEK'
                              : level === 'year' ? 'MONTH' : 'YEAR'}
                {!(level === 'lifetime' && charted.length < 2) &&
                  ` · tap ${level === 'year' ? 'a month' : 'a bar'} to zoom in`}
              </Text>
              {/* THREE presentations, because the levels ask different
                  questions and 12 thin bars answer none of them:
                    year     -> 12 months as a LINE (a trend)
                    lifetime -> under 2 years, figures instead of one bar
                    else     -> bars (few enough buckets to compare directly) */}
              {level === 'year' ? (
                <LineChart data={charted} onPick={zoomIn} c={c} s={s} />
              ) : level === 'lifetime' && charted.length < 2 ? (
                <LifetimeSummary years={charted} lt={lt} onPick={zoomIn} c={c} s={s} />
              ) : (
                <Bars data={charted} onPick={zoomIn} c={c} s={s} />
              )}
            </View>
            <PeriodPanels extras={extras} attendance={attendance} c={c} s={s} />
          </>
        )}
      </View>
    </ScrollView>
  );
}

/* ── pieces ─────────────────────────────────────────────────────────────── */

function Figures({ b, truckScoped, c, s }: {
  b: Bucket; truckScoped: boolean; c: ThemeColors; s: Styles;
}) {
  const attempted = b.delivered + b.rts + b.missing;
  const success = attempted ? (b.delivered / attempted) * 100 : null;
  // Drivers and captains answer for damage reported on the TRUCK; walkers for
  // what they brought back. Never summed — different events.
  const damaged = truckScoped ? b.truckDamaged : b.damaged;
  return (
    <View style={s.figures}>
      <View style={[s.bigTile, { backgroundColor: c.background, borderColor: c.border }]}>
        <Text style={[s.tileLabel, { color: c.mutedForeground }]}>DELIVERED</Text>
        <Text style={[s.bigValue, { color: c.foreground }]}>
          {b.delivered.toLocaleString()}
        </Text>
        {success !== null && (
          <Text style={[s.tileSub, { color: c.mutedForeground }]}>
            {success.toFixed(1)}% of {attempted.toLocaleString()} attempted
          </Text>
        )}
      </View>
      <View style={s.smallRow}>
        {([
          ['RTS', b.rts, c.warning],
          [truckScoped ? 'Truck damage' : 'Damaged', damaged, c.danger],
          ['Missing', b.missing, c.danger],
        ] as [string, number, string][]).map(([l, v, tone]) => (
          <View key={l} style={[s.smallTile, { backgroundColor: c.surface }]}>
            <Text style={[s.tileLabel, { color: c.mutedForeground }]}>{l.toUpperCase()}</Text>
            <Text style={[s.smallValue, { color: tone }]}>{v.toLocaleString()}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

/** Why packages came back, for the selected period.
 *
 *  stroke-dasharray, one circle per segment — no path math, no arc flags, and
 *  the identical technique works in react-native-svg, which is why the web
 *  prototype ported without a charting dependency on either surface. Capped at
 *  top 4 + Other: the technique gets fiddly past ~6 segments and there are 6
 *  RTS types. */
function ReasonDonut({ reasons, c, s }: {
  reasons: { rts_type: string; count: number }[]; c: ThemeColors; s: Styles;
}) {
  const tones = [c.info, c.warning, c.success, c.danger, c.mutedForeground];
  const total = reasons.reduce((n, r) => n + r.count, 0);
  if (!total) {
    return (
      <Text style={[s.emptyNote, { color: c.mutedForeground }]}>
        Nothing came back in this period.
      </Text>
    );
  }
  const top = reasons.slice(0, 4);
  const rest = reasons.slice(4).reduce((n, r) => n + r.count, 0);
  const slices = rest > 0 ? [...top, { rts_type: 'other', count: rest }] : top;

  let offset = 25;   // start at 12 o'clock
  const arcs = slices.map((r, i) => {
    const pct = (r.count / total) * 100;
    const el = (
      <Circle key={r.rts_type} cx="21" cy="21" r="15.9" fill="none"
              stroke={tones[i % tones.length]} strokeWidth="6"
              strokeDasharray={`${pct} ${100 - pct}`} strokeDashoffset={offset} />
    );
    offset -= pct;
    return el;
  });

  return (
    <View>
      <View style={s.donutWrap}>
        <Svg viewBox="0 0 42 42" width={200} height={200}>
          <Circle cx="21" cy="21" r="15.9" fill="none" stroke={c.border} strokeWidth="6" />
          {arcs}
          <SvgText x="21" y="20.5" textAnchor="middle" fill={c.foreground}
                   fontSize="7" fontWeight="700">{String(total)}</SvgText>
          <SvgText x="21" y="25" textAnchor="middle" fill={c.mutedForeground}
                   fontSize="2.8">RETURNED</SvgText>
        </Svg>
      </View>
      <View style={s.legend}>
        {slices.map((r, i) => {
          const pct = (r.count / total) * 100;
          return (
            <View key={r.rts_type} style={s.legendRow}>
              <View style={[s.swatch, { backgroundColor: tones[i % tones.length] }]} />
              <Text style={[s.legendLabel, { color: c.foreground }]} numberOfLines={1}>
                {r.rts_type === 'other' ? 'Other' : (RTS_LABEL[r.rts_type] ?? r.rts_type)}
              </Text>
              <Text style={[s.legendCount, { color: c.foreground }]}>{r.count}</Text>
              <Text style={[s.legendPct, { color: c.mutedForeground }]}>
                {Math.round(pct)}%
              </Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

function Bars({ data, onPick, c, s }: {
  data: Bucket[]; onPick: (b: Bucket) => void; c: ThemeColors; s: Styles;
}) {
  const max = Math.max(1, ...data.map(d => d.delivered));
  if (!data.some(d => d.delivered > 0)) {
    return (
      <Text style={[s.emptyNote, { color: c.mutedForeground }]}>
        Nothing delivered in this period.
      </Text>
    );
  }
  // A ROTATING PALETTE, one tone per bucket. Effort class only ever varies at
  // DAY grain — a week or month mixes efforts, so every coarse bar fell back to
  // one flat primary and the chart read as a single undifferentiated block.
  // Distinct tones let the eye track "which week was that" between the chart
  // and the sibling nav.
  const TONES = [c.primary, c.success, c.info, c.warning, c.gold, c.danger];
  const toneFor = (d: Bucket, i: number) =>
    d.effort ? ({ easy: c.info, standard: c.success, heavy: c.warning }[d.effort] ?? c.primary)
             : TONES[i % TONES.length];

  return (
    <View>
      <View style={[s.barsRow, { borderBottomColor: c.border }]}>
        {data.map((d, i) => {
          const empty = d.delivered === 0;
          const pct = Math.max(4, (d.delivered / max) * 100);
          // THE LABEL GOES INSIDE ONCE THE BAR IS TALL. Rendered above the bar
          // in a fixed-height column, the tallest bar's number is pushed out of
          // the plot and collides with the heading above it — which is exactly
          // what happened to the 84 on Mon. Inside, it can never overflow, and
          // the biggest bar is the one you most want to read.
          const inside = pct > 78;
          return (
            <TouchableOpacity
              key={d.key}
              onPress={() => !empty && onPick(d)}
              disabled={empty}
              style={s.barCol}
              accessibilityRole="button"
              accessibilityLabel={`${d.label}: ${d.delivered} delivered`}
            >
              {!inside && (
                <Text style={[s.barValue, { color: empty ? 'transparent' : c.mutedForeground }]}>
                  {d.delivered > 0 ? d.delivered.toLocaleString() : ''}
                </Text>
              )}
              {empty ? (
                <View style={[s.barEmpty, { backgroundColor: c.border }]} />
              ) : (
                <View style={[s.bar, {
                  backgroundColor: toneFor(d, i),
                  height: `${pct}%`,
                }]}>
                  {inside && (
                    <Text style={[s.barValueInside, { color: c.background }]} numberOfLines={1}>
                      {d.delivered.toLocaleString()}
                    </Text>
                  )}
                </View>
              )}
            </TouchableOpacity>
          );
        })}
      </View>
      {/* Same affordance as the month line: a bucket with work reads as a
          control, an empty one stays flat. The bar itself is the touch target
          (these labels sit under it), so this is a visual cue only. */}
      <View style={s.barLabels}>
        {data.map(d => {
          const on = d.delivered > 0;
          return (
            <View key={d.key} style={s.barLabelCell}>
              <View style={[s.monthChip, on && { backgroundColor: c.primary + '1F' }]}>
                <Text style={[s.monthLabel, {
                  color: on ? c.primary : c.mutedForeground + '66',
                  fontWeight: on ? fontWeight.semibold : fontWeight.regular,
                }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
                  {d.short}
                </Text>
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}

/** Month-by-month as a LINE, not bars.
 *
 *  Twelve bars across a phone are ~24px wide each: too thin to carry a value
 *  label and too chunky to show a trend. A line answers the question a year
 *  view is actually asked — "which way is this going" — and twelve points is
 *  where a line starts beating bars.
 *
 *  MONTHS WITH NO WORK ARE DRAWN AS ZERO, not as a break in the line. The
 *  operator's reasoning, which overrode the usual missing-data convention:
 *  field staff take breaks, so a quiet month is a REAL zero that the person
 *  lived through. A gap in this domain reads as a data-collection failure,
 *  which would be the misleading reading, not the honest one.
 */
function LineChart({ data, onPick, c, s }: {
  data: Bucket[]; onPick: (b: Bucket) => void; c: ThemeColors; s: Styles;
}) {
  const max = Math.max(1, ...data.map(d => d.delivered));
  if (!data.some(d => d.delivered > 0)) {
    return (
      <Text style={[s.emptyNote, { color: c.mutedForeground }]}>
        Nothing delivered in this period.
      </Text>
    );
  }

  // TOP PAD is larger than the others: the peak's value label is drawn above
  // its point, and with a symmetric pad the label sat ON the line at the very
  // point it was labelling. The extra headroom is reserved for it.
  const W = 320, H = 150, PAD = 8, TOP = 24;
  const step = data.length > 1 ? (W - PAD * 2) / (data.length - 1) : 0;
  const x = (i: number) => PAD + i * step;
  const y = (v: number) => H - PAD - (v / max) * (H - PAD - TOP);

  const pts = data.map((d, i) => `${x(i)},${y(d.delivered)}`).join(' ');
  // Closed area under the line, so the shape reads as volume rather than as a
  // bare stroke floating in space.
  const area = `${PAD},${H - PAD} ${pts} ${x(data.length - 1)},${H - PAD}`;
  const peak = data.reduce((b, d, i) => (d.delivered > data[b].delivered ? i : b), 0);

  return (
    <View>
      <Svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H}>
        {/* Baseline only. Gridlines at this size are more ink than information. */}
        <Line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD}
              stroke={c.border} strokeWidth="1" />
        <Polyline points={area} fill={c.primary + '22'} stroke="none" />
        <Polyline points={pts} fill="none" stroke={c.primary}
                  strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        {data.map((d, i) => (
          <Circle key={d.key} cx={x(i)} cy={y(d.delivered)} r={i === peak ? 4 : 2.5}
                  fill={i === peak ? c.primary : c.card}
                  stroke={c.primary} strokeWidth="1.5" />
        ))}
        {/* Only the PEAK is labelled. Twelve labels on a phone overlap into
            noise; the high point is the one that answers "how good did it get". */}
        <SvgText x={x(peak)} y={Math.max(11, y(data[peak].delivered) - 9)}
                 textAnchor="middle" fill={c.foreground} fontSize="11" fontWeight="700">
          {data[peak].delivered.toLocaleString()}
        </SvgText>
      </Svg>
      {/* Tap targets sit UNDER the svg rather than on it: react-native-svg
          hit-testing on small circles is unreliable, and a full-height column
          is a far better thumb target anyway. */}
      <View style={s.lineTapRow}>
        {data.map(d => {
          const on = d.delivered > 0;
          return (
            <TouchableOpacity
              key={d.key}
              style={s.lineTapCol}
              onPress={() => on && onPick(d)}
              disabled={!on}
              accessibilityRole="button"
              accessibilityLabel={`${d.label}: ${d.delivered} delivered`}
            >
              {/* A VISUAL AFFORDANCE, not just the instruction in the heading.
                  Most people skim past a heading; a tappable month has to LOOK
                  tappable. Months with work get a filled chip in the primary
                  tint and primary text — the same treatment as the zoom-out
                  buttons, so the shape already reads as "control" on this
                  screen. Months with no work stay flat and dimmed, which
                  doubles as the disabled state. */}
              <View style={[s.monthChip, on && { backgroundColor: c.primary + '1F' }]}>
                <Text style={[s.monthLabel, {
                  color: on ? c.primary : c.mutedForeground + '66',
                  fontWeight: on ? fontWeight.semibold : fontWeight.regular,
                }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
                  {/* THREE letters, not one. Jan/Jun/Jul all start with J, so a
                      single letter made a third of the axis ambiguous. */}
                  {d.short}
                </Text>
              </View>
            </TouchableOpacity>
          );
        })}
      </View>
    </View>
  );
}

/** Lifetime for an account with too little history to chart.
 *
 *  One bar labelled "2026" is not a chart — it is a rectangle, and it read as a
 *  rendering fault. Below two years the honest presentation is the numbers
 *  themselves, plus a statement of when the chart will appear, so the absence
 *  is explained rather than merely rendered. */
function LifetimeSummary({ years, lt, onPick, c, s }: {
  years: Bucket[];
  lt: { delivered: number; trips: number; success_pct: number | null };
  onPick: (b: Bucket) => void;
  c: ThemeColors; s: Styles;
}) {
  const best = years.reduce<Bucket | null>(
    (b, y) => (!b || y.delivered > b.delivered ? y : b), null);
  const span = years.length === 1 ? years[0].label
             : `${years[0]?.label}–${years[years.length - 1]?.label}`;
  // ZOOMING IN MUST STILL BE POSSIBLE. Every other level offers a bar to tap;
  // replacing the single year bar with figures removed the ONLY way back in
  // from Lifetime — and Lifetime is the one level with no zoom-out trail
  // either, so the screen became a dead end. The year tile is the control.
  const target = years.length === 1 ? years[0] : best;
  return (
    <View>
      <View style={s.tileRow}>
        {([
          ['Delivered', lt.delivered.toLocaleString(), null],
          ['Best year', best ? best.delivered.toLocaleString() : '—', null],
          ['Trips', lt.trips.toLocaleString(), null],
          [years.length === 1 ? 'Only year' : 'Span', span || '—', target],
        ] as [string, string, Bucket | null][]).map(([l, v, tap]) => {
          const body = (
            <>
              <Text style={[s.tileLabel, { color: c.mutedForeground }]}>{l}</Text>
              <Text style={[s.tileValue, { color: c.foreground }]}>{v}</Text>
              {!!tap && (
                <Text style={[s.tileHint, { color: c.primary }]}>tap to open →</Text>
              )}
            </>
          );
          return tap ? (
            <TouchableOpacity
              key={l}
              onPress={() => onPick(tap)}
              accessibilityRole="button"
              accessibilityLabel={`Open ${tap.label}`}
              style={[s.tile, { backgroundColor: c.background, borderColor: c.primary }]}
            >
              {body}
            </TouchableOpacity>
          ) : (
            <View key={l}
                  style={[s.tile, { backgroundColor: c.background, borderColor: c.border }]}>
              {body}
            </View>
          );
        })}
      </View>
      <Text style={[s.emptyNote, { color: c.mutedForeground }]}>
        A year-by-year chart appears once you have two full years of history.
      </Text>
    </View>
  );
}

/** Top blocks + attendance. Week outward only — at a single day "top blocks" is
 *  just "the blocks you worked", which belongs in the day detail. */
function PeriodPanels({ extras, attendance, c, s }: {
  extras: PeriodExtras | null;
  attendance: { present: number; late: number; ncns: number; total: number; rate: number | null };
  c: ThemeColors; s: Styles;
}) {
  const a = attendance;
  const blocks = extras?.top_blocks ?? [];
  const blocksApply = extras?.blocks_apply ?? true;
  return (
    <View style={[s.section, { borderTopColor: c.border }]}>
      <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>ATTENDANCE</Text>
      {a.total === 0 ? (
        /* Null rate, not 0% — "no roll calls" is not "0% attendance". */
        <Text style={[s.emptyNote, { color: c.mutedForeground }]}>
          No roll calls recorded for this period.
        </Text>
      ) : (
        <>
          <Text style={[s.attRate, { color: c.foreground }]}>
            {a.rate?.toFixed(0)}%
            <Text style={[s.attSub, { color: c.mutedForeground }]}>
              {'  '}{a.present} of {a.total} shifts
            </Text>
          </Text>
          <View style={s.attRow}>
            <Text style={[s.attChip, { color: c.success }]}>{a.present} present</Text>
            {a.late > 0 && <Text style={[s.attChip, { color: c.warning }]}>{a.late} late</Text>}
            {a.ncns > 0 && <Text style={[s.attChip, { color: c.danger }]}>{a.ncns} no-show</Text>}
          </View>
        </>
      )}

      {/* Hidden entirely for driver/captain, who never own stops. An empty
          panel reads as broken, not as "not applicable to you". */}
      {blocksApply && (
        <>
          <Text style={[s.sectionLabel, { color: c.mutedForeground, marginTop: spacing.md }]}>
            HARDEST BLOCKS · most returns for the work done
          </Text>
          {blocks.length === 0 ? (
            <Text style={[s.emptyNote, { color: c.mutedForeground }]}>
              No blocks worked in this period.
            </Text>
          ) : (
            blocks.map(b => (
              <View key={b.block_key} style={s.blockRow}>
                <Text style={[s.blockKey, { color: c.foreground }]} numberOfLines={1}>
                  {b.block_key.replace(/_/g, ' ')}
                </Text>
                <Text style={[s.blockStops, { color: c.mutedForeground }]}>{b.stops} stops</Text>
                <Text style={[s.blockRate, {
                  color: (b.rts_rate ?? 0) > 0.15 ? c.danger : c.mutedForeground,
                }]}>
                  {b.rts_rate === null ? '—' : `${Math.round(b.rts_rate * 100)}%`}
                </Text>
              </View>
            ))
          )}
        </>
      )}
    </View>
  );
}

/** Day detail — truck, crew, RTS rows, and the supervised trainee block. */
function DayDetail({ date, c, s }: { date: string; c: ThemeColors; s: Styles }) {
  const [day, setDay] = useState<AssignmentDay | null>(() => dayCache.get(date) ?? null);
  const [loading, setLoading] = useState(!dayCache.has(date));

  useEffect(() => {
    if (dayCache.has(date)) {          // completed day — cannot have changed
      setDay(dayCache.get(date) ?? null);
      setLoading(false);
      return;
    }
    setLoading(true);
    apiClient.get('/assignment-history/me',
      { params: { start_date: date, end_date: date } })
      .then(({ data }) => {
        const d = (data.days ?? [])[0] ?? null;
        dayCache.set(date, d);
        setDay(d);
      })
      .catch(() => setDay(null))
      .finally(() => setLoading(false));
  }, [date]);

  if (loading) return <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.md }} />;
  if (!day) return null;

  const ordered = groupCrew(day.crew ?? []);

  // ADR-269: trainees the caller was PAIRED with that day. `?? []` because the
  // field is optional on the wire — a client can outrun the backend serving it.
  const supervised = day.supervised ?? [];

  return (
    <View style={[s.section, { borderTopColor: c.border }]}>
      {/* TRUCK BANNER — the truck is the identity of the day, so it gets a
          filled row with the vehicle glyph rather than a small outlined pill
          floating among chips. Effort and scope ride inside it as trailing
          metadata, which keeps the whole "where was I" answer on one line. */}
      {(!!day.truck_name || day.counts_scope === 'truck') && (
        <View style={[s.truckBanner, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={[s.truckGlyph, { backgroundColor: c.primary + '26' }]}>
            <Text style={[s.truckGlyphText, { color: c.primary }]}>🚚</Text>
          </View>
          <View style={s.truckMeta}>
            <Text style={[s.truckName, { color: c.foreground }]} numberOfLines={1}>
              {day.truck_name ?? 'Assigned'}
            </Text>
            <Text style={[s.truckSub, { color: c.mutedForeground }]}>
              {day.counts_scope === 'truck' ? 'whole truck' : 'your stops'}
              {!!day.slot_role && ` · ${day.slot_role}`}
            </Text>
          </View>
          {/* Only exceptions get a chip — 'standard' on every row is noise that
              hides the heavy days. */}
          {!!day.effort_class && day.effort_class !== 'standard' && (
            <View style={[s.effortChip, {
              backgroundColor: (day.effort_class === 'heavy' ? c.warning : c.info) + '26',
            }]}>
              <Text style={[s.effortText, {
                color: day.effort_class === 'heavy' ? c.warning : c.info,
              }]}>
                {day.effort_class.toUpperCase()}
              </Text>
            </View>
          )}
        </View>
      )}

      {ordered.length > 0 && (
        <View style={s.crewBlock}>
          <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>
            CREW · {(day.crew ?? []).length}
          </Text>
          {ordered.map(([role, names]) => (
            <View key={role} style={s.crewGroup}>
              {/* Role as a full-width header rather than a fixed-width gutter
                  column. The gutter forced every name to start at the same x
                  no matter how long the role word was, and left a ragged
                  channel down the middle. */}
              <View style={s.crewGroupHead}>
                <View style={[s.roleDot, { backgroundColor: roleTone(role, c) }]} />
                <Text style={[s.crewRole, { color: c.mutedForeground }]}>
                  {role.toUpperCase()}
                </Text>
                <View style={[s.crewRule, { backgroundColor: c.border }]} />
                <Text style={[s.crewCount, { color: c.mutedForeground }]}>{names.length}</Text>
              </View>
              {/* FIXED TWO-COLUMN GRID, not flexWrap. Wrapping variable-width
                  pills is what produced the zig-zag the operator flagged:
                  every row broke at a different point, so no name lined up
                  with the one above it. Each cell is exactly 50% wide, so the
                  left and right columns are true columns. */}
              <View style={s.crewGrid}>
                {names.map(n => (
                  <View key={n} style={s.crewCell}>
                    <View style={[s.avatar, { backgroundColor: roleTone(role, c) + '26' }]}>
                      <Text style={[s.avatarText, { color: roleTone(role, c) }]}>
                        {initials(n)}
                      </Text>
                    </View>
                    <Text style={[s.crewName, { color: c.foreground }]} numberOfLines={1}>
                      {n}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          ))}
        </View>
      )}

      {(day.rts_details ?? []).length > 0 && (
        <>
          {/* WHOSE returns. counts_scope is "truck" for driver/captain, and the
              label must honour it: a driver's day legitimately lists the WHOLE
              truck's returns, which read as personal without this. */}
          <Text style={[s.sectionLabel, { color: c.mutedForeground, marginTop: spacing.md }]}>
            {day.counts_scope === 'truck' ? 'TRUCK RETURNED' : 'YOU RETURNED'}{' '}
            {day.rts_details.length}
          </Text>
          {/* Each return is a CARD with a coloured left edge keyed to the
              reason, not a run of flat text lines. A returned package is a
              discrete event the walker may have to account for, and nine
              identical grey paragraphs gave no way to scan for the one that
              matters. Damage is red — it is the reason with consequences. */}
          {day.rts_details.map(r => {
            const tone = r.rts_type === 'package_damaged' ? c.danger
                       : r.is_reattemptable ? c.info : c.warning;
            return (
              <View key={r.tba_number}
                    style={[s.rtsCard, { backgroundColor: c.surface, borderLeftColor: tone }]}>
                <View style={s.rtsHead}>
                  <Text style={[s.rtsType, { color: c.foreground }]}>
                    {RTS_LABEL[r.rts_type] ?? r.rts_type.replace(/_/g, ' ')}
                  </Text>
                  {r.is_reattemptable && (
                    <View style={[s.retryChip, { backgroundColor: c.info + '26' }]}>
                      <Text style={[s.retryText, { color: c.info }]}>RETRYABLE</Text>
                    </View>
                  )}
                </View>
                {/* THE TBA IS THE PACKAGE'S IDENTITY. Dropped when these rows
                    became cards, which left a return the walker could not tie
                    to an actual package — the one field that makes the row
                    actionable in a dispute. Monospaced and selectable so it can
                    be read aloud or copied into a lookup. */}
                <Text style={[s.rtsTba, { color: c.mutedForeground }]} selectable>
                  {r.tba_number}
                </Text>
                {!!r.rts_explanation && (
                  <Text style={[s.rtsWhy, { color: c.mutedForeground }]}>{r.rts_explanation}</Text>
                )}
              </View>
            );
          })}
        </>
      )}

      {/* SUPERVISED TRAINEES (ADR-269). Rendered SEPARATELY from the counts
          above — merging them resurrects the ADR-244 attribution bug, where a
          trainee's returns land on the trainer's own record. */}
      {supervised.length > 0 && (
        <Text style={[s.sectionLabel, { color: c.mutedForeground, marginTop: spacing.md }]}>
          YOU SUPERVISED · {supervised.length}
        </Text>
      )}
      {supervised.map(sup => {
        const pct = sup.packages_total
          ? Math.round((sup.packages_delivered / sup.packages_total) * 100) : null;
        return (
          /* A CARD, not a text run. This is the record the trainer answers for
             (ADR-269), so it gets the same weight as their own numbers: an
             identity row, a delivered/total figure with a progress bar, and
             the returns as chips. The old version buried all of that in three
             lines of muted body copy. */
          <View key={sup.employee_id}
                style={[s.supCard, { backgroundColor: c.surface, borderColor: c.border }]}>
            <View style={s.supHead}>
              <View style={[s.avatar, { backgroundColor: c.success + '26' }]}>
                <Text style={[s.avatarText, { color: c.success }]}>{initials(sup.name)}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.supName, { color: c.foreground }]} numberOfLines={1}>
                  {sup.name}
                </Text>
                <Text style={[s.supRole, { color: c.mutedForeground }]}>
                  trainee you supervised
                </Text>
              </View>
              {pct !== null && (
                <Text style={[s.supPct, { color: c.foreground }]}>{pct}%</Text>
              )}
            </View>

            <View style={s.supStatRow}>
              <Text style={[s.supStat, { color: c.foreground }]}>
                {sup.packages_delivered}
                <Text style={{ color: c.mutedForeground, fontWeight: fontWeight.regular }}>
                  {' / '}{sup.packages_total} delivered
                </Text>
              </Text>
              {sup.rts_count > 0 && (
                <Text style={[s.supRtsCount, { color: c.warning }]}>{sup.rts_count} RTS</Text>
              )}
            </View>

            {pct !== null && (
              <View style={[s.supBarTrack, { backgroundColor: c.border }]}>
                <View style={[s.supBarFill, { width: `${pct}%`, backgroundColor: c.success }]} />
              </View>
            )}

            {/* Reason AND package. A chip naming only the reason tells the
                trainer three came back but not WHICH three, and the whole point
                of the block is that they can discuss specific packages with the
                trainee (ADR-269). */}
            {sup.rts_details.length > 0 && (
              <View style={s.supRtsList}>
                {sup.rts_details.map(r => (
                  <View key={r.tba_number} style={s.supRtsRow}>
                    <View style={[s.supRtsDot, {
                      backgroundColor: r.rts_type === 'package_damaged' ? c.danger : c.warning,
                    }]} />
                    <Text style={[s.supRtsLabel, { color: c.foreground }]} numberOfLines={1}>
                      {RTS_LABEL[r.rts_type] ?? r.rts_type.replace(/_/g, ' ')}
                    </Text>
                    <Text style={[s.supRtsTba, { color: c.mutedForeground }]} selectable>
                      {r.tba_number}
                    </Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}

type Styles = ReturnType<typeof styles>;

const styles = (c: ThemeColors) => StyleSheet.create({
  wrap:        { padding: spacing.md, gap: spacing.md },
  card:        { borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, gap: spacing.xs },
  cardTitle:   { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  cardHint:    { fontSize: fontSize.xs },
  muted:       { fontSize: fontSize.sm },

  tileRow:     { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm },
  tile:        { flexGrow: 1, flexBasis: '45%', borderWidth: 1, borderRadius: radius.md,
                 padding: spacing.sm },
  tileLabel:   { fontSize: fontSize.xs, letterSpacing: 0.5 },
  tileValue:   { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  tileSub:     { fontSize: fontSize.xs, marginTop: 2 },
  tileHint:    { fontSize: 10, fontWeight: fontWeight.semibold, marginTop: 3 },

  trailRow:    { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  trailBtn:    { borderWidth: 1, borderRadius: radius.md,
                 paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  trailText:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  titleBlock:  { marginTop: spacing.sm, gap: spacing.xs },
  /* Display size: the date is the anchor of the whole card, and at 20px it was
     competing with the section labels rather than leading them. */
  drillTitle:  { fontSize: fontSize['2xl'], fontWeight: fontWeight.bold, letterSpacing: -0.5 },
  metaRow:     { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.xs },
  badge:       { flexDirection: 'row', alignItems: 'center', gap: 5,
                 paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  badgeDot:    { width: 6, height: 6, borderRadius: 3 },
  badgeText:   { fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 0.6 },
  trendPill:   { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  trendText:   { fontSize: fontSize.xs, fontWeight: fontWeight.bold },
  metaNote:    { fontSize: fontSize.xs },
  chip:        { fontSize: fontSize.xs, paddingHorizontal: spacing.sm, paddingVertical: 2,
                 borderRadius: radius.sm, overflow: 'hidden' },

  navRow:      { flexDirection: 'row', justifyContent: 'space-between', marginTop: spacing.xs },
  navBtn:      { borderWidth: 1, borderRadius: radius.md,
                 paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  navText:     { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  figures:     { gap: spacing.sm, marginTop: spacing.sm },
  bigTile:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  bigValue:    { fontSize: 32, fontWeight: fontWeight.bold },
  smallRow:    { flexDirection: 'row', gap: spacing.xs },
  smallTile:   { flex: 1, borderRadius: radius.md, padding: spacing.sm },
  smallValue:  { fontSize: fontSize.md, fontWeight: fontWeight.bold },

  section:     { borderTopWidth: 1, paddingTop: spacing.md, marginTop: spacing.md,
                 gap: spacing.xs },
  sectionLabel:{ fontSize: fontSize.xs, letterSpacing: 0.5, fontWeight: fontWeight.semibold },
  emptyNote:   { fontSize: fontSize.sm, fontStyle: 'italic', paddingVertical: spacing.md,
                 textAlign: 'center' },

  donutWrap:   { alignItems: 'center', paddingVertical: spacing.sm },
  legend:      { gap: spacing.xs },
  legendRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  swatch:      { width: 10, height: 10, borderRadius: 2 },
  legendLabel: { flex: 1, fontSize: fontSize.sm },
  legendCount: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  legendPct:   { fontSize: fontSize.xs, width: 38, textAlign: 'right' },

  barsRow:     { flexDirection: 'row', alignItems: 'flex-end', height: 160,
                 borderBottomWidth: 1, gap: spacing.xs },
  barCol:      { flex: 1, height: '100%', justifyContent: 'flex-end', alignItems: 'center',
                 gap: 2 },
  bar:         { width: '100%', borderTopLeftRadius: radius.sm, borderTopRightRadius: radius.sm },
  barEmpty:    { width: '100%', height: 2, borderRadius: 1 },
  barValue:    { fontSize: 9 },
  /* Inside the bar once it is tall enough to push a label out of the plot.
     Padded from the top so it sits just under the bar's cap. */
  barValueInside: { fontSize: 9, fontWeight: fontWeight.bold,
                    textAlign: 'center', paddingTop: 3 },
  lineTapRow:  { flexDirection: 'row', marginTop: spacing.xs },
  /* paddingVertical on the COLUMN, not the chip: the touch target stays a full
     comfortable height while the chip itself remains compact. */
  lineTapCol:  { flex: 1, alignItems: 'center', paddingVertical: spacing.xs },
  /* NO minWidth, and tight padding. A 12-column axis on a 393pt screen leaves
     27.4pt per column; minWidth:30 plus 5pt padding each side made the chip
     40pt, so "May" and "Aug" truncated to "M..." and "A...". Text-only width
     for three characters at fontSize 10 is ~16.5pt, so 4pt of padding each
     side fits with room to spare. */
  monthChip:   { paddingHorizontal: 3, paddingVertical: 3, borderRadius: radius.sm,
                 alignItems: 'center' },
  /* adjustsFontSizeToFit on the Text handles the residual: estimating glyph
     widths was wrong twice ("May" is wider than "Mar" at the same character
     count because y is a wide glyph), so the label shrinks itself the last
     point or two rather than truncating to "M...". */
  monthLabel:  { fontSize: 10 },
  barLabelCell:{ flex: 1, alignItems: 'center' },
  barLabels:   { flexDirection: 'row', gap: spacing.xs, marginTop: spacing.xs },
  barLabel:    { flex: 1, fontSize: fontSize.xs, textAlign: 'center' },

  attRate:     { fontSize: fontSize.xl, fontWeight: fontWeight.bold },
  attSub:      { fontSize: fontSize.xs, fontWeight: fontWeight.regular },
  attRow:      { flexDirection: 'row', gap: spacing.md, marginTop: 2 },
  attChip:     { fontSize: fontSize.xs },

  blockRow:    { flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
                 paddingVertical: 3 },
  blockKey:    { flex: 1, fontSize: fontSize.xs },
  blockStops:  { fontSize: fontSize.xs },
  blockRate:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold,
                 width: 44, textAlign: 'right' },

  truckBanner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
                 borderWidth: 1, borderRadius: radius.md, padding: spacing.sm },
  truckGlyph:  { width: 34, height: 34, borderRadius: radius.md,
                 alignItems: 'center', justifyContent: 'center' },
  truckGlyphText: { fontSize: 16 },
  truckMeta:   { flex: 1 },
  truckName:   { fontSize: fontSize.base, fontWeight: fontWeight.bold },
  truckSub:    { fontSize: fontSize.xs, marginTop: 1 },
  effortChip:  { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  effortText:  { fontSize: 9, fontWeight: fontWeight.bold, letterSpacing: 0.5 },

  crewBlock:   { gap: spacing.sm },
  crewGroup:   { gap: spacing.xs },
  crewGroupHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  roleDot:     { width: 7, height: 7, borderRadius: 4 },
  crewRole:    { fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 0.6 },
  crewRule:    { flex: 1, height: 1 },
  crewCount:   { fontSize: 10, fontWeight: fontWeight.semibold },
  /* Fixed two-column grid. `flexWrap` on variable-width pills is what produced
     the ragged zig-zag; a 50% basis makes the columns actually align. */
  crewGrid:    { flexDirection: 'row', flexWrap: 'wrap', rowGap: spacing.xs },
  crewCell:    { width: '50%', flexDirection: 'row', alignItems: 'center',
                 gap: spacing.xs, paddingRight: spacing.xs },
  avatar:      { width: 26, height: 26, borderRadius: 13,
                 alignItems: 'center', justifyContent: 'center' },
  avatarText:  { fontSize: 10, fontWeight: fontWeight.bold },
  crewName:    { flex: 1, fontSize: fontSize.xs },

  rtsCard:     { borderLeftWidth: 3, borderRadius: radius.sm,
                 paddingHorizontal: spacing.sm, paddingVertical: spacing.xs,
                 marginTop: spacing.xs, gap: 2 },
  rtsHead:     { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  rtsType:     { flex: 1, fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  retryChip:   { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.full },
  retryText:   { fontSize: 8, fontWeight: fontWeight.bold, letterSpacing: 0.5 },
  /* Monospaced: a TBA is a machine identifier read digit by digit, and a
     proportional font makes 1/l and 0/O ambiguous when reading one aloud. */
  rtsTba:      { fontSize: 10, fontFamily: Platform.select({ ios: 'Menlo', default: 'monospace' }),
                 letterSpacing: 0.3 },
  rtsWhy:      { fontSize: fontSize.xs, fontStyle: 'italic' },

  supCard:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm,
                 marginTop: spacing.xs, gap: spacing.xs },
  supHead:     { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  supName:     { fontSize: fontSize.base, fontWeight: fontWeight.bold },
  supRole:     { fontSize: fontSize.xs },
  supPct:      { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  supStatRow:  { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  supStat:     { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  supRtsCount: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  supBarTrack: { height: 5, borderRadius: 3, overflow: 'hidden' },
  supBarFill:  { height: '100%', borderRadius: 3 },
  supRtsList:  { gap: 3, marginTop: 2 },
  supRtsRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  supRtsDot:   { width: 5, height: 5, borderRadius: 3 },
  supRtsLabel: { flex: 1, fontSize: fontSize.xs },
  supRtsTba:   { fontSize: 10, fontFamily: Platform.select({ ios: 'Menlo', default: 'monospace' }),
                 letterSpacing: 0.3 },
});
