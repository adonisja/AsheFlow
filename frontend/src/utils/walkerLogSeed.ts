/** Today's roster and bag manifest, pre-loaded so a day can be logged without
 *  typing 11 names and 59 bag labels by hand.
 *
 *  The bag list is imported from the BTR workbook at build time (a plain JSON
 *  import, no parsing in the browser). The roster is the walker list off the
 *  DispatchOS assignment card — walkers only; the driver is excluded because
 *  this log tracks walker routes and a driver takes none.
 *
 *  WHY A DERIVED POOL RATHER THAN A STORED ONE. "Which bags are still
 *  unassigned" is not saved anywhere: it is computed as (manifest − everything
 *  currently on a route). Storing it as its own record would create a second
 *  copy of the truth that drifts the moment a bag is moved between routes or a
 *  route is deleted — the same two-places-to-update failure the codebase has
 *  paid for before. Derived, a deleted route's bags return to the pool for free.
 */
import type { LogTote, WalkerDay } from './walkerLogDb';

export interface SeedStop {
  stop: string;
  dispatch_time: string | null;
  duration: string | null;
  package_count: number | null;
  ov_count: number | null;
  ov_zones: string;
  bag_ids: string[];
}

export interface SeedBag {
  bag_id: string;
  sort_zone: string;
  stop: string;
  stop_package_count: number;
  stop_ov_count: number;
  stop_bag_count: number;
}

export interface Seed {
  btr: string;
  date: string;
  anchor: string;
  stops: SeedStop[];
  bags: SeedBag[];
}

/** Bundled manifests. DELIBERATELY EMPTY.
 *
 *  This used to hold two real workbooks (BTR45 2026-09-10, BTR31 2026-09-12) as
 *  compile-time fixtures. They were removed before the page shipped publicly:
 *  a bundled manifest is baked into the JavaScript every visitor downloads, so
 *  a real truck's bag list would be served to anyone who opened the page.
 *
 *  Nothing is lost operationally. The Load Sheet import reads the same .xlsx in
 *  the browser and stores it in IndexedDB, which is where a day's manifest
 *  belongs — local to the person logging it, never in the bundle. The import
 *  path already took priority over these fixtures, so removing them only makes
 *  the fallback that was already preferred the sole path.
 *
 *  Do not re-add real workbooks here. Import them at runtime instead. */
const SEEDS: Seed[] = [];

/** The manifest for a date, or null when that date has no workbook. Null is the
 *  normal case — most dates are logged by hand with no seed at all. */
export const seedFor = (date: string): Seed | null =>
  SEEDS.find((s) => s.date === date) ?? null;

/** Bundled crews. DELIBERATELY EMPTY, for a stronger reason than the manifests.
 *
 *  This held 18 real coworkers' full names. Names are PII: they identify actual
 *  people, they are not the logger's to publish, and unlike a bag label they
 *  cannot be made non-identifying. Committing them would have shipped a real
 *  crew roster to every visitor.
 *
 *  The Crew Import screenshot flow replaces it. OCR reads the assignment card
 *  on the phone and the names land in IndexedDB — on the device of the person
 *  who already works with those people, and nowhere else.
 *
 *  Do not re-add names here. */
const CREWS: Record<string, string[]> = {};

/** The crew seeded for a date, or [] when that date has none. */
export const crewFor = (date: string): string[] => CREWS[date] ?? [];

/** A manifest bag as a tote ready to drop onto a route. */
export const bagToTote = (b: SeedBag): LogTote => ({
  bag_id: b.bag_id,
  addresses: [],
  sort_zone: b.sort_zone,
  stop: b.stop,
  stop_package_count: b.stop_package_count,
  stop_ov_count: b.stop_ov_count,
  stop_bag_count: b.stop_bag_count,
});

/** Every bag_id currently sitting on some route across the given days. */
export function assignedBagIds(days: WalkerDay[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const d of days) {
    for (const r of d.routes) {
      for (const t of r.totes) {
        if (t.bag_id.trim()) out.set(t.bag_id.trim(), `${d.name} · route ${r.route_id}`);
      }
    }
  }
  return out;
}

/** The active manifest minus what is already assigned. Derived, never stored. */
export function unassignedBags(seed: Seed | null, days: WalkerDay[]): SeedBag[] {
  // Takes the RESOLVED seed, not a date.
  //
  // It used to call seedFor(date) itself, which silently ignored a manifest
  // imported from a workbook: the page resolved the right seed, passed the
  // date, and this looked up the compile-time fixture instead — so an imported
  // truck showed "No totes left" with 39 bags sitting in IndexedDB. Whoever
  // resolves the seed must be the one that owns which seed it is.
  if (!seed) return [];
  const taken = assignedBagIds(days);
  return seed.bags.filter((b) => !taken.has(b.bag_id));
}
