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
} from 'react-native';
import Svg, { Circle, Text as SvgText } from 'react-native-svg';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import {
  attendanceIn, daysOfWeek, monthsOfYear, reasonsIn, weeksOfMonth, yearsFrom,
  lastWorkedDay, parseYMD, type Bucket, type Grain,
} from './aggregate';
import type { AssignmentDay, MyStats, PeriodExtras } from './types';

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

const CREW_ORDER = ['driver', 'captain', 'trainer', 'walker', 'trainee'];

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

        <View style={s.titleRow}>
          <Text style={[s.drillTitle, { color: c.foreground }]}>
            {level === 'day' || level === 'lifetime'
              ? cursor.label : `${LEVEL_NAME[level]} · ${cursor.label}`}
          </Text>
          {isEntry && (
            <Text style={[s.chip, { color: c.mutedForeground, backgroundColor: c.surface }]}>
              your last shift
            </Text>
          )}
        </View>

        {/* A delta, or NOTHING when there is no completed prior period.
            "Nothing to compare" and "no change" are different facts. */}
        {cursor.trend !== null ? (
          <Text style={[s.trend, {
            color: cursor.trend >= 0 ? c.success : c.danger,
          }]}>
            {cursor.trend >= 0 ? '▲' : '▼'} {Math.abs(cursor.trend).toFixed(1)}%
          </Text>
        ) : level !== 'lifetime' ? (
          <Text style={[s.muted, { color: c.mutedForeground }]}>
            no earlier {LEVEL_NAME[level].toLowerCase()} to compare
          </Text>
        ) : null}

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
                              : level === 'year' ? 'MONTH' : 'YEAR'} · tap a bar to zoom in
              </Text>
              <Bars data={charted} onPick={zoomIn} c={c} s={s} />
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
  const EFFORT_TONE: Record<string, string> = {
    easy: c.info, standard: c.success, heavy: c.warning,
  };
  return (
    <View>
      <View style={[s.barsRow, { borderBottomColor: c.border }]}>
        {data.map(d => {
          const empty = d.delivered === 0;
          return (
            <TouchableOpacity
              key={d.key}
              onPress={() => !empty && onPick(d)}
              disabled={empty}
              style={s.barCol}
              accessibilityRole="button"
              accessibilityLabel={`${d.label}: ${d.delivered} delivered`}
            >
              <Text style={[s.barValue, { color: empty ? 'transparent' : c.mutedForeground }]}>
                {d.delivered > 0 ? d.delivered.toLocaleString() : ''}
              </Text>
              {empty ? (
                <View style={[s.barEmpty, { backgroundColor: c.border }]} />
              ) : (
                <View style={[s.bar, {
                  backgroundColor: d.effort ? EFFORT_TONE[d.effort] ?? c.primary : c.primary,
                  height: `${Math.max(4, (d.delivered / max) * 100)}%`,
                }]} />
              )}
            </TouchableOpacity>
          );
        })}
      </View>
      <View style={s.barLabels}>
        {data.map(d => (
          <Text key={d.key} style={[s.barLabel, { color: c.mutedForeground }]} numberOfLines={1}>
            {d.short}
          </Text>
        ))}
      </View>
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

  const groups = new Map<string, string[]>();
  for (const m of day.crew ?? []) {
    if (!groups.has(m.role)) groups.set(m.role, []);
    groups.get(m.role)!.push(m.name);
  }
  const ordered = [...groups.entries()].sort(
    (a, b) => CREW_ORDER.indexOf(a[0]) - CREW_ORDER.indexOf(b[0]));

  // ADR-269: trainees the caller was PAIRED with that day. `?? []` because the
  // field is optional on the wire — a client can outrun the backend serving it.
  const supervised = day.supervised ?? [];

  return (
    <View style={[s.section, { borderTopColor: c.border }]}>
      <View style={s.dayHead}>
        {day.counts_scope === 'truck' && (
          <Text style={[s.chip, { color: c.mutedForeground, backgroundColor: c.surface }]}>
            whole truck
          </Text>
        )}
        {!!day.truck_name && (
          <View style={[s.truckPill, { backgroundColor: c.surface, borderColor: c.border }]}>
            <Text style={[s.truckText, { color: c.foreground }]}>{day.truck_name}</Text>
          </View>
        )}
        {!!day.effort_class && day.effort_class !== 'standard' && (
          /* Only exceptions get a chip — 'standard' on every row is noise that
             hides the heavy days. */
          <Text style={[s.chip, {
            color: day.effort_class === 'heavy' ? c.warning : c.info,
            backgroundColor: c.surface,
          }]}>
            {day.effort_class}
          </Text>
        )}
      </View>

      {ordered.length > 0 && (
        <>
          <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>CREW</Text>
          {ordered.map(([role, names]) => (
            <View key={role} style={s.crewRow}>
              <Text style={[s.crewRole, { color: c.mutedForeground }]}>{role.toUpperCase()}</Text>
              <View style={s.crewNames}>
                {names.map(n => (
                  <View key={n} style={[s.crewPill, { backgroundColor: c.surface }]}>
                    <View style={[s.avatar, { backgroundColor: c.primary + '33' }]}>
                      <Text style={[s.avatarText, { color: c.primary }]}>{initials(n)}</Text>
                    </View>
                    <Text style={[s.crewName, { color: c.foreground }]}>{n}</Text>
                  </View>
                ))}
              </View>
            </View>
          ))}
        </>
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
          {day.rts_details.map(r => (
            <View key={r.tba_number} style={s.rtsRow}>
              <Text style={[s.rtsType, { color: c.foreground }]}>
                {RTS_LABEL[r.rts_type] ?? r.rts_type.replace(/_/g, ' ')}
                {r.is_reattemptable && (
                  <Text style={[s.retry, { color: c.info }]}>{'  '}retryable</Text>
                )}
              </Text>
              {!!r.rts_explanation && (
                <Text style={[s.rtsWhy, { color: c.mutedForeground }]}>{r.rts_explanation}</Text>
              )}
            </View>
          ))}
        </>
      )}

      {/* SUPERVISED TRAINEES (ADR-269). Rendered SEPARATELY from the counts
          above — merging them resurrects the ADR-244 attribution bug, where a
          trainee's returns land on the trainer's own record. */}
      {supervised.map(sup => (
        <View key={sup.employee_id} style={[s.supervised, { borderLeftColor: c.primary }]}>
          <Text style={[s.supName, { color: c.foreground }]}>
            {sup.name}
            <Text style={[s.supRole, { color: c.mutedForeground }]}>
              {'  '}trainee you supervised
            </Text>
          </Text>
          <Text style={[s.supLine, { color: c.mutedForeground }]}>
            <Text style={{ color: c.foreground, fontWeight: fontWeight.semibold }}>
              {sup.packages_delivered}/{sup.packages_total}
            </Text>
            {' delivered'}
            {sup.rts_count > 0 && `  ·  ${sup.rts_count} RTS`}
          </Text>
          {sup.rts_details.length > 0 && sup.rts_details.map(r => (
            <Text key={r.tba_number} style={[s.supRts, { color: c.mutedForeground }]}>
              • {RTS_LABEL[r.rts_type] ?? r.rts_type.replace(/_/g, ' ')}
            </Text>
          ))}
        </View>
      ))}
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

  trailRow:    { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  trailBtn:    { borderWidth: 1, borderRadius: radius.md,
                 paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  trailText:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  titleRow:    { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap',
                 gap: spacing.xs, marginTop: spacing.sm },
  drillTitle:  { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  chip:        { fontSize: fontSize.xs, paddingHorizontal: spacing.sm, paddingVertical: 2,
                 borderRadius: radius.sm, overflow: 'hidden' },
  trend:       { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

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

  dayHead:     { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.xs },
  truckPill:   { borderWidth: 1, borderRadius: radius.md,
                 paddingHorizontal: spacing.sm, paddingVertical: 3 },
  truckText:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  crewRow:     { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  crewRole:    { width: 60, fontSize: 9, fontWeight: fontWeight.bold, paddingTop: 6 },
  crewNames:   { flex: 1, flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  crewPill:    { flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
                 borderRadius: 999, paddingLeft: 3, paddingRight: spacing.sm, paddingVertical: 2 },
  avatar:      { width: 20, height: 20, borderRadius: 10,
                 alignItems: 'center', justifyContent: 'center' },
  avatarText:  { fontSize: 9, fontWeight: fontWeight.bold },
  crewName:    { fontSize: fontSize.xs },

  rtsRow:      { paddingVertical: 3 },
  rtsType:     { fontSize: fontSize.sm },
  retry:       { fontSize: 9 },
  rtsWhy:      { fontSize: fontSize.xs, fontStyle: 'italic' },

  supervised:  { borderLeftWidth: 3, paddingLeft: spacing.sm, marginTop: spacing.md,
                 gap: 2 },
  supName:     { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  supRole:     { fontSize: fontSize.xs, fontWeight: fontWeight.regular },
  supLine:     { fontSize: fontSize.xs },
  supRts:      { fontSize: fontSize.xs, paddingLeft: spacing.xs },
});
