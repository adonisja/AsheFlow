/**
 * Wire types for My Stats (ADR-271). MIRRORS `frontend/src/api/types.ts`.
 *
 * Mobile has no shared types module — each screen declares what it reads — so
 * the stats types live here beside the code that uses them. Both surfaces are
 * hand-maintained against the same Pydantic schemas; there is no codegen, so a
 * backend field change lands in TWO files and must be made in the same commit.
 */

export interface DayStat {
  d: string;
  delivered: number;
  total: number;
  rts: number;
  missing: number;
  /** Packages the person brought back DAMAGED — a SUBSET of `rts`, since
   *  package_damaged is one of the six RTS_TYPES. Never add the two. */
  damaged: number;
  /** Damage reported on their truck pre-delivery. A different event from
   *  `damaged`; the UI must not sum them. Populated for driver/captain only. */
  truck_damaged: number;
  effort: string | null;
  /** Per-day reason mix, {abbreviated_rts_type: count}. Folded into the bulk
   *  payload so every level's donut is a client-side sum (ADR-271 B). */
  rz: Record<string, number>;
  /** Roll-call status for the day, or null if none recorded. */
  rc: string | null;
}

export interface StatsSeries {
  start_date: string;
  /** Always yesterday. */
  end_date: string;
  role: string;
  days: DayStat[];
}

export interface LifetimeTotals {
  /** ADR-305: NULL in workforce mode when no route has been Flex-scanned —
   *  delivered is DERIVED there (carried − rts − missing), and an empty scanned
   *  set has no figure. Render an em-dash, never 0: "delivered nothing" is a
   *  different claim about a real person. Always a number in full mode. */
  delivered: number | null;
  rts: number;
  missing: number;
  damaged: number;
  truck_damaged: number;
  trips: number;
  /** Null, never 0, when nothing has been attempted. */
  success_pct: number | null;
  /** ADR-305 D3: routes with no Flex count, excluded from BOTH delivered and
   *  attempted. > 0 means these figures cover a SUBSET of the walker's routes,
   *  and the UI must say so — "93.9% over 2 of 3 routes", not a bare 93.9%. */
  routes_excluded_unscanned: number;
}

/** Per calendar year, ALL TIME — computed server-side because the daily series
 *  is capped at 24 months and the lifetime chart is year-over-year. */
export interface YearStat {
  year: number;
  delivered: number;
  total: number;
  rts: number;
  missing: number;
  damaged: number;
  truck_damaged: number;
}

export interface MyStats {
  lifetime: LifetimeTotals;
  years: YearStat[];
  series: StatsSeries;
}

/** One block worked in the selected period. `block_key` survives ADR-219's
 *  address purge, so it carries no PII. */
export interface BlockStat {
  block_key: string;
  stops: number;
  delivered: number;
  rts: number;
  /** Null, never 0, when nothing was attempted there. */
  rts_rate: number | null;
}

export interface Attendance {
  present: number;
  late: number;
  ncns: number;
  total: number;
  /** Null when nothing was recorded — "no roll calls" is not "0% attendance". */
  rate: number | null;
}

export interface ReasonStat {
  rts_type: string;
  count: number;
}

export interface PeriodExtras {
  start_date: string;
  end_date: string;
  top_blocks: BlockStat[];
  attendance: Attendance;
  reasons: ReasonStat[];
  /** False for driver/captain: blocks come from the stop's executor and a
   *  driver does not carry, so HIDE the panel rather than render it empty. */
  blocks_apply: boolean;
}

export interface HistoryCrewMember {
  name: string;
  /** The SLOT held that day, not the job title — a captain may ride as a
   *  walker (ADR-256 D2). */
  role: string;
}

export interface HistoryRTSDetail {
  tba_number: string;
  rts_type: string;
  rts_explanation: string;
  is_reattemptable: boolean;
  /** Null once ADR-219's 48h window has closed. Not an error. */
  normalised_address: string | null;
}

/**
 * A paired trainee's day, as their trainer sees it (ADR-269). Counts are the
 * trainee's OWN executed stops, never the truck total.
 */
export interface SupervisedDay {
  employee_id: string;
  name: string;
  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  rts_rate: number | null;
  /** Prefer this over rts_rate — same difficulty confound as the parent day. */
  rts_rate_vs_class: number | null;
  rts_details: HistoryRTSDetail[];
}

/** One day's detail — truck, crew, RTS rows. Fetched on demand: the ~2 KB/day
 *  part deliberately kept out of the cached series (ADR-271 H). */
export interface AssignmentDay {
  route_date: string;
  truck_name: string | null;
  slot_role: string;
  crew: HistoryCrewMember[];
  route_numbers: number[];

  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;

  effort_class: string | null;
  rts_rate: number | null;
  /** rts_rate divided by the company rate for the SAME effort_class.
   *  1.0 = exactly typical. ALWAYS prefer this over rts_rate when comparing
   *  people — raw rate is confounded by difficulty (2.10% easy vs 10.81%
   *  heavy, a 5x spread the walker does not control). */
  rts_rate_vs_class: number | null;

  rts_details: HistoryRTSDetail[];
  /** 'street' while addresses survive, 'block' after ADR-219 nulls them. */
  address_detail: 'street' | 'block';
  /** Whose numbers the counts are: 'truck' for driver/captain, 'own' for
   *  walker/trainer/trainee. MUST be labelled in the UI — a walker's 142 and
   *  a driver's 2,865 are different measurements. */
  counts_scope: 'truck' | 'own';
  /** OPTIONAL ON THE WIRE. The client ships ahead of the backend it talks to,
   *  so during a deploy window this field is absent. Typing it as required
   *  turned `day.supervised.map()` into a hard render crash for EVERY user,
   *  not just trainers (ADR-269 addendum). Read as `day.supervised ?? []`. */
  supervised?: SupervisedDay[];
}
