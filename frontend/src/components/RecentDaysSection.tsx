/**
 * Recent days — the per-day half of My Stats (ADR-268).
 *
 * Lives INSIDE MyPerformanceCard rather than on its own page. My Stats already
 * answers "how am I doing overall" from the same source (our DeliveryStop/RTS
 * data), and mobile's MyAccountScreen states the placement rule this follows:
 * tabs are split by WHO SAYS IT — you, us, Amazon — and things reading from one
 * source do not get split across surfaces.
 *
 * What this adds that the aggregate tiles cannot show:
 *   - which truck, and who was on it
 *   - the route's effort_class
 *   - therefore a DIFFICULTY-NORMALISED rate, where the tiles show raw counts
 *
 * That last point is the reason this exists. Raw RTS rate is confounded:
 * 2.10% on easy routes vs 10.81% on heavy ones, measured. The lifetime totals
 * above cannot correct for that; per-day, with effort_class in hand, we can.
 */
import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import type {
  AssignmentDay, AssignmentHistoryResponse, HistoryRTSDetail,
} from '../api/types';
import { ChevronDown, ChevronUp, Truck, Users } from 'lucide-react';

/** Sunday-anchored week containing today, shifted by `offset` weeks.
 *
 *  One week at a time, not 30 days: thirty rows of truck + crew + returns is
 *  more than anyone reads, and a week is the unit people already think in.
 *
 *  Built from local Y/M/D parts — `new Date('2026-08-07')` is midnight UTC and
 *  lands on the 6th in any timezone behind it, shifting the whole week. */
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

function weekLabel(offset: number, start: Date, end: Date): string {
  if (offset === 0) return 'This week';
  if (offset === -1) return 'Last week';
  const f = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return `${f(start)} – ${f(end)}`;
}

function prettyDate(iso: string): string {
  // Split and rebuild as LOCAL. `new Date('2026-08-07')` is midnight UTC and
  // renders as the 6th anywhere behind it.
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short',
  });
}

const RTS_LABEL: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Customer rescheduled',
  customer_cancelled_order: 'Customer cancelled',
};

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
function summariseReturns(details: HistoryRTSDetail[]): { rts: number; damaged: number } {
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
 *  week and a heavy week produce very different numbers, and without colour the
 *  chart implies they are comparable. Same tokens as the effort chip on each
 *  card, so bar and chip cannot disagree about what "heavy" looks like. */
const EFFORT_BAR: Record<string, string> = {
  easy: 'bg-info', standard: 'bg-success', heavy: 'bg-warning',
};
function effortBar(effort: string | null): string {
  return EFFORT_BAR[effort ?? 'standard'] ?? 'bg-success';
}

/** Who sees the difficulty-normalised rate.
 *
 *  Oversight data, not crew data. A walker told they are "0.48× the rate for
 *  heavy routes" is handed a number they cannot act on, and it invites
 *  self-comparison against a company average on a page about their own day.
 *
 *  Keyed off the SLOT ROLE held that day, not the job title. */
const RATE_VISIBLE_ROLES = ['driver', 'captain', 'dispatch', 'management', 'admin'];
function showsRate(slotRole: string): boolean {
  return RATE_VISIBLE_ROLES.includes(slotRole);
}

/** Plain-language reading of rts_rate_vs_class. "0.33× typical" is meaningless
 *  on its own; this is what it means — the return rate against the company
 *  average FOR ROUTES OF THE SAME DIFFICULTY. */
function vsClassPhrase(vs: number): string {
  if (vs < 0.75) return 'fewer returns than usual';
  if (vs < 0.95) return 'slightly fewer than usual';
  if (vs <= 1.15) return 'about usual';
  if (vs <= 1.5) return 'slightly more than usual';
  return 'more returns than usual';
}

/** Crew grouped by the role held THAT DAY, in operational reading order.
 *  `role` was already on every crew member and the UI discarded it — "who was
 *  the driver" is the first thing anyone asks of a past day. */
const CREW_ORDER = ['driver', 'captain', 'trainer', 'walker', 'trainee'];
const CREW_LABEL: Record<string, string> = {
  driver: 'Driver', captain: 'Captain', trainer: 'Trainer',
  walker: 'Walkers', trainee: 'Trainees',
};

function groupCrew(crew: { name: string; role: string }[]) {
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

/** The selected week as bars, one slot per day Sun–Sat.
 *
 *  Lives INSIDE the week picker so it moves with it. Built from the same `days`
 *  the cards below render, so chart and cards can never disagree.
 *
 *  Bar HEIGHT is packages delivered; bar COLOUR is the route's difficulty.
 *  Height alone implies a light week and a heavy week are comparable, which is
 *  the confound this surface exists to correct.
 *
 *  Days with no assignment render as an empty slot: the gap IS the information
 *  ("you did not work Tuesday"), and omitting it would reflow the week. */
/** Which number the bars represent. Packages answers "how much did I move",
 *  RTS answers "how much came back" — the same week reads completely
 *  differently under each. Must stay in step with the mobile WeekChart. */
type ChartMetric = 'packages' | 'rts';

function WeekChart({ days, start }: { days: AssignmentDay[]; start: Date }) {
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
  if (!slots.some(x => x.day)) return null;

  const present = (['easy', 'standard', 'heavy'] as const).filter(e =>
    /* `packages_delivered > 0` is load-bearing: a day with an assignment but no
       delivered packages draws NO bar, so listing its class advertises a colour
       the chart never uses. */
    /* Follows the metric: a day with 0 RTS draws no bar in RTS mode, so it
       must not claim a legend swatch there either. */
    slots.some(x => x.day && valueOf(x.day) > 0 &&
                    (x.day.effort_class ?? 'standard') === e));

  return (
    <div className="mb-4">
      <div className="flex justify-center gap-1.5 mb-2">
        {(['packages', 'rts'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMetric(m)}
            className={`px-2.5 py-0.5 rounded-full border text-[10px] font-semibold transition-colors ${
              metric === m
                ? 'border-primary bg-accent text-foreground'
                : 'border-border text-muted-foreground hover:text-foreground'
            }`}
          >
            {m === 'packages' ? 'Delivered' : 'Returned'}
          </button>
        ))}
      </div>
      <div className="flex items-end gap-1.5 h-20">
        {slots.map(slot => {
          const value = valueOf(slot.day);
          return (
            <div key={slot.key} className="flex-1 flex flex-col items-center justify-end h-full">
              {value > 0 && (
                <div
                  className={`w-full rounded-t ${effortBar(slot.day?.effort_class ?? null)}`}
                  /* 12% floor: a worked day must read as a bar, not a sliver. */
                  style={{ height: `${Math.max(12, (value / max) * 100)}%` }}
                  title={`${value} ${metric === 'packages' ? 'delivered' : 'returned'} · ${slot.day?.effort_class ?? 'standard'}`}
                />
              )}
            </div>
          );
        })}
      </div>
      <div className="flex gap-1.5 mt-1">
        {slots.map(slot => (
          <span key={slot.key} className="flex-1 text-center text-[9px] text-muted-foreground">
            {slot.letter}
          </span>
        ))}
      </div>
      {/* The legend is the point of the colour — without it the bars are just
          decorative. Only classes actually drawn are listed. */}
      <div className="flex justify-center gap-3 mt-1.5">
        {present.map(e => (
          <span key={e} className="flex items-center gap-1 text-[9px] text-muted-foreground capitalize">
            <span className={`w-1.5 h-1.5 rounded-sm ${effortBar(e)}`} />{e}
          </span>
        ))}
      </div>
    </div>
  );
}

function DayRow({ day }: { day: AssignmentDay }) {
  const [openReturns, setOpenReturns] = useState(false);
  const [openCrew, setOpenCrew] = useState(false);
  const [openSup, setOpenSup] = useState<string | null>(null);

  const hasWork = day.packages_total > 0;
  const vs = day.rts_rate_vs_class;
  const groups = groupCrew(day.crew);
  const supervised = day.supervised ?? [];

  const vsTone = vs === null ? 'text-muted-foreground'
    : vs < 0.95 ? 'text-success'
    : vs > 1.15 ? 'text-warning'
    : 'text-muted-foreground';

  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3.5">
      {/* HEADER — the date owns its line, the count sits opposite. Truck and
          effort drop to a second row rather than being squeezed between two
          neighbours at narrow widths. */}
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-base font-bold text-foreground">{prettyDate(day.route_date)}</span>
        {hasWork && (
          <span className="text-base font-bold text-foreground tabular-nums shrink-0">
            {day.packages_delivered}
            <span className="font-normal text-muted-foreground">/{day.packages_total}</span>
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 flex-wrap mt-1">
        {day.truck_name && (
          /* A bordered pill, not bare text: the truck is an identifier and was
             disappearing between the date and the effort chip. */
          <span className="flex items-center gap-1 text-[11px] font-semibold text-foreground
                           border border-border rounded px-1.5 py-0.5">
            <Truck className="w-3 h-3" />{day.truck_name}
          </span>
        )}
        {day.effort_class && day.effort_class !== 'standard' && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide font-bold ${
            day.effort_class === 'heavy' ? 'bg-warning/15 text-warning' : 'bg-info/10 text-info'
          }`}>
            {day.effort_class}
          </span>
        )}
        {hasWork && (
          <span className="text-[10px] text-muted-foreground">
            {day.counts_scope === 'truck' ? 'whole truck' : 'your stops'}
          </span>
        )}
      </div>

      {/* How the day went, in words. The multiplier alone told the reader
          nothing — the phrase carries the meaning, the number supports it. */}
      {hasWork && vs !== null && showsRate(day.slot_role) && (
        <p className={`text-[11px] font-semibold mt-1 ${vsTone}`}>
          {vsClassPhrase(vs)}
          <span className="font-normal text-muted-foreground">
            {' '}({vs.toFixed(2)}× the rate for {day.effort_class ?? 'standard'} routes)
          </span>
        </p>
      )}

      {/* CREW — grouped by role, expandable. The old truncated single line
          could not answer "who was driving" and ran off the card. */}
      {groups.length > 0 && (
        <>
          <button
            onClick={() => setOpenCrew(o => !o)}
            className="mt-2.5 pt-2.5 border-t border-border/60 w-full flex items-center gap-1
                       text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {openCrew ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            <Users className="w-3 h-3" /> Crew ({day.crew.length})
          </button>
          {openCrew ? (
            <div className="mt-1 space-y-0.5">
              {groups.map(g => (
                <div key={g.role} className="flex gap-2 text-[11px]">
                  <span className="w-16 shrink-0 uppercase tracking-wide font-bold
                                   text-muted-foreground text-[10px] pt-px">
                    {g.label}
                  </span>
                  <span className="text-foreground">{g.names.join(', ')}</span>
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}

      {/* RETURNS — whose, and what kind. "4 came back" said neither. */}
      {day.rts_details.length > 0 && (
        <>
          <button
            onClick={() => setOpenReturns(o => !o)}
            className="mt-2.5 pt-2.5 border-t border-border/60 w-full flex items-center gap-1
                       text-[11px] text-muted-foreground hover:text-foreground transition-colors text-left"
          >
            {openReturns ? <ChevronUp className="w-3 h-3 shrink-0" /> : <ChevronDown className="w-3 h-3 shrink-0" />}
            <span className="text-foreground font-medium">
              {day.counts_scope === 'truck' ? 'Truck brought back' : 'You brought back'}{' '}
              {returnsLabel(summariseReturns(day.rts_details))}
            </span>
          </button>
          {openReturns && (
            <div className="mt-1.5 space-y-1">
              {day.address_detail === 'block' && (
                /* Gone by POLICY (ADR-219), not by failure. */
                <p className="text-[10px] text-muted-foreground italic">
                  Street addresses are removed 48h after the route.
                </p>
              )}
              {day.rts_details.map(r => <RTSRow key={r.tba_number} r={r} />)}
            </div>
          )}
        </>
      )}

      {/* SUPERVISED TRAINEES (ADR-269). Separate from the counts above, never
          merged — that is the ADR-244 attribution bug. Their returns collapse
          behind their own expander so nine returns do not bury the week. */}
      {supervised.map(sup => {
        const open = openSup === sup.employee_id;
        return (
          <div key={sup.employee_id} className="mt-2 pl-2 border-l-2 border-primary/60">
            <p className="text-xs font-semibold text-foreground">
              {sup.name}
              <span className="ml-1.5 font-normal text-[10px] text-muted-foreground">
                trainee you supervised
              </span>
            </p>
            <p className="text-[11px] text-muted-foreground">
              <span className="font-semibold text-foreground tabular-nums">
                {sup.packages_delivered}/{sup.packages_total}
              </span> delivered
            </p>
            {/* Kept for the trainer even though a trainer is not in
                RATE_VISIBLE_ROLES for their OWN day: they answer for this
                record, which is why the block exists. */}
            {sup.rts_rate_vs_class != null && (
              <p className={`text-[11px] ${
                sup.rts_rate_vs_class > 1.15 ? 'text-warning'
                  : sup.rts_rate_vs_class < 0.95 ? 'text-success' : 'text-muted-foreground'
              }`}>
                {vsClassPhrase(sup.rts_rate_vs_class)}
                <span className="text-muted-foreground"> ({sup.rts_rate_vs_class.toFixed(2)}×)</span>
              </p>
            )}
            {sup.rts_details.length > 0 && (
              <>
                <button
                  onClick={() => setOpenSup(open ? null : sup.employee_id)}
                  className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground
                             hover:text-foreground transition-colors text-left"
                >
                  {open ? <ChevronUp className="w-3 h-3 shrink-0" /> : <ChevronDown className="w-3 h-3 shrink-0" />}
                  <span className="text-foreground font-medium">
                    Brought back {returnsLabel(summariseReturns(sup.rts_details))}
                  </span>
                </button>
                {open && (
                  <div className="mt-1 space-y-1">
                    {sup.rts_details.map(r => <RTSRow key={r.tba_number} r={r} />)}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** One returned package. Shared by a day's own RTS list and by the supervised
 *  block below it, so the two cannot present the same record differently. */
function RTSRow({ r }: { r: HistoryRTSDetail }) {
  return (
    <div className="text-[11px]">
      <p className="text-muted-foreground">
        <span className="text-foreground">{RTS_LABEL[r.rts_type] ?? r.rts_type}</span>
        {r.normalised_address && ` · ${r.normalised_address}`}
        {r.is_reattemptable && (
          <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-info/10 text-info uppercase tracking-wide">
            retryable
          </span>
        )}
      </p>
      {/* The walker's own words. rts_type is a dropdown value; this is what
          they actually wrote, and it is the part that explains the day to them
          a week later. */}
      {r.rts_explanation && (
        <p className="text-muted-foreground/80 italic">{r.rts_explanation}</p>
      )}
    </div>
  );
}

export default function RecentDaysSection() {
  // 0 = this week, -1 = last week. Capped at 0: there is no history for days
  // that have not happened.
  const [offset, setOffset] = useState(0);
  const [days, setDays] = useState<AssignmentDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const { start, end } = weekBounds(offset);

  useEffect(() => {
    setLoading(true);
    setError(null);
    axiosClient.get<AssignmentHistoryResponse>('/assignment-history/me', {
      params: { start_date: ymdOf(start), end_date: ymdOf(end) },
    })
      .then(({ data }) => setDays(data.days))
      .catch(e => setError(errorText(e, 'Could not load your recent days.')))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  // Silent on failure, matching MyPerformanceCard: a stats section must not
  // error the account page around it.
  if (error) return null;

  return (
    <div className="mt-4 pt-4 border-t border-border">
      <h3 className="text-sm font-semibold text-foreground mb-2">Recent days</h3>

      {/* Week navigation. Next is disabled at offset 0 rather than hidden, so
          the control does not move as you step between weeks. */}
      <div className="flex items-center justify-between mb-2.5">
        <button
          onClick={() => setOffset(o => o - 1)}
          className="px-2 py-0.5 rounded border border-border text-foreground
                     hover:bg-accent/30 transition-colors"
          aria-label="Previous week"
        >
          ‹
        </button>
        <span className="text-sm font-semibold text-foreground">
          {weekLabel(offset, start, end)}
        </span>
        <button
          onClick={() => setOffset(o => Math.min(0, o + 1))}
          disabled={offset >= 0}
          className="px-2 py-0.5 rounded border border-border text-foreground
                     hover:bg-accent/30 transition-colors disabled:opacity-30
                     disabled:hover:bg-transparent"
          aria-label="Next week"
        >
          ›
        </button>
      </div>

      {/* The week's shape, immediately under the picker it belongs to. */}
      {!loading && days && days.length > 0 && <WeekChart days={days} start={start} />}

      {loading ? (
        <p className="text-[11px] text-muted-foreground italic py-2 text-center">Loading…</p>
      ) : !days || days.length === 0 ? (
        /* An empty week is a real answer — "you did not work" — and must not
           render as a missing section the way the 30-day view did. */
        <p className="text-[11px] text-muted-foreground italic py-2 text-center">
          No assignments {offset === 0 ? 'yet this week' : 'that week'}.
        </p>
      ) : (
        <div className="space-y-2.5">
          {days.map(d => <DayRow key={`${d.route_date}-${d.truck_name ?? ''}`} day={d} />)}
        </div>
      )}
    </div>
  );
}
