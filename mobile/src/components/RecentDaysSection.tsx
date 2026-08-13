/**
 * Recent days — the per-day half of My Stats (ADR-268).
 *
 * Rendered INSIDE MyPerformanceCard, not as its own screen. MyAccountScreen
 * states the placement rule this follows: the tabs split by WHO SAYS IT — you
 * (Settings), us (My Stats), Amazon (Scorecard) — and surfaces reading from one
 * source do not get split apart. This reads the same DeliveryStop/RTS data the
 * tiles above already summarise.
 *
 * What it adds that the aggregates cannot:
 *   - which truck, and who was on it
 *   - the route's effort_class
 *   - therefore a DIFFICULTY-NORMALISED rate
 *
 * That last one is the point. Raw RTS rate is confounded — 2.10% on easy routes
 * vs 10.81% on heavy, measured — so lifetime totals silently penalise whoever
 * drew the hard work. Per day, with effort_class in hand, it can be corrected.
 */
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

/** Sunday-anchored week containing `d`, as local YMD strings.
 *
 *  One week at a time, not 30 days: thirty rows of truck + crew + returns is
 *  more than anyone reads, and the days that matter are the recent ones. A week
 *  is also the unit people already think in ("how did last week go").
 *
 *  Built from local Y/M/D parts throughout — `new Date('2026-08-07')` is
 *  midnight UTC and lands on the 6th in any timezone behind it, which would
 *  shift the whole week by a day for a US operation. */
function weekBounds(offset: number): { start: Date; end: Date } {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const start = new Date(today);
  start.setDate(today.getDate() - today.getDay() + offset * 7);  // getDay(): 0 = Sunday
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  return { start, end };
}

function ymdOf(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** "Aug 9 – Aug 15", or "This week" / "Last week" for the two most recent. */
function weekLabel(offset: number, start: Date, end: Date): string {
  if (offset === 0) return 'This week';
  if (offset === -1) return 'Last week';
  const f = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return `${f(start)} – ${f(end)}`;
}

/** Returns split into RTS vs DAMAGED, which are not the same outcome.
 *
 *  `package_damaged` is one of the six RTS_TYPES on the wire, but the package
 *  is destroyed rather than merely undelivered — our system tracks it apart
 *  (DamagedPackage, ADR-190) and Amazon scores it separately. Collapsing both
 *  into "3 back" hides the one a manager has to act on.
 *
 *  Deliberately NOT a per-reason breakdown: the full reason list renders
 *  immediately below when expanded, so listing it here duplicates the same
 *  facts twice on one card. */
function summariseReturns(details: RTSDetail[]): { rts: number; damaged: number } {
  let damaged = 0;
  for (const r of details) if (r.rts_type === 'package_damaged') damaged++;
  return { rts: details.length - damaged, damaged };
}

/** "3 RTS", "2 RTS · 1 damaged", "1 damaged". */
function returnsLabel(d: { rts: number; damaged: number }): string {
  const parts: string[] = [];
  if (d.rts > 0) parts.push(`${d.rts} RTS`);
  if (d.damaged > 0) parts.push(`${d.damaged} damaged`);
  return parts.join(' · ');
}

/** Effort class -> bar colour. Difficulty is the story the week tells: a light
 *  week and a week of heavy routes produce very different numbers, and without
 *  colour the chart implies they are comparable.
 *
 *  Uses the SAME tokens as the effort chip on each day card, so the bar and the
 *  chip cannot disagree about what "heavy" looks like. */
function effortColor(effort: string | null, c: ThemeColors): string {
  if (effort === 'heavy') return c.gold;
  if (effort === 'easy') return c.info;
  return c.success;                    // standard, or unknown
}

/** Who sees the difficulty-normalised rate.
 *
 *  The operator's call: it is oversight data, not crew data. A walker being
 *  told they are "0.48x the rate for heavy routes" is being handed a number
 *  they cannot act on and did not ask for — worse, it invites self-comparison
 *  against a company average on a page about their own day.
 *
 *  Keyed off the SLOT ROLE held that day, not the job title, so someone who
 *  ran a route as a walker sees a walker's card for that day. */
const RATE_VISIBLE_ROLES = ['driver', 'captain', 'dispatch', 'management', 'admin'];

function showsRate(slotRole: string): boolean {
  return RATE_VISIBLE_ROLES.includes(slotRole);
}

/** Plain-language reading of rts_rate_vs_class.
 *
 *  "0.33× typical" is meaningless to a walker — the operator asked what it
 *  means, which is the answer. It is the return rate against the company
 *  average FOR ROUTES OF THE SAME DIFFICULTY, so the honest short form is
 *  better/worse than usual, with the multiplier kept as supporting detail. */
function vsClassPhrase(vs: number): string {
  if (vs < 0.75) return 'fewer returns than usual';
  if (vs < 0.95) return 'slightly fewer than usual';
  if (vs <= 1.15) return 'about usual';
  if (vs <= 1.5) return 'slightly more than usual';
  return 'more returns than usual';
}

/** Crew grouped by the role held THAT DAY, in operational reading order.
 *  `role` was already on every crew member and the UI was discarding it —
 *  "who was the driver" is the first thing anyone asks of a past day. */
const CREW_ORDER = ['driver', 'captain', 'trainer', 'walker', 'trainee'];
const CREW_LABEL: Record<string, string> = {
  driver: 'Driver', captain: 'Captain', trainer: 'Trainer',
  walker: 'Walkers', trainee: 'Trainees',
};

function groupCrew(crew: CrewMember[]): { role: string; label: string; names: string[] }[] {
  const by = new Map<string, string[]>();
  for (const m of crew) (by.get(m.role) ?? by.set(m.role, []).get(m.role)!).push(m.name);
  return [...by.entries()]
    .sort((a, b) => {
      const ia = CREW_ORDER.indexOf(a[0]); const ib = CREW_ORDER.indexOf(b[0]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    })
    .map(([role, names]) => ({
      role,
      label: CREW_LABEL[role] ?? role.charAt(0).toUpperCase() + role.slice(1),
      names,
    }));
}

type CrewMember = { name: string; role: string };
type RTSDetail = {
  tba_number: string;
  rts_type: string;
  rts_explanation: string;
  is_reattemptable: boolean;
  normalised_address: string | null;
};
type AssignmentDay = {
  route_date: string;
  truck_name: string | null;
  slot_role: string;
  crew: CrewMember[];
  route_numbers: number[];
  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  effort_class: string | null;
  rts_rate: number | null;
  /** rts_rate / the company rate for the SAME effort_class. 1.0 = typical.
   *  Always prefer this over rts_rate when judging a day. */
  rts_rate_vs_class: number | null;
  rts_details: RTSDetail[];
  address_detail: 'street' | 'block';
  /** 'truck' = driver/captain (whole load); 'own' = walker/trainer/trainee
   *  (only their stops). Must be labelled — a walker's 142 and a driver's
   *  2,865 are different measurements. */
  counts_scope: 'truck' | 'own';
  /** Trainees the caller was PAIRED with that day (ADR-269). Empty for every
   *  role but a trainer who was actually paired — the pairing is the
   *  authorisation, so this is never a filtered view of a longer list.
   *
   *  OPTIONAL ON THE WIRE, not just in spirit: the mobile app ships ahead of
   *  the backend it talks to, so during a deploy window — or against any older
   *  API — this field is simply absent. Typing it as required made
   *  `day.supervised.map()` a hard render crash for EVERY user, not just
   *  trainers. Any newly-added response field is absent from some running
   *  server until that server is updated; the client must survive it. */
  supervised?: SupervisedDay[];
};

/** A paired trainee's day, as their trainer sees it (ADR-269).
 *  Same shape the trainee sees for themselves: during training the trainer
 *  answers for items on this record, so it carries full RTS detail. */
type SupervisedDay = {
  employee_id: string;
  name: string;
  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  rts_rate: number | null;
  rts_rate_vs_class: number | null;
  rts_details: RTSDetail[];
};

const RTS_LABEL: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Customer rescheduled',
  customer_cancelled_order: 'Customer cancelled',
};

function prettyDate(iso: string): string {
  // Rebuilt as LOCAL: new Date('2026-08-07') is midnight UTC and renders as the
  // 6th in any timezone behind it.
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short',
  });
}

/** The selected week as bars, one slot per day Sun-Sat.
 *
 *  MOVED here from MyPerformanceCard, where it was a fixed trailing 7 days fed
 *  by a different endpoint and could not follow the week picker. Built from the
 *  same `days` the cards below render, so the chart and the cards can never
 *  disagree, and stepping back a week moves both together.
 *
 *  Bar HEIGHT is packages delivered; bar COLOUR is the route's difficulty.
 *  Height alone implies a light week and a heavy week are comparable, which is
 *  the confound this whole surface exists to correct for.
 *
 *  Days with no assignment render as an empty slot rather than being omitted:
 *  a gap IS the information ("you did not work Tuesday"), and dropping the slot
 *  would silently reflow the week. */
/** Which number the bars represent. Packages answers "how much did I move",
 *  RTS answers "how much came back" — the same week reads completely
 *  differently under each, and a heavy delivery day with heavy returns is not
 *  visible from either one alone. */
type ChartMetric = 'packages' | 'rts';

function WeekChart({ days, start }: { days: AssignmentDay[]; start: Date }) {
  const c = useColors();
  const s = styles(c);
  const [metric, setMetric] = useState<ChartMetric>('packages');

  const valueOf = (d?: AssignmentDay) =>
    d ? (metric === 'packages' ? d.packages_delivered : d.rts_count) : 0;

  const byDate = new Map(days.map(d => [d.route_date, d]));
  const slots = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return { key: ymdOf(d), letter: 'SMTWTFS'[d.getDay()], day: byDate.get(ymdOf(d)) };
  });

  const max = Math.max(1, ...slots.map(x => valueOf(x.day)));
  // Guard on a VALUE, not merely on a day existing. A week of assignment-only
  // days (rostered, but no delivery stops — Aug 4-7 for a trainer on staging)
  // passed the old check and rendered an axis with no bars, which reads as a
  // broken chart rather than as "you were on a truck but carried nothing".
  const hasValues = slots.some(x => valueOf(x.day) > 0);
  const anyDay = slots.some(x => x.day);
  if (!anyDay) return null;

  return (
    <View style={s.chartWrap}>
      <View style={s.metricRow}>
        {(['packages', 'rts'] as const).map(m => (
          <TouchableOpacity
            key={m}
            onPress={() => setMetric(m)}
            style={[
              s.metricBtn,
              { borderColor: c.border },
              metric === m && { backgroundColor: c.accent, borderColor: c.primary },
            ]}
          >
            <Text style={[
              s.metricText,
              { color: metric === m ? c.foreground : c.mutedForeground },
            ]}>
              {m === 'packages' ? 'Delivered' : 'Returned'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      {!hasValues ? (
        <Text style={[s.chartEmpty, { color: c.mutedForeground }]}>
          {metric === 'packages'
            ? 'No packages delivered this week.'
            : 'Nothing came back this week.'}
        </Text>
      ) : (
      <View style={s.chartRow}>
        {slots.map(slot => {
          const value = valueOf(slot.day);
          return (
            <View key={slot.key} style={s.chartCol}>
              <View style={s.chartBarTrack}>
                {value > 0 && (
                  <View
                    style={{
                      width: '100%',
                      // 12% floor: a day that was worked must read as a bar, not a
                      // sliver, even next to a much bigger day.
                      height: `${Math.max(12, (value / max) * 100)}%`,
                      backgroundColor: effortColor(slot.day?.effort_class ?? null, c),
                      borderTopLeftRadius: 2,
                      borderTopRightRadius: 2,
                    }}
                  />
                )}
              </View>
              <Text style={[s.chartLabel, { color: c.mutedForeground }]}>{slot.letter}</Text>
            </View>
          );
        })}
      </View>
      )}
      {/* The legend is the point of the colour — without it the bars are just
          decorative. Only classes actually present in the week are listed. */}
      <View style={s.legendRow}>
        {(['easy', 'standard', 'heavy'] as const)
          /* `x.day.packages_delivered > 0` is load-bearing: a day with an
             assignment but no delivered packages draws NO bar, so listing its
             class advertises a colour the chart never uses. Jul 23 (effort
             null, 0 delivered) showed a phantom "Standard" entry. */
          .filter(e => slots.some(x =>
            x.day && valueOf(x.day) > 0 && (x.day.effort_class ?? 'standard') === e))
          .map(e => (
            <View key={e} style={s.legendItem}>
              <View style={[s.legendDot, { backgroundColor: effortColor(e, c) }]} />
              <Text style={[s.legendText, { color: c.mutedForeground }]}>{e}</Text>
            </View>
          ))}
      </View>
    </View>
  );
}

function DayRow({ day }: { day: AssignmentDay }) {
  const c = useColors();
  const s = styles(c);
  const [openReturns, setOpenReturns] = useState(false);
  const [openCrew, setOpenCrew] = useState(false);
  const [openSup, setOpenSup] = useState<string | null>(null);

  const vs = day.rts_rate_vs_class;
  const hasWork = day.packages_total > 0;
  const groups = groupCrew(day.crew);
  const supervised = day.supervised ?? [];

  const vsColor = vs === null ? c.mutedForeground
    : vs < 0.95 ? c.success
    : vs > 1.15 ? c.gold
    : c.mutedForeground;

  return (
    <View style={[s.row, { borderColor: c.border, backgroundColor: c.surface }]}>
      {/* HEADER — date owns the line. Truck and effort sit on their own row
          beneath it rather than crowding the date: at phone width three items
          on one line left the truck name squeezed between two neighbours, which
          is exactly what the operator flagged on the Jul 22 card. */}
      <View style={s.headRow}>
        <Text style={[s.date, { color: c.foreground }]}>{prettyDate(day.route_date)}</Text>
        {hasWork && (
          <Text style={[s.count, { color: c.foreground }]}>
            {day.packages_delivered}
            <Text style={{ color: c.mutedForeground, fontWeight: fontWeight.regular }}>
              /{day.packages_total}
            </Text>
          </Text>
        )}
      </View>

      <View style={s.subRow}>
        {!!day.truck_name && (
          <View style={[s.truckPill, { backgroundColor: c.surface, borderColor: c.border }]}>
            <Text style={[s.truckText, { color: c.foreground }]}>{day.truck_name}</Text>
          </View>
        )}
        {!!day.effort_class && day.effort_class !== 'standard' && (
          /* Only exceptions get a chip — 'standard' on every row is noise that
             hides the heavy days. */
          <Text style={[s.chip, {
            color: day.effort_class === 'heavy' ? c.gold : c.info,
            backgroundColor: (day.effort_class === 'heavy' ? c.gold : c.info) + '22',
          }]}>
            {day.effort_class}
          </Text>
        )}
        {hasWork && (
          <Text style={[s.scopeText, { color: c.mutedForeground }]}>
            {day.counts_scope === 'truck' ? 'whole truck' : 'your stops'}
          </Text>
        )}
      </View>

      {/* How the day went, in words. "0.48x typical" alone told the reader
          nothing — the phrase carries the meaning and the number backs it up. */}
      {hasWork && vs !== null && showsRate(day.slot_role) && (
        <Text style={[s.vsLine, { color: vsColor }]}>
          {vsClassPhrase(vs)}
          <Text style={{ color: c.mutedForeground }}>
            {'  '}({vs.toFixed(2)}x the rate for {day.effort_class ?? 'standard'} routes)
          </Text>
        </Text>
      )}

      {/* CREW — grouped by role and expandable. The old single truncated line
          could not answer "who was driving", and the names ran off the card
          with no way to see the rest. */}
      {groups.length > 0 && (
        <>
          <TouchableOpacity onPress={() => setOpenCrew(o => !o)} style={[s.toggle, { borderTopColor: c.border }]}>
            <Text style={[s.toggleText, { color: c.mutedForeground }]}>
              {openCrew ? '▾' : '▸'} Crew ({day.crew.length})
            </Text>
          </TouchableOpacity>
          {openCrew ? (
            <View style={s.crewBlock}>
              {groups.map(g => (
                <View key={g.role} style={s.crewGroup}>
                  <Text style={[s.crewRole, { color: c.mutedForeground }]}>{g.label}</Text>
                  <Text style={[s.crewNames, { color: c.foreground }]}>
                    {g.names.join(', ')}
                  </Text>
                </View>
              ))}
            </View>
          ) : null}
        </>
      )}

      {/* RETURNS — whose, and what kind. "4 came back" said neither. */}
      {day.rts_details.length > 0 && (
        <>
          <TouchableOpacity onPress={() => setOpenReturns(o => !o)} style={[s.toggle, { borderTopColor: c.border }]}>
            <Text style={[s.toggleText, { color: c.mutedForeground }]}>
              {openReturns ? '▾' : '▸'}{' '}
              <Text style={{ color: c.foreground }}>
                {day.counts_scope === 'truck' ? 'Truck brought back' : 'You brought back'}
                {' '}{returnsLabel(summariseReturns(day.rts_details))}
              </Text>
            </Text>
          </TouchableOpacity>
          {openReturns && (
            <View style={s.details}>
              {day.address_detail === 'block' && (
                /* Gone by POLICY (ADR-219), not by failure — without this the
                   blank reads as lost data. */
                <Text style={[s.policy, { color: c.mutedForeground }]}>
                  Street addresses are removed 48h after the route.
                </Text>
              )}
              {day.rts_details.map(r => <RTSRow key={r.tba_number} r={r} c={c} s={s} />)}
            </View>
          )}
        </>
      )}

      {/* SUPERVISED TRAINEES (ADR-269). Separate from the counts above, never
          merged into them — that is the ADR-244 attribution bug. Their returns
          collapse behind their own expander so a trainee with nine returns does
          not bury the rest of the week. */}
      {supervised.map(sup => {
        const open = openSup === sup.employee_id;
        return (
          <View key={sup.employee_id} style={[s.supervised, { borderLeftColor: c.primary }]}>
            <Text style={[s.supervisedName, { color: c.foreground }]}>
              {sup.name}
              <Text style={[s.supervisedRole, { color: c.mutedForeground }]}>
                {'  '}trainee you supervised
              </Text>
            </Text>
            <Text style={[s.supervisedLine, { color: c.mutedForeground }]}>
              <Text style={{ color: c.foreground, fontWeight: fontWeight.semibold }}>
                {sup.packages_delivered}/{sup.packages_total}
              </Text>
              {' delivered'}
            </Text>
            {/* Kept for the trainer even though a trainer is not in
                RATE_VISIBLE_ROLES for their OWN day: they answer for this
                record, which is the whole reason the block exists. */}
            {sup.rts_rate_vs_class != null && (
              <Text style={[s.supervisedLine, {
                color: sup.rts_rate_vs_class > 1.15 ? c.gold
                  : sup.rts_rate_vs_class < 0.95 ? c.success : c.mutedForeground,
              }]}>
                {vsClassPhrase(sup.rts_rate_vs_class)}
                <Text style={{ color: c.mutedForeground }}>
                  {'  '}({sup.rts_rate_vs_class.toFixed(2)}x)
                </Text>
              </Text>
            )}
            {sup.rts_details.length > 0 && (
              <>
                <TouchableOpacity
                  onPress={() => setOpenSup(open ? null : sup.employee_id)}
                  style={[s.toggle, { borderTopColor: c.border }]}
                >
                  <Text style={[s.toggleText, { color: c.mutedForeground }]}>
                    {open ? '▾' : '▸'}{' '}
                    <Text style={{ color: c.foreground }}>
                      Brought back {returnsLabel(summariseReturns(sup.rts_details))}
                    </Text>
                  </Text>
                </TouchableOpacity>
                {open && (
                  <View style={s.details}>
                    {sup.rts_details.map(r => (
                      <RTSRow key={r.tba_number} r={r} c={c} s={s} />
                    ))}
                  </View>
                )}
              </>
            )}
          </View>
        );
      })}
    </View>
  );
}

/** One returned package. Shared by a day's own list and the supervised block,
 *  so the two cannot present the same record differently. */
function RTSRow({ r, c, s }: { r: RTSDetail; c: ThemeColors; s: any }) {
  return (
    <View>
      <Text style={[s.detail, { color: c.mutedForeground }]}>
        <Text style={{ color: c.foreground }}>{RTS_LABEL[r.rts_type] ?? r.rts_type}</Text>
        {r.normalised_address ? ` · ${r.normalised_address}` : ''}
        {r.is_reattemptable ? '  · retryable' : ''}
      </Text>
      {/* The walker's own words. rts_type is a dropdown value; this is what they
          actually wrote, and it is the part that explains the day a week later. */}
      {!!r.rts_explanation && (
        <Text style={[s.explanation, { color: c.mutedForeground }]}>{r.rts_explanation}</Text>
      )}
    </View>
  );
}

export default function RecentDaysSection() {
  const c = useColors();
  const s = styles(c);
  // 0 = this week, -1 = last week, ... Forward is capped at 0: there is no
  // history to show for days that have not happened.
  const [offset, setOffset] = useState(0);
  const [days, setDays] = useState<AssignmentDay[] | null>(null);
  const [loading, setLoading] = useState(true);

  const { start, end } = weekBounds(offset);

  useEffect(() => {
    setLoading(true);
    apiClient
      .get('/assignment-history/me', {
        params: { start_date: ymdOf(start), end_date: ymdOf(end) },
      })
      .then(({ data }) => setDays(data.days ?? []))
      // Silent, matching MyPerformanceCard: a stats section must not error the
      // account screen around it.
      .catch(() => setDays([]))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  return (
    <View style={[s.wrap, { borderTopColor: c.border }]}>
      <View style={s.head}>
        <Text style={[s.headTitle, { color: c.foreground }]}>Recent days</Text>
      </View>

      {/* Week navigation. Next is disabled at offset 0 rather than hidden, so
          the control does not jump around as you move between weeks. */}
      <View style={s.weekNav}>
        <TouchableOpacity
          onPress={() => setOffset(o => o - 1)}
          style={[s.navBtn, { borderColor: c.border }]}
          accessibilityLabel="Previous week"
        >
          <Text style={[s.navText, { color: c.foreground }]}>‹</Text>
        </TouchableOpacity>
        <Text style={[s.weekLabel, { color: c.foreground }]}>
          {weekLabel(offset, start, end)}
        </Text>
        <TouchableOpacity
          onPress={() => setOffset(o => Math.min(0, o + 1))}
          disabled={offset >= 0}
          style={[s.navBtn, { borderColor: c.border, opacity: offset >= 0 ? 0.3 : 1 }]}
          accessibilityLabel="Next week"
        >
          <Text style={[s.navText, { color: c.foreground }]}>›</Text>
        </TouchableOpacity>
      </View>

      {/* The week's shape, immediately under the picker it belongs to. */}
      {!loading && days && days.length > 0 && <WeekChart days={days} start={start} />}

      {loading ? (
        <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.md }} />
      ) : !days || days.length === 0 ? (
        /* An empty week is a real answer — "you did not work" — and must not
           render as a missing section the way the old 30-day view did. */
        <Text style={[s.empty, { color: c.mutedForeground }]}>
          No assignments {offset === 0 ? 'yet this week' : 'that week'}.
        </Text>
      ) : (
        days.map(d => <DayRow key={`${d.route_date}-${d.truck_name ?? ''}`} day={d} />)
      )}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  wrap:      { marginTop: spacing.md, paddingTop: spacing.md, borderTopWidth: 1 },
  head:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: spacing.xs },
  headTitle: { fontSize: fontSize.sm, fontWeight: fontWeight.bold },

  // Week navigation
  weekNav:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
  navBtn:    { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: 2, minWidth: 34, alignItems: 'center' },
  navText:   { fontSize: fontSize.md, fontWeight: fontWeight.semibold },
  weekLabel: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  empty:     { fontSize: 11, fontStyle: 'italic', paddingVertical: spacing.sm, textAlign: 'center' },

  // Chart, inside the week picker block
  chartWrap:     { marginBottom: spacing.md },
  metricRow:     { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.sm, justifyContent: 'center' },
  metricBtn:     { borderWidth: 1, borderRadius: radius.full, paddingHorizontal: spacing.sm, paddingVertical: 3 },
  metricText:    { fontSize: 10, fontWeight: fontWeight.semibold },
  chartRow:      { flexDirection: 'row', height: 76, gap: 6, alignItems: 'flex-end' },
  chartCol:      { flex: 1, alignItems: 'center' },
  chartBarTrack: { flex: 1, width: '100%', justifyContent: 'flex-end' },
  chartLabel:    { fontSize: 9, marginTop: 3 },
  chartEmpty:    { fontSize: 11, fontStyle: 'italic', textAlign: 'center', paddingVertical: spacing.md },
  legendRow:     { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs, justifyContent: 'center' },
  legendItem:    { flexDirection: 'row', alignItems: 'center', gap: 4 },
  legendDot:     { width: 7, height: 7, borderRadius: 2 },
  legendText:    { fontSize: 9, textTransform: 'capitalize' },

  // Cards get real breathing room and a surface fill, so each day reads as its
  // own object rather than one continuous wall of text. Spacing alone was not
  // enough — without the fill the borders were the only separator.
  row:       { borderWidth: 1, borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.md, marginBottom: spacing.sm },

  // Date owns its line; the count sits opposite it. Truck/effort/scope drop to
  // a second row so nothing is squeezed between two neighbours at phone width.
  headRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  date:      { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  count:     { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  subRow:    { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginTop: 3 },

  // A bordered pill, not bare text: the truck is an identifier and was
  // disappearing between the date and the effort chip.
  truckPill: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 6, paddingVertical: 1 },
  truckText: { fontSize: 11, fontWeight: fontWeight.semibold },
  chip:      { fontSize: 9, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.5, paddingHorizontal: 5, paddingVertical: 1, borderRadius: radius.sm, overflow: 'hidden' },
  scopeText: { fontSize: 10 },
  vsLine:    { fontSize: 11, marginTop: 4, fontWeight: fontWeight.semibold },

  // Crew
  crewPeek:  { fontSize: 11, marginTop: 2 },
  crewBlock: { marginTop: 4, gap: 3 },
  crewGroup: { flexDirection: 'row', gap: 6, alignItems: 'flex-start' },
  crewRole:  { fontSize: 10, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.4, width: 62 },
  crewNames: { fontSize: 11, flex: 1 },

  // A hairline above each expander turns "one wall of lines" into labelled
  // bands: identity / performance / crew / returns.
  toggle:    { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth },
  toggleText:{ fontSize: 11 },
  details:   { marginTop: 4, gap: 2 },
  policy:    { fontSize: 10, fontStyle: 'italic' },
  detail:    { fontSize: 11 },
  explanation: { fontSize: 11, fontStyle: 'italic', marginLeft: spacing.xs, marginBottom: 2 },

  // Indented + left rule so a trainee's numbers read as SOMEONE ELSE'S at a
  // glance. Without the offset they sit in the same visual column as the
  // trainer's own counts and invite being read as one total.
  supervised:     { marginTop: spacing.sm, paddingLeft: spacing.sm, borderLeftWidth: 2 },
  supervisedName: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  supervisedRole: { fontSize: 10, fontWeight: fontWeight.regular },
  supervisedLine: { fontSize: 11, marginBottom: 2 },
});
