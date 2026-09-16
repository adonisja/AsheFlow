/** Sorting, filtering and door-grouping for the collected-addresses table.
 *
 *  ADR-432. Kept out of the page component because these are the parts with
 *  actual logic in them — a door's agreement state and a sort comparator are
 *  testable in isolation, and were the two things most likely to be quietly
 *  wrong inside JSX.
 *
 *  ALL CLIENT-SIDE, and that is a bounded decision (ADR-432 D4): the listing
 *  fetches up to 1000 rows at once and a campaign at its cap fits. Past that
 *  these aggregates are computed over a SUBSET and would be silently wrong —
 *  the same failure ADR-430 hit with a client-side observation count. The page
 *  says so rather than hiding it; see `atFetchLimit`.
 */
import type { CollectedProfile } from '../api/types';

export type SortKey = 'address' | 'building_type' | 'collected_on' | 'collected_by';
export type SortDir = 'asc' | 'desc';

/** Whether a door's observations tell the same story.
 *
 *  - `single`  — one observation; nothing to compare yet
 *  - `agreed`  — every observation reports the same building type
 *  - `differs` — they do not, and a human should look
 */
export type DoorState = 'single' | 'agreed' | 'differs';

export interface DoorGroup {
  key: string;
  address: string;
  state: DoorState;
  /** Newest first, matching the flat table's order. */
  observations: CollectedProfile[];
}

/** The identity of a door for grouping.
 *
 *  Prefers the server's door_key — the same lossy fold the duplicate check and
 *  ADR-430's observation count use, so grouping agrees with the "closed"
 *  marking rather than inventing a second notion of sameness. Falls back to a
 *  normalised address only for rows written before the column existed.
 */
export function groupKey(p: CollectedProfile): string {
  return p.door_key || p.address.trim().toLowerCase().replace(/\s+/g, ' ');
}

/** Groups observations by door, newest door first.
 *
 *  `differs` compares building_type ALONE (ADR-432 D1). Hours and notes vary
 *  legitimately between visits — a shop shuts early, one collector writes a
 *  fuller note — so comparing the whole record would flag nearly every pair and
 *  the signal would mean nothing. Building type is the door's fixed identity.
 */
export function groupByDoor(rows: CollectedProfile[]): DoorGroup[] {
  const byKey = new Map<string, CollectedProfile[]>();
  for (const p of rows) {
    const k = groupKey(p);
    const list = byKey.get(k);
    if (list) list.push(p);
    else byKey.set(k, [p]);
  }
  return [...byKey.entries()].map(([key, observations]) => {
    const types = new Set(observations.map((o) => o.building_type));
    return {
      key,
      address: observations[0].address,
      state: observations.length < 2 ? 'single' : types.size === 1 ? 'agreed' : 'differs',
      observations,
    } as DoorGroup;
  });
}

/** Compare for the sortable columns.
 *
 *  Address sorts NUMERICALLY ("380 W 33" before "1200 BROADWAY" the way a
 *  person expects, not the way a plain string compare puts them), which is
 *  what `numeric: true` buys. Nulls sort last in both directions: a missing
 *  collector name is absent information, and floating it to the top of a
 *  descending sort would make the first screen the least informative one.
 */
export function compareProfiles(a: CollectedProfile, b: CollectedProfile,
                                key: SortKey, dir: SortDir): number {
  const mul = dir === 'asc' ? 1 : -1;
  const av = a[key] ?? '';
  const bv = b[key] ?? '';
  if (!av && !bv) return 0;
  if (!av) return 1;      // nulls last, regardless of direction
  if (!bv) return -1;
  return mul * String(av).localeCompare(String(bv), undefined, { numeric: true });
}

export interface Filters {
  buildingType: string;
  workload: string;
  /** '' | 'open' | 'closed' | 'differs' */
  state: string;
}

export const NO_FILTERS: Filters = { buildingType: '', workload: '', state: '' };

export function hasActiveFilters(f: Filters): boolean {
  return Boolean(f.buildingType || f.workload || f.state);
}

/** Applies the filter chips to the flat rows.
 *
 *  `differs` is a property of a DOOR, not of a row, so it is resolved against
 *  the grouping rather than the row: selecting it keeps every observation whose
 *  door disagrees. Filtering row-by-row could not express it at all.
 */
export function filterProfiles(rows: CollectedProfile[], f: Filters): CollectedProfile[] {
  let out = rows;
  if (f.buildingType) out = out.filter((p) => p.building_type === f.buildingType);
  if (f.workload) out = out.filter((p) => (p.workloads ?? []).includes(f.workload));
  if (f.state === 'open') out = out.filter((p) => !p.closed);
  else if (f.state === 'closed') out = out.filter((p) => p.closed);
  else if (f.state === 'differs') {
    const differing = new Set(
      groupByDoor(rows).filter((g) => g.state === 'differs').map((g) => g.key),
    );
    out = out.filter((p) => differing.has(groupKey(p)));
  }
  return out;
}
