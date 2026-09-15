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

/** The building taxonomy (ADR-418).
 *
 *  Mirrors `backend/app/schemas/building_taxonomy.py`. Hand-maintained — there
 *  is no codegen — so a type added there must be added here or the collector
 *  cannot record it.
 *
 *  `category` groups the options in the picker. It is NOT sent: the server
 *  derives it from the type, because two independently supplied fields drift
 *  and a row claiming residential/loading_dock is worse than no row.
 */
export const BUILDING_CATEGORIES = [
  { value: 'residential', label: 'Residential' },
  { value: 'commercial',  label: 'Commercial' },
] as const;

export const BUILDING_TYPES = [
  // Residential
  { value: 'walkup',            label: 'Walk-up',              category: 'residential' },
  { value: 'elevator',          label: 'Elevator',             category: 'residential' },
  { value: 'doorman_reception', label: 'Doorman / Reception',  category: 'residential' },
  { value: 'mailroom',          label: 'Mailroom',             category: 'residential' },
  { value: 'lockers',           label: 'Lockers',              category: 'residential' },
  { value: 'public_housing',    label: 'Public housing',       category: 'residential' },
  // Commercial
  { value: 'storefront_reception',  label: 'Store front: reception',   category: 'commercial' },
  { value: 'storefront_front_door', label: 'Store front: front door',  category: 'commercial' },
  { value: 'freight',               label: 'Freight',                  category: 'commercial' },
  { value: 'loading_dock',          label: 'Loading dock / service',   category: 'commercial' },
  { value: 'loading_dock_mailroom', label: 'Loading dock: mailroom',   category: 'commercial' },
] as const;

export type BuildingType = typeof BUILDING_TYPES[number]['value'];

/** Workload is a SET and is COLLECTED, not derived.
 *
 *  It used to be computed from building type, which is a guess dressed as
 *  data: right often enough to be believed, wrong often enough to mislead. A
 *  doorman building that is also 20+ floors is genuinely both bulk drop and
 *  high-rise, which one value could not say.
 *
 *  `not_applicable` exists so "none of these" is something the collector
 *  SAID, distinguishable from a field they never reached — which is why an
 *  empty selection is an error rather than a silent blank. */
export const WORKLOAD_TAGS = [
  { value: 'bulk_drop',      label: 'Bulk drop',     hint: 'drop off many packages at once' },
  { value: 'door_to_door',   label: 'Door-to-door',  hint: "each package to the customer's door" },
  { value: 'high_rise',      label: 'High-rise',     hint: '20+ floors' },
  { value: 'high_wait',      label: 'High wait',     hint: 'queues, sign-in, dock areas' },
] as const;

/** Separate from WORKLOAD_TAGS because it is an answer ABOUT the others, and
 *  because it carries text: picking it without saying what it is records that
 *  the four tags were wrong without recording what is right. */
export const OTHER = 'other';

export type WorkloadTag = typeof WORKLOAD_TAGS[number]['value'] | typeof OTHER;

/** Tags that cannot be true of a given building type.
 *
 *  A walk-up is defined by having no elevator, which caps the floors and forces
 *  every package up the stairs one at a time — so it is neither a high-rise nor
 *  a bulk drop. Mirrors INCOMPATIBLE_WITH_TYPE in building_taxonomy.py; the
 *  client disables the boxes, the server rejects the pair. */
export const INCOMPATIBLE_WITH_TYPE: Record<string, readonly string[]> = {
  walkup: ['high_rise', 'bulk_drop'],
};

export const isIncompatible = (buildingType: string, tag: string): boolean =>
  (INCOMPATIBLE_WITH_TYPE[buildingType] ?? []).includes(tag);

/** Mirrors validate_workloads() on the server. Returns an error string, or
 *  null when the selection is valid. */
export function workloadError(
  tags: string[] | undefined,
  buildingType?: string,
  other?: string,
): string | null {
  // `tags` is typed as an array but arrives from IndexedDB, where a profile
  // saved before ADR-418 has no `workloads` key at all. TypeScript cannot see
  // that — stored data predates the type — so the undefined check is load
  // bearing, not defensive noise. Without it the whole page threw on mount
  // for anyone with an existing profile.
  if (!tags || tags.length === 0) {
    return 'Pick at least one workload, or “None of these apply”.';
  }
  if (tags.includes(OTHER) && !(other || '').trim()) {
    return 'Say what the other workload is.';
  }
  if (buildingType) {
    const clash = tags.filter((t) => isIncompatible(buildingType, t));
    if (clash.length > 0) {
      const label = BUILDING_TYPES.find((b) => b.value === buildingType)?.label ?? buildingType;
      const names = clash
        .map((t) => WORKLOAD_TAGS.find((w) => w.value === t)?.label ?? t)
        .join(' or ');
      return `A ${label.toLowerCase()} cannot also be ${names.toLowerCase()}.`;
    }
  }
  return null;
}

/** What a walker is expected to do at this door. Verbatim from the backend's
 *  BUILDING_TYPE_PROTOCOL — shown as a reminder while profiling, so the person
 *  entering it knows what the classification will mean downstream. */
export const TYPE_PROTOCOL: Record<string, string> = {
  walkup:                 'Photo at front door.',
  elevator:               'Photo at front door.',
  doorman_reception:      'Hand to doorman or receptionist. Get a name if required.',
  mailroom:               'Photo of packages in the mail room.',
  lockers:                'Scan into the locker bank. Photo of the locker number.',
  storefront_reception:   "Get the receptionist's name.",
  storefront_front_door:  "Photo at front door or get the receptionist's name.",
  freight:                'Use the freight entrance. Photo at the door.',
  loading_dock:           "Photo at the loading dock or get the clerk's name.",
  loading_dock_mailroom:  'Deliver through the dock to the mail room. Get a name.',
};

/** Added to the protocol when the door has a security desk. It is a flag
 *  rather than a type, so its instruction is additive too. */
export const SECURITY_DESK_PROTOCOL = 'Bring ID. This door has a security desk.';

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
  /** Does this door have a security desk? A FLAG, not a type — the old
   *  `biz_security` forced a false choice, so a loading dock with a security
   *  desk had to be filed as one or the other. */
  has_security_desk: boolean;
  /** Which workloads apply. A SET, and collected rather than derived: a
   *  doorman building that is also 20+ floors is genuinely both. Empty is
   *  invalid — `['not_applicable']` is how "none apply" is said. */
  workloads: WorkloadTag[];
  /** What the `other` tag means. Required when it is picked, empty otherwise. */
  workload_other: string;
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

/** Fills in fields added after a profile was stored.
 *
 *  IndexedDB has no migrations: a record written last week has last week's
 *  shape, and the compiler happily assumes otherwise. Everything that reads
 *  profiles out of storage passes them through here, so the gap is closed in
 *  ONE place rather than with optional chaining scattered at every use.
 *
 *  ADR-418 added `workloads` and `has_security_desk`. An older profile carried
 *  a single derived `workload_class`, which is NOT migrated into `workloads`:
 *  it was computed from the building type, never observed, and promoting a
 *  guess to a collected answer is exactly what that ADR set out to stop. Such
 *  a profile reads as incomplete and asks the collector for a real answer. */
export function hydrateProfile(p: AddressProfile): AddressProfile {
  return {
    ...p,
    workloads: p.workloads ?? [],
    workload_other: p.workload_other ?? '',
    has_security_desk: p.has_security_desk ?? false,
  };
}

export const profileId = (date: string, address: string): string =>
  `${date}|${address.trim().toLowerCase()}`;

export const emptyProfile = (date: string, address = ''): AddressProfile => ({
  id: profileId(date, address),
  date,
  address,
  building_type: '',
  has_security_desk: false,
  workloads: [],
  workload_other: '',
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
  p.address.trim().length > 0
  && p.building_type !== ''
  // ADR-418: workload is collected, not derived, so an unanswered workload is
  // an incomplete profile. `['not_applicable']` satisfies this — saying "none
  // apply" is an answer; leaving it blank is not.
  && workloadError(p.workloads) === null;


/** Columns for the profile CSV. Named to match `BuildingProfile` so a later
 *  import maps straight across without a translation table. */
export const PROFILE_COLUMNS = [
  'normalised_address', 'building_category', 'building_type',
  'has_security_desk', 'workloads', 'workload_other',
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
      // Derived here the same way the server derives it, so the CSV is
      // self-contained: a file that names only the leaf makes the reader look
      // the category up.
      BUILDING_TYPES.find((b) => b.value === p.building_type)?.category ?? '',
      p.building_type,
      p.has_security_desk ? 'true' : 'false',
      // Pipe-separated, not comma: the field is already inside a quoted CSV
      // cell, and a comma there survives the file but trips every naive
      // splitter downstream.
      p.workloads.join('|'),
      p.workload_other,
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
