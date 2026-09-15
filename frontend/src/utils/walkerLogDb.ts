/** Local-only storage for the manual walker/route tracker.
 *
 *  DELIBERATELY NOT the AsheFlow backend. This is a research/comparison
 *  instrument: hand-entered observations that get compared AGAINST what the
 *  production sort produced. Writing them into `routes` / `tote_addresses`
 *  would put unverified manual data in the same tables the sort reads, and
 *  there would be no way to tell an observation from a system fact afterwards.
 *
 *  So: IndexedDB, this browser, no company_id, no auth, no network. Export to
 *  JSON or CSV is the only way data leaves — which is also the analysis path.
 *
 *  IndexedDB rather than localStorage because a day of routes with tote
 *  addresses and RTS lists is well past localStorage's ~5MB and its
 *  synchronous API blocks the render thread on every write.
 */

const DB_NAME = 'asheflow_walker_log';
const DB_VERSION = 6;
const STORE = 'walker_days';
/** Routes built before anyone picked them up, keyed by date.
 *
 *  A separate store rather than a synthetic "unassigned" walker-day: that
 *  pseudo-walker would land in listByDate, in knownNames, in the roster's
 *  logged-check and in every CSV row, and each of those would need a special
 *  case to exclude it. A route with no walker is a different KIND of record, so
 *  it gets its own place. */
const UNCLAIMED = 'unclaimed_routes';
/** The crew working a given date — who is on the truck today.
 *
 *  Separate from walker-days because a walker is on the crew BEFORE they have
 *  logged anything: on a build-first morning the routes exist and the crew list
 *  is how you know who may claim them. Deriving the crew from "walkers with a
 *  saved day" is circular — nobody can be picked until they already have a
 *  record, which is the gap this closes.
 *
 *  Seeded from the manifest on a seeded date, editable on every date. */
const CREW = 'crew';
/** Manifests imported at RUNTIME from a workbook, keyed `${date}|${btr}`.
 *
 *  Separate from the compile-time seeds in walkerLogSeed.ts because those are
 *  fixtures baked into the bundle, and a walker in the field has a new workbook
 *  every morning that nobody is going to rebuild the app for. Same shape, so
 *  seedFor() can serve either.
 *
 *  Keyed by date AND btr: one workbook holds a whole fleet (ADR-411), and each
 *  truck has its own bags and its own crew. */
const MANIFESTS = 'manifests';
/** Which BTR the user is working on a given date. One row per date. */
const ACTIVE_BTR = 'active_btr';
/** Dates the user explicitly cleared.
 *
 *  Needed because the compile-time seeds in walkerLogSeed.ts are part of the
 *  BUNDLE — there is no row to delete. Without a tombstone, "Clear day" on a
 *  seeded date wiped the stored rows and the fixture immediately supplied its
 *  bags and crew again, so the clear looked like it had failed. */
const CLEARED = 'cleared_dates';
/** Address profiles — the second dataset (see addressProfile.ts).
 *
 *  Its own store rather than a field on the walker day: a profile is a fact
 *  about a BUILDING, collected with or without a route open, and hanging it off
 *  a walker-day would make it unreachable on any day that walker did not work. */
const PROFILES = 'address_profiles';

import { hydrateProfile } from './addressProfile';
import type { AddressProfile } from './addressProfile';

/** One RTS'd package: a real TBA plus why it came back. */
export interface LogRTS {
  tba: string;
  code: string;
  reason: string;
}

/** One tote and the addresses it carried.
 *
 *  The `stop*` fields come from the BTR workbook, not from the walker. They are
 *  the manifest's claim about this bag — which WE-stop it belonged to, and how
 *  many packages/OVs that stop carried. Kept on the tote so a route's manifest
 *  load can be totalled and set against the walker's own difficulty rating,
 *  which is the comparison this whole log exists to make.
 *
 *  Undefined on a hand-added tote — absent means "no manifest row", which is
 *  different from a manifest row that said zero. */
export interface LogTote {
  bag_id: string;
  addresses: string[];
  sort_zone?: string;
  stop?: string;
  stop_package_count?: number;
  stop_ov_count?: number;
  /** Bags the manifest put in this stop. A route holding fewer than this means
   *  the stop was SPLIT across walkers — the thing pre-grouping would hide. */
  stop_bag_count?: number;
}

/** A bag from the imported workbook that no walker-route has claimed yet. */
export interface UnassignedBag extends Required<Omit<LogTote, 'addresses' | 'sort_zone'>> {
  sort_zone: string;
}

/** Sizes an OV can be, matching OV_SIZES in the production model
 *  (`backend/app/models/workforce_ov.py`). Ordered smallest to largest — the
 *  order is meaningful, since size is what an OV costs the cart. */
export const OV_SIZES = ['XS', 'S', 'M', 'L', 'XL'] as const;
export type OVSize = typeof OV_SIZES[number];

/** One oversized package on a route.
 *
 *  An OV is ONE package too large to ride inside a tote, so it is its own unit
 *  rather than an entry in a tote's address list — the same call the production
 *  model makes (ADR-400 A4). Folding it into a tote would overstate that tote's
 *  contents and lose the size, which is the only thing that says what the OV
 *  actually costs the walker to carry.
 *
 *  Unlike a bag there is no printed label to pick from: the BTR sheet gives a
 *  COUNT and a sort zone per stop, not identities. So `ov_id` is typed by hand
 *  (the OV#### the station wrote on it, or anything that identifies it) and may
 *  be blank — an OV with an address and no id is still a real delivery.
 *
 *  One address, not a list: an OV is one package going to one place. */
export interface LogOV {
  ov_id: string;
  size: OVSize | '';
  address: string;
  /** Sort zone off the sheet (e.g. "B-16.1T"), typed or left blank. */
  sort_zone: string;
}

export interface LogRoute {
  /** DAY-WIDE UNIQUE IDENTIFIER, never a per-walker counter.
   *
   *  A route is a thing the day produced; a walker is who ended up carrying it.
   *  Those are separate facts, so the number is allocated once against the DATE
   *  and never changes — not when the route is claimed, not when it is handed
   *  to another walker, not when an earlier route is deleted.
   *
   *  This is a correction to the original reading of "count of routes + 1",
   *  which was implemented as 1..n per walker and renumbered on delete. That
   *  made the id unstable: route 2 became route 1 when route 1 was deleted, so
   *  two exports of the same day disagreed about which route was which, and a
   *  route handed from one walker to another silently changed identity. */
  route_id: number;
  totes: LogTote[];
  /** "HH:MM" local, or '' when not yet recorded. Paired with the day's date. */
  route_start: string;
  route_end: string;
  /** Walker's own rating — free choice from DIFFICULTIES. */
  difficulty: string;
  rts: LogRTS[];
  /** Oversized packages carried on this route. Optional so days logged before
   *  OVs existed still load — absent means "not recorded", not "none". */
  ovs?: LogOV[];
  notes: string;
}

export interface WalkerDay {
  /** `${date}|${name}` — one row per walker per date, so re-entering the same
   *  walker on the same day edits rather than duplicates. */
  id: string;
  date: string;          // YYYY-MM-DD
  name: string;
  arrival_time: string;  // "HH:MM"
  departure_time: string;
  routes: LogRoute[];
  updated_at: string;    // ISO, for export provenance
}

/** The date's unclaimed routes, passed to toCSV so they are not lost from the
 *  export. Null when there are none, or when exporting a day that had none. */
export type UnclaimedForExport = { date: string; routes: LogRoute[] } | null;

export const DIFFICULTIES = ['easy', 'moderate', 'hard', 'brutal'] as const;

/** The system's RTS reasons, verbatim from `backend/app/models/rts.py`
 *  (RTS_TYPES) with the labels used by the mobile MyRoute screen.
 *
 *  NO 'other'. An earlier version of this file invented one, which would have
 *  produced observations that cannot be matched against a real RTSPackage row
 *  — the whole point of this log is comparability, and a code the system
 *  cannot express is not comparable to anything.
 *
 *  `reattemptable` mirrors _REATTEMPTABLE_TYPES: the server derives it from the
 *  type and never takes it from a client, so it is shown here as information,
 *  not as something to tick. */
export const RTS_CODES = [
  { value: 'no_access',                          label: 'No access',                          reattemptable: true },
  { value: 'business_closed',                    label: 'Business closed',                    reattemptable: true },
  { value: 'package_damaged',                    label: 'Package damaged',                    reattemptable: false },
  { value: 'inclement_weather',                  label: 'Inclement weather',                  reattemptable: true },
  { value: 'customer_requested_future_delivery', label: 'Customer requested future delivery', reattemptable: false },
  { value: 'customer_cancelled_order',           label: 'Customer cancelled order',           reattemptable: false },
] as const;

export const rtsLabel = (code: string): string =>
  RTS_CODES.find((c) => c.value === code)?.label ?? code;

export const dayId = (date: string, name: string): string =>
  `${date}|${name.trim().toLowerCase()}`;

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: 'id' });
        // Listing is always "show me a date", never a full scan.
        store.createIndex('by_date', 'date', { unique: false });
        store.createIndex('by_name', 'name', { unique: false });
      }
      // v2. Guarded by the same contains() check as above so an existing
      // database gains the store on open instead of needing a reset.
      if (!db.objectStoreNames.contains(UNCLAIMED)) {
        db.createObjectStore(UNCLAIMED, { keyPath: 'date' });
      }
      // v3.
      if (!db.objectStoreNames.contains(CREW)) {
        db.createObjectStore(CREW, { keyPath: 'date' });
      }
      // v4.
      if (!db.objectStoreNames.contains(MANIFESTS)) {
        const st = db.createObjectStore(MANIFESTS, { keyPath: 'id' });
        st.createIndex('by_date', 'date', { unique: false });
      }
      if (!db.objectStoreNames.contains(ACTIVE_BTR)) {
        db.createObjectStore(ACTIVE_BTR, { keyPath: 'date' });
      }
      // v5.
      if (!db.objectStoreNames.contains(CLEARED)) {
        db.createObjectStore(CLEARED, { keyPath: 'date' });
      }
      // v6.
      if (!db.objectStoreNames.contains(PROFILES)) {
        const st = db.createObjectStore(PROFILES, { keyPath: 'id' });
        st.createIndex('by_date', 'date', { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Wraps one transaction so callers never juggle onsuccess/onerror. */
async function tx<T>(
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => IDBRequest<T>,
  storeName: string = STORE,
): Promise<T> {
  const db = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const t = db.transaction(storeName, mode);
      const req = fn(t.objectStore(storeName));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

export const putDay = (day: WalkerDay): Promise<IDBValidKey> =>
  tx('readwrite', (s) => s.put({ ...day, updated_at: new Date().toISOString() }));

export const getDay = (id: string): Promise<WalkerDay | undefined> =>
  tx('readonly', (s) => s.get(id) as IDBRequest<WalkerDay | undefined>);

export const deleteDay = (id: string): Promise<undefined> =>
  tx('readwrite', (s) => s.delete(id) as IDBRequest<undefined>);

export const listByDate = (date: string): Promise<WalkerDay[]> =>
  tx('readonly', (s) => s.index('by_date').getAll(date) as IDBRequest<WalkerDay[]>);

export const listAll = (): Promise<WalkerDay[]> =>
  tx('readonly', (s) => s.getAll() as IDBRequest<WalkerDay[]>);

/** The date's unclaimed routes — built, but nobody has picked them up yet. */
export async function getUnclaimed(date: string): Promise<LogRoute[]> {
  const row = await tx<{ date: string; routes: LogRoute[] } | undefined>(
    'readonly', (s) => s.get(date) as IDBRequest<{ date: string; routes: LogRoute[] } | undefined>,
    UNCLAIMED,
  );
  return row?.routes ?? [];
}

/** Every date that has unclaimed routes. Used by export, which spans dates. */
export const listAllUnclaimed = (): Promise<{ date: string; routes: LogRoute[] }[]> =>
  tx('readonly', (s) => s.getAll() as IDBRequest<{ date: string; routes: LogRoute[] }[]>, UNCLAIMED);

export async function putUnclaimed(date: string, routes: LogRoute[]): Promise<void> {
  await tx('readwrite', (s) => s.put({ date, routes }), UNCLAIMED);
}

/** Removes every WALKER record for a date: walker-days, unclaimed routes, and
 *  the crew. Leaves the imported load sheet in place.
 *
 *  This is "the people were wrong" — a mis-read crew screenshot, or a morning
 *  logged against the wrong date. The workbook is still the right workbook, and
 *  re-importing it would be pointless work. */
export async function clearWalkers(date: string): Promise<{ days: number; routes: number }> {
  const days = await listByDate(date);
  for (const d of days) await deleteDay(d.id);

  const unclaimed = await getUnclaimed(date);
  if (unclaimed.length > 0) await putUnclaimed(date, []);

  // [] rather than a delete: an empty crew is a deliberate state that must win
  // over the seeded roster, and removing the row would let the seed reappear.
  await putCrew(date, []);

  return { days: days.length, routes: unclaimed.length };
}

/** An imported manifest. Structurally identical to a compile-time Seed — the
 *  page resolves either without caring which it got. */
export interface StoredManifest {
  /** `${date}|${btr}` */
  id: string;
  date: string;
  btr: string;
  anchor: string;
  stops: unknown[];
  bags: unknown[];
  /** Crew read off a screenshot, or typed. Empty when none was imported. */
  crew: string[];
  imported_at: string;
}

export const manifestId = (date: string, btr: string) => `${date}|${btr}`;

export const putManifest = (m: Omit<StoredManifest, 'id' | 'imported_at'>): Promise<IDBValidKey> =>
  tx('readwrite', (s) => s.put({
    ...m, id: manifestId(m.date, m.btr), imported_at: new Date().toISOString(),
  }), MANIFESTS);

export const getManifest = (date: string, btr: string): Promise<StoredManifest | undefined> =>
  tx('readonly', (s) => s.get(manifestId(date, btr)) as IDBRequest<StoredManifest | undefined>, MANIFESTS);

/** Every manifest imported for a date — one per BTR in the workbook. */
export const manifestsForDate = (date: string): Promise<StoredManifest[]> =>
  tx('readonly', (s) => s.index('by_date').getAll(date) as IDBRequest<StoredManifest[]>, MANIFESTS);

export const deleteManifest = (date: string, btr: string): Promise<undefined> =>
  tx('readwrite', (s) => s.delete(manifestId(date, btr)) as IDBRequest<undefined>, MANIFESTS);

/** Removes EVERYTHING for a date, imported load sheets included.
 *
 *  This is "start the day over" — the wrong workbook, or a session worth
 *  abandoning wholesale. The manifests go too, so the date is left exactly as
 *  it was before anything was imported.
 *
 *  The crew row is DELETED here rather than emptied, unlike clearWalkers: with
 *  the manifest gone there is nothing date-specific left to preserve, and a
 *  lingering empty row would suppress a seeded roster on a date the user has
 *  returned to a blank slate. */
export async function clearDate(date: string): Promise<{
  days: number; routes: number; manifests: number;
}> {
  const r = await clearWalkers(date);

  const manifests = await manifestsForDate(date);
  for (const m of manifests) await deleteManifest(date, m.btr);
  await tx('readwrite', (s) => s.delete(date) as IDBRequest<undefined>, CREW);
  await tx('readwrite', (s) => s.delete(date) as IDBRequest<undefined>, ACTIVE_BTR);
  // Tombstone: the bundled fixture must not resurrect what was just cleared.
  await tx('readwrite', (s) => s.put({ date }), CLEARED);

  return { ...r, manifests: manifests.length };
}

/** Address profiles for a date.
 *
 *  Hydrated on the way out: IndexedDB has no migrations, so a record written
 *  before a field existed simply lacks it, and the compiler cannot see that.
 *  Closing the gap HERE means everything downstream can trust the type. */
export const profilesForDate = async (date: string): Promise<AddressProfile[]> =>
  (await tx('readonly', (s) => s.index('by_date').getAll(date) as IDBRequest<AddressProfile[]>, PROFILES))
    .map(hydrateProfile);

export const allProfiles = async (): Promise<AddressProfile[]> =>
  (await tx('readonly', (s) => s.getAll() as IDBRequest<AddressProfile[]>, PROFILES))
    .map(hydrateProfile);

export const putProfile = (p: AddressProfile): Promise<IDBValidKey> =>
  tx('readwrite', (s) => s.put({ ...p, updated_at: new Date().toISOString() }), PROFILES);

export const deleteProfile = (id: string): Promise<undefined> =>
  tx('readwrite', (s) => s.delete(id) as IDBRequest<undefined>, PROFILES);

/** Was this date explicitly cleared? Suppresses the bundled fixture. */
export const isDateCleared = (date: string): Promise<boolean> =>
  tx('readonly', (s) => s.get(date) as IDBRequest<{ date: string } | undefined>, CLEARED)
    .then((r) => r !== undefined);

/** Every date the user cleared, so the page can check without a query per row. */
export const clearedDates = (): Promise<string[]> =>
  tx('readonly', (s) => s.getAllKeys() as IDBRequest<IDBValidKey[]>, CLEARED)
    .then((k) => k.map(String));

/** Undoes the tombstone — used when something is imported for the date again. */
export const unclearDate = (date: string): Promise<undefined> =>
  tx('readwrite', (s) => s.delete(date) as IDBRequest<undefined>, CLEARED);

/** The BTR being worked on a date. Null when nothing has been chosen. */
export async function getActiveBtr(date: string): Promise<string | null> {
  const row = await tx<{ date: string; btr: string } | undefined>(
    'readonly', (s) => s.get(date) as IDBRequest<{ date: string; btr: string } | undefined>,
    ACTIVE_BTR,
  );
  return row?.btr ?? null;
}

export const setActiveBtr = (date: string, btr: string): Promise<IDBValidKey> =>
  tx('readwrite', (s) => s.put({ date, btr }), ACTIVE_BTR);

/** The crew saved against a date, or null when none has been saved yet.
 *
 *  Null and [] mean different things: null is "never set up, fall back to the
 *  seeded roster", [] is "deliberately emptied". Collapsing them would make
 *  removing the last walker silently restore all ten. */
export async function getCrew(date: string): Promise<string[] | null> {
  const row = await tx<{ date: string; walkers: string[] } | undefined>(
    'readonly', (s) => s.get(date) as IDBRequest<{ date: string; walkers: string[] } | undefined>,
    CREW,
  );
  return row ? row.walkers : null;
}

export async function putCrew(date: string, walkers: string[]): Promise<void> {
  await tx('readwrite', (s) => s.put({ date, walkers }), CREW);
}

export const listAllCrews = (): Promise<{ date: string; walkers: string[] }[]> =>
  tx('readonly', (s) => s.getAll() as IDBRequest<{ date: string; walkers: string[] }[]>, CREW);

/** Every walker name this log has ever seen — from a logged day OR from any
 *  date's crew.
 *
 *  Crews matter here, not just days: a walker added to Monday's crew who never
 *  got a route has no walker-day, so a names list built only from `listAll()`
 *  forgets they exist and they must be retyped from scratch on Tuesday. The
 *  roster is the set of PEOPLE; a walker-day is only the record of one shift
 *  they worked.
 *
 *  Powers the pickers' "walked before" section, so a name entered once is one
 *  keystroke forever after and does not drift into a second spelling. */
export async function knownNames(): Promise<string[]> {
  const [days, crews] = await Promise.all([listAll(), listAllCrews()]);
  const names = [
    ...days.map((d) => d.name),
    ...crews.flatMap((c) => c.walkers),
  ].map((n) => n.trim()).filter(Boolean);

  // De-duplicate case-insensitively, keeping the first spelling seen, so
  // "devon riley" typed later does not become a second person.
  const seen = new Map<string, string>();
  for (const n of names) if (!seen.has(n.toLowerCase())) seen.set(n.toLowerCase(), n);
  return [...seen.values()].sort((a, b) => a.localeCompare(b));
}

export const nowHM = (): string => {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

/** Minutes between two "HH:MM" values; null when either is blank.
 *  Crossing midnight is treated as +1 day so a night shift does not read
 *  negative — a route ending 00:20 after a 23:40 start is 40 minutes. */
export function durationMin(start: string, end: string): number | null {
  if (!start || !end) return null;
  const [sh, sm] = start.split(':').map(Number);
  const [eh, em] = end.split(':').map(Number);
  if ([sh, sm, eh, em].some((n) => Number.isNaN(n))) return null;
  let mins = eh * 60 + em - (sh * 60 + sm);
  if (mins < 0) mins += 24 * 60;
  return mins;
}

export const fmtDuration = (mins: number | null): string =>
  mins === null ? '—' : `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`;

/** A tote with no manifest provenance. The page no longer creates these — totes
 *  are chosen from the day's manifest — but it is kept as the factory for a bag
 *  entered outside a manifest (a day with no workbook, or an import). */
/** The next free route number for a date, across every walker AND the
 *  unclaimed bucket. Max+1 rather than count+1: count+1 collides the moment a
 *  route is deleted (three routes, delete #2, count+1 = 3 which already
 *  exists), and a collision here means two different routes sharing an id. */
export function nextRouteId(days: WalkerDay[], unclaimed: LogRoute[]): number {
  let max = 0;
  for (const d of days) for (const r of d.routes) max = Math.max(max, r.route_id);
  for (const r of unclaimed) max = Math.max(max, r.route_id);
  return max + 1;
}

export const emptyTote = (bag_id = ''): LogTote => ({ bag_id, addresses: [] });

export const emptyOV = (): LogOV => ({ ov_id: '', size: '', address: '', sort_zone: '' });

export const emptyRoute = (route_id: number): LogRoute => ({
  route_id,
  totes: [],
  ovs: [],
  route_start: '',
  route_end: '',
  difficulty: '',
  rts: [],
  notes: '',
});

export const emptyDay = (date: string, name: string): WalkerDay => ({
  id: dayId(date, name),
  date,
  name: name.trim(),
  arrival_time: '',
  departure_time: '',
  routes: [],
  updated_at: new Date().toISOString(),
});

/** A route's manifest-side load, derived from the totes it holds.
 *
 *  Package and OV counts live on the STOP, not the bag, so a route holding two
 *  bags of a three-bag stop must not claim that stop's full package count. The
 *  counts are therefore apportioned per bag held (count / stop_bag_count) and
 *  rounded once at the end — which is why a split stop's packages sum back to
 *  roughly the original across the walkers who shared it, instead of being
 *  double-counted by each of them.
 *
 *  Returns null counts when NO tote on the route carries manifest data, so an
 *  entirely hand-entered route exports blank rather than a misleading 0. */
export function manifestLoad(r: LogRoute): {
  packages: number | null; ovs: number | null; stops: string[]; splitStops: string[];
} {
  const held = new Map<string, number>();
  for (const t of r.totes) if (t.stop) held.set(t.stop, (held.get(t.stop) ?? 0) + 1);

  let packages = 0, ovs = 0, seen = false;
  const splitStops: string[] = [];
  for (const [stop, n] of held) {
    const tote = r.totes.find((t) => t.stop === stop)!;
    const total = tote.stop_bag_count ?? n;
    const share = total > 0 ? n / total : 1;
    if (tote.stop_package_count !== undefined) { packages += tote.stop_package_count * share; seen = true; }
    if (tote.stop_ov_count !== undefined) { ovs += tote.stop_ov_count * share; seen = true; }
    if (n < total) splitStops.push(`${stop}(${n}/${total})`);
  }
  return {
    packages: seen ? Math.round(packages) : null,
    ovs: seen ? Math.round(ovs) : null,
    stops: [...held.keys()],
    splitStops,
  };
}

/** Drops rows the user added but never filled — an "+ RTS" click followed by a
 *  save exports as `::` and a blank tote as `BAG-4471 | `, which then reads as a
 *  real (empty-identifier) tote in a pivot and inflates every tote and RTS
 *  count. Blank rows are UI scaffolding, not observations, so they are stripped
 *  at the export boundary rather than blocked at entry — a half-entered row must
 *  still be allowed to sit there mid-typing. */
function clean(d: WalkerDay): WalkerDay {
  return {
    ...d,
    routes: d.routes.map((r) => ({
      ...r,
      totes: r.totes.filter((t) => t.bag_id.trim() || t.addresses.length > 0),
      rts: r.rts.filter((x) => x.tba.trim() || x.code.trim() || x.reason.trim()),
      ovs: (r.ovs ?? []).filter((o) => o.ov_id.trim() || o.address.trim() || o.size),
    })),
  };
}

/** One row per ROUTE — the grain the analysis actually compares on (duration,
 *  difficulty, tote count, RTS count per route). Tote and RTS detail is packed
 *  into cells rather than exploded, because exploding to one-row-per-address
 *  would multiply every route metric and quietly overcount them on a pivot. */
/** Column headers for the route-grain export. Shared by CSV and XLSX so the two
 *  formats cannot disagree about what column 12 means. */
export const EXPORT_COLUMNS = [
  'date', 'walker', 'arrival_time', 'departure_time', 'day_minutes',
  'route_id', 'route_start', 'route_end', 'route_minutes', 'difficulty',
  'tote_count', 'totes', 'address_count', 'addresses',
  'rts_count', 'rts',
  // Manifest side (from the BTR workbook) — the columns that make the
  // comparison possible: felt difficulty and actual minutes against the
  // package load the manifest said this route was carrying.
  'manifest_packages', 'manifest_ovs', 'stops', 'sort_zones', 'split_stops',
  // Recorded OVs — what the walker actually carried, against manifest_ovs,
  // which is what the sheet predicted.
  'ov_count', 'ovs',
  'notes',
] as const;

/** A cell keeps its type here rather than being stringified.
 *
 *  CSV throws types away — everything becomes text — but a spreadsheet must
 *  receive `route_minutes` as a NUMBER or it cannot average it, and a column of
 *  numbers-as-text silently breaks every formula pointed at it. That is the
 *  whole reason rows are built as values and only serialised at the end. */
export type Cell = string | number | null;

/** One row per ROUTE — the grain the analysis compares on (duration,
 *  difficulty, tote count, RTS count per route). Tote and RTS detail is packed
 *  into cells rather than exploded, because exploding to one-row-per-address
 *  would multiply every route metric and overcount it on a pivot. */
export function toRows(days: WalkerDay[], unclaimed: UnclaimedForExport = null): Cell[][] {
  const rows: Cell[][] = [];

  // A route still unclaimed at export time is a real finding — work that was
  // built and loaded and that nobody walked — so it exports with an empty
  // walker rather than vanishing. Filter `walker == ""` to isolate them.
  const source = days.map(clean);
  if (unclaimed && unclaimed.routes.length > 0) {
    source.push(clean({ ...emptyDay(unclaimed.date, ''), routes: unclaimed.routes }));
  }

  for (const d of source) {
    const dayMin = durationMin(d.arrival_time, d.departure_time);

    if (d.routes.length === 0) {
      rows.push([
        d.date, d.name, d.arrival_time, d.departure_time, dayMin,
        null, '', '', null, '',
        0, '', 0, '', 0, '',
        null, null, '', '', '',
        0, '',
        '',
      ]);
      continue;
    }

    for (const r of d.routes) {
      const addresses = r.totes.flatMap((t) => t.addresses);
      const m = manifestLoad(r);
      rows.push([
        d.date, d.name, d.arrival_time, d.departure_time, dayMin,
        r.route_id, r.route_start, r.route_end,
        durationMin(r.route_start, r.route_end), r.difficulty,
        r.totes.length,
        r.totes.map((t) => t.bag_id).join(' | '),
        addresses.length,
        addresses.join(' | '),
        r.rts.length,
        r.rts.map((x) => `${x.tba}:${x.code}:${x.reason}`).join(' | '),
        m.packages, m.ovs,
        m.stops.join(' | '),
        [...new Set(r.totes.map((t) => t.sort_zone).filter(Boolean))].join(' | '),
        m.splitStops.join(' | '),
        (r.ovs ?? []).length,
        (r.ovs ?? []).map((o) => `${o.ov_id || '?'}:${o.size || '?'}:${o.address}`).join(' | '),
        r.notes,
      ]);
    }
  }
  return rows;
}

/** CSV escape: quote always, double interior quotes. Addresses contain commas. */
const q = (v: Cell): string => `"${String(v ?? '').replace(/"/g, '""')}"`;

export function toCSV(days: WalkerDay[], unclaimed: UnclaimedForExport = null): string {
  return [
    EXPORT_COLUMNS.join(','),
    ...toRows(days, unclaimed).map((r) => r.map(q).join(',')),
  ].join('\n');
}

/** Hands the browser a file to save. Blob-first because a workbook is binary —
 *  stringifying it would corrupt it. */
export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  // Revoking immediately can cancel the download in some browsers; a tick is
  // enough for the click to have been dispatched.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export const download = (filename: string, content: string, mime: string): void =>
  downloadBlob(filename, new Blob([content], { type: mime }));

/** Import merges by id: re-importing an export updates those walker-days and
 *  leaves everything else alone, so two machines' exports can be combined. */
export async function importJSON(text: string): Promise<number> {
  const parsed: unknown = JSON.parse(text);
  const rows = Array.isArray(parsed) ? parsed : (parsed as { days?: unknown }).days;
  if (!Array.isArray(rows)) throw new Error('Expected a JSON array of walker-days.');

  let n = 0;
  for (const raw of rows) {
    const d = raw as Partial<WalkerDay>;
    if (!d || typeof d.date !== 'string' || typeof d.name !== 'string') continue;
    await putDay({
      ...emptyDay(d.date, d.name),
      ...d,
      id: dayId(d.date, d.name),
      routes: Array.isArray(d.routes) ? d.routes : [],
    } as WalkerDay);
    n += 1;
  }

  // Unclaimed routes ride along in the export, so they must come back — an
  // import that silently dropped them would return the bags to the pool and
  // let them be handed out a second time.
  const bucket = (parsed as { unclaimed?: unknown }).unclaimed;
  if (Array.isArray(bucket)) {
    for (const raw of bucket) {
      const u = raw as { date?: unknown; routes?: unknown };
      if (typeof u?.date !== 'string' || !Array.isArray(u.routes)) continue;
      const existing = await getUnclaimed(u.date);
      const have = new Set(existing.map((r) => r.route_id));
      const merged = [...existing, ...(u.routes as LogRoute[]).filter((r) => !have.has(r.route_id))];
      await putUnclaimed(u.date, merged);
    }
  }
  return n;
}
