/** Address profile collection — the second dataset this log gathers.
 *
 *  Mirrors `BuildingProfile` in the backend, field for field where it matters,
 *  so what is collected here can be compared against (or loaded into) the real
 *  thing. The enums are copied from `backend/app/schemas/location_profile.py`
 *  rather than re-invented: a building_type this page accepts that the server
 *  rejects would make the whole collection worthless.
 *
 *  WHAT IS DELIBERATELY ABSENT. The production model carries a verification
 *  lifecycle (agreement counts, locking, library promotion), GeoClient
 *  resolution, and a decaying troublesome score. None of that belongs in a
 *  hand-collection tool: they are all things the SYSTEM derives from many
 *  submissions over time. This captures what a person standing at the door can
 *  actually observe.
 */

export const BUILDING_TYPES = [
  { value: 'walkup',           label: 'Walk-up',                    workload: 'high_touch' },
  { value: 'elevator',         label: 'Elevator building',          workload: 'standard' },
  { value: 'doorman',          label: 'Doorman',                    workload: 'bulk_drop' },
  { value: 'receptionist',     label: 'Receptionist',               workload: 'bulk_drop' },
  { value: 'mailroom',         label: 'Mailroom',                   workload: 'bulk_drop' },
  { value: 'biz_front',        label: 'Business — front door',      workload: 'standard' },
  { value: 'biz_freight',      label: 'Business — freight entrance', workload: 'high_wait' },
  { value: 'biz_security',     label: 'Business — security desk',   workload: 'high_touch' },
  { value: 'biz_loading_dock', label: 'Business — loading dock',    workload: 'bulk_drop' },
] as const;

export type BuildingType = typeof BUILDING_TYPES[number]['value'];

export const WORKLOAD_CLASSES = [
  { value: 'bulk_drop',  label: 'Bulk drop',  hint: 'hand off many at once' },
  { value: 'standard',   label: 'Standard',   hint: 'normal door-to-door' },
  { value: 'high_touch', label: 'High touch', hint: 'stairs, many doors' },
  { value: 'high_wait',  label: 'High wait',  hint: 'queue, dock, sign-in' },
] as const;

/** What a walker is expected to do at this door. Verbatim from the backend's
 *  BUILDING_TYPE_PROTOCOL — shown as a reminder while profiling, so the person
 *  entering it knows what the classification will mean downstream. */
export const TYPE_PROTOCOL: Record<string, string> = {
  mailroom:         'Photo of packages in mail room.',
  receptionist:     "Get the receptionist's name.",
  doorman:          'Hand to doorman. Get name if required.',
  walkup:           'Photo at front door.',
  elevator:         'Photo at front door.',
  biz_front:        "Photo at front door or get receptionist's name.",
  biz_freight:      "Photo at front door or get receptionist's name.",
  biz_security:     'Bring ID. Photo at front door.',
  biz_loading_dock: "Photo at loading dock or get mail clerk's name.",
};

export const deriveWorkload = (t: string): string =>
  BUILDING_TYPES.find((b) => b.value === t)?.workload ?? 'standard';

export interface AddressProfile {
  /** `${date}|${address lowercased}` — one profile per address per collection
   *  day, so revisiting the same building edits rather than duplicates. */
  id: string;
  /** The date it was collected. Profiles are facts about a BUILDING, not a day,
   *  but the collection date is what lets a later analysis weight a fresh
   *  observation over a stale one. */
  date: string;
  /** As typed or scanned. Not normalised — GeoClient does that server-side, and
   *  guessing at canonical form here would produce addresses that match
   *  nothing. */
  address: string;
  building_type: BuildingType | '';
  /** Defaults from building_type, overridable: the mapping is a default, and a
   *  notoriously slow doorman is high_wait regardless of the door. */
  workload_class: string;
  /** Free text in the collector's words — the backend's raw_note. */
  note: string;
  /** Operating hours, "HH:MM" or ''. Feeds the reattempt bundler upstream. */
  opens_at: string;
  closes_at: string;
  break_start: string;
  break_end: string;
  /** Has this address caused trouble? The backend derives a decaying score from
   *  RTS events; a human can only say yes or no, so that is what is asked. */
  troublesome: boolean;
  /** Who collected it, so a later analysis can weight by observer. */
  collected_by: string;
  updated_at: string;
}

export const profileId = (date: string, address: string): string =>
  `${date}|${address.trim().toLowerCase()}`;

export const emptyProfile = (date: string, address = ''): AddressProfile => ({
  id: profileId(date, address),
  date,
  address,
  building_type: '',
  workload_class: '',
  note: '',
  opens_at: '', closes_at: '', break_start: '', break_end: '',
  troublesome: false,
  collected_by: '',
  updated_at: new Date().toISOString(),
});

/** Is there enough here to be worth keeping?
 *
 *  An address alone is not a profile — it is a note to self. The building type
 *  is the field every downstream consumer needs, so that is the bar. */
export const isUsable = (p: AddressProfile): boolean =>
  p.address.trim().length > 0 && p.building_type !== '';


/** Columns for the profile CSV. Named to match `BuildingProfile` so a later
 *  import maps straight across without a translation table. */
export const PROFILE_COLUMNS = [
  'normalised_address', 'building_type', 'workload_class',
  'raw_note', 'opens_at', 'closes_at', 'break_start', 'break_end',
  'troublesome', 'collected_by', 'collected_on', 'updated_at',
] as const;

/** CSV escape: quote always, double interior quotes. Addresses contain commas
 *  and notes contain everything. */
const q = (v: unknown): string => `"${String(v ?? '').replace(/"/g, '""')}"`;

/** One row per ADDRESS — its OWN file, not merged into the route export.
 *
 *  The route CSV is one row per delivery address ON a route; this is one row
 *  per BUILDING. Same-looking data, different grain, and concatenating them
 *  would produce a file where summing any column is wrong. Two files import
 *  cleanly into two tables; one mixed file imports into neither.
 *
 *  Incomplete profiles are dropped — `isUsable` is the bar, because a row with
 *  no building_type would arrive at the database as a NOT NULL violation.
 */
export function profilesToCSV(profiles: AddressProfile[]): string {
  const rows = [PROFILE_COLUMNS.join(',')];
  for (const p of profiles.filter(isUsable)) {
    rows.push([
      p.address.trim(),
      p.building_type,
      p.workload_class,
      p.note,
      p.opens_at, p.closes_at, p.break_start, p.break_end,
      // "true"/"false" rather than 1/0: unambiguous in every importer, and
      // Postgres casts it to boolean directly.
      p.troublesome ? 'true' : 'false',
      p.collected_by,
      p.date,
      p.updated_at,
    ].map(q).join(','));
  }
  return rows.join('\n');
}

// ── Addresses the campaign already had ───────────────────────────────────────

/** Loose key for "is this the same doorway", used ONLY for warning about
 *  duplicates — never for storage, never sent to the server.
 *
 *  The stored address stays exactly as typed (GeoClient normalises later,
 *  ADR-277), but a warning that only fires on an exact string match is nearly
 *  useless in the field: "380 W 33 ST" and "380 West 33rd Street" are one
 *  building and two strings. This folds the handful of variations people
 *  actually type — directions, street types, ordinal suffixes, punctuation —
 *  so the warning fires when it should.
 *
 *  Deliberately lossy. A false positive costs a dismissible warning; a false
 *  negative costs someone a walk to a door that was already done. */
export function doorKey(address: string): string {
  let s = address.toLowerCase();
  s = s.replace(/[.,#]/g, ' ');
  s = s.replace(/\b(\d+)(st|nd|rd|th)\b/g, '$1');           // 33rd -> 33
  s = s.replace(/\b(north|south|east|west)\b/g, (m) => m[0]); // west -> w
  s = s.replace(/\b(street|st)\b/g, 'st');
  s = s.replace(/\b(avenue|ave|av)\b/g, 'ave');
  s = s.replace(/\b(boulevard|blvd)\b/g, 'blvd');
  s = s.replace(/\b(road|rd)\b/g, 'rd');
  s = s.replace(/\b(place|pl)\b/g, 'pl');
  s = s.replace(/\b(drive|dr)\b/g, 'dr');
  s = s.replace(/\b(lane|ln)\b/g, 'ln');
  s = s.replace(/\b(parkway|pkwy)\b/g, 'pkwy');
  s = s.replace(/\b(apartment|apt|unit|suite|ste)\b.*$/, ''); // unit is not the door
  return s.replace(/\s+/g, ' ').trim();
}

const KNOWN_KEY = 'walkerlog.knownAddresses';

/** Door keys the server reported as already-received, remembered per browser.
 *
 *  THIS IS NOT A CACHE OF THE DATABASE. It holds only addresses this device
 *  submitted and was told were duplicates — never a listing, never anything
 *  fetched. There is no public read path (ADR-415 D4) and this does not create
 *  one: the set cannot grow except by submitting an address you already typed.
 *
 *  localStorage, not IndexedDB: it is a small set of short strings, and losing
 *  it degrades a warning rather than losing data. */
export function knownAddresses(): Set<string> {
  try {
    const raw = localStorage.getItem(KNOWN_KEY);
    return new Set<string>(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();          // private window, cleared storage, bad JSON
  }
}

export function rememberKnown(addresses: string[]): void {
  if (addresses.length === 0) return;
  try {
    const set = knownAddresses();
    for (const a of addresses) set.add(doorKey(a));
    localStorage.setItem(KNOWN_KEY, JSON.stringify([...set]));
  } catch {
    /* storage unavailable — the warning simply stays local-only */
  }
}
