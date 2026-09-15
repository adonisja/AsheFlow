import { isUsable, type AddressProfile } from './addressProfile';
import type { WalkerDay } from './walkerLogDb';

/** Submitting collected profiles to the shared endpoint (ADR-415).

 *  Deliberately NOT using `axiosClient`. That client attaches a Cognito token
 *  and throws at import time when VITE_API_URL is unset — both wrong here. This
 *  page is public: there is no session to attach, and it has to keep working
 *  with no backend configured at all, because local-first is the default and
 *  submission is additive (ADR-415 D5).
 *
 *  Nothing here is required for the page to function. A collector with no
 *  signal fills in buildings, exports, and is done; submission is the
 *  convenience that saves you collecting files by hand.
 */

/** Where to submit. Falls back to the configured API, and is overridable so the
 *  collection subdomain can point somewhere else without a rebuild. */
const API = (import.meta.env.VITE_COLLECTION_API as string | undefined)
  ?? (import.meta.env.VITE_API_URL as string | undefined)
  ?? '';

export const submitConfigured = (): boolean => API.length > 0;

export interface SubmitResult {
  accepted: number;
  duplicate: number;
  /** Addresses in THIS batch the campaign had already received — typically
   *  from another collector, since your own are blocked before they are sent.
   *  Echoed back so the page can warn about them next time rather than letting
   *  someone walk to the same door twice. */
  duplicate_addresses: string[];
}

/** POSTs a batch of profiles.
 *
 *  Sends ONLY complete profiles: the server rejects a missing building_type
 *  with a 422, and a half-filled row is a draft the collector has not finished,
 *  not something to push at a database.
 *
 *  Errors are thrown with a message the collector can act on. There is no retry
 *  loop — the data is already safe locally, so a failed submit costs nothing but
 *  a second tap.
 */
export async function submitProfiles(
  token: string,
  profiles: AddressProfile[],
): Promise<SubmitResult> {
  if (!submitConfigured()) {
    throw new Error('No collection server is configured for this page.');
  }
  const usable = profiles.filter(isUsable);
  if (usable.length === 0) {
    throw new Error('Nothing complete to send. A profile needs an address and a building type.');
  }

  const res = await fetch(`${API.replace(/\/$/, '')}/collection/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      token,
      // Mapped explicitly rather than spread: the stored shape carries `id`,
      // `date` and `updated_at`, and the server forbids unrecognised keys, so a
      // spread would 422 the whole batch.
      profiles: usable.map((p) => ({
        address: p.address.trim(),
        building_type: p.building_type,
        // `building_category` is NOT sent: the server derives it from the type
        // (ADR-418), and the request schema forbids unrecognised keys, so
        // sending it would 422 the whole batch.
        has_security_desk: p.has_security_desk,
        workloads: p.workloads,
        // null, not '' — the server forbids text without the `other` tag, and
        // an empty string is text.
        workload_other: p.workload_other?.trim() || null,
        note: p.note || null,
        opens_at: p.opens_at || null,
        closes_at: p.closes_at || null,
        break_start: p.break_start || null,
        break_end: p.break_end || null,
        troublesome: p.troublesome,
        collected_by: p.collected_by || null,
        collected_on: p.date,
      })),
    }),
  });

  if (res.status === 404) {
    throw new Error('That collection link is not active. Ask for a current one.');
  }
  if (res.status === 429) {
    throw new Error('Too many submissions right now. Try again in a minute.');
  }
  if (!res.ok) {
    // No server text echoed back: a public endpoint's error body is an
    // information-disclosure surface, and the collector cannot act on it anyway.
    throw new Error('Could not send. Your entries are still saved on this device.');
  }
  const out = (await res.json()) as SubmitResult;
  // Tolerate a server that predates the echo rather than crashing the page.
  return { ...out, duplicate_addresses: out.duplicate_addresses ?? [] };
}


/** Is this door already collected under this campaign? (ADR-417 D7)
 *
 *  FAILS OPEN. A dropped hotspot must not stop data entry — the page's whole
 *  premise is that it works offline — so an unreachable server returns
 *  `unknown` and the collector carries on. Nothing bad reaches the database:
 *  the unique constraint still rejects a true same-day duplicate on submit,
 *  and the campaign-wide case is a wasted walk, not corrupt data.
 *
 *  Returns `unknown` rather than throwing, so the caller cannot accidentally
 *  treat a network failure as "not collected".
 */
export type CheckResult =
  | { state: 'known'; collected_on: string | null }
  | { state: 'new' }
  | { state: 'unknown' };

export async function checkAddress(
  token: string,
  address: string,
): Promise<CheckResult> {
  if (!submitConfigured() || !token.trim() || address.trim().length < 3) {
    return { state: 'unknown' };
  }
  try {
    const res = await fetch(`${API.replace(/\/$/, '')}/collection/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token.trim(), address: address.trim() }),
    });
    if (!res.ok) return { state: 'unknown' };   // 404 token, 429, 5xx: all "cannot say"
    const j = (await res.json()) as { known: boolean; collected_on: string | null };
    return j.known
      ? { state: 'known', collected_on: j.collected_on }
      : { state: 'new' };
  } catch {
    return { state: 'unknown' };                // offline
  }
}

// ── Route log (ADR-417 D3) ───────────────────────────────────────────────────

export interface DaySubmitResult {
  accepted: number;
  /** Days that already existed and were overwritten. The server upserts on
   *  (token, date, walker), so a retry after a dropped connection lands here
   *  rather than creating a duplicate. */
  replaced: number;
}

/** Is a day worth sending?
 *
 *  A walker with no routes is a name someone typed and moved on from — the
 *  row exists locally so the crew list can show them, but it carries no
 *  observation. Sending it would put a name in the database with nothing
 *  attached to it, which is the one thing the PII position does not justify.
 */
export const dayWorthSending = (d: WalkerDay): boolean =>
  d.name.trim().length > 0 && d.routes.length > 0;

/** POSTs logged walker days.
 *
 *  Maps explicitly rather than spreading. The stored shape carries `id` and
 *  `updated_at`, the server forbids unrecognised keys, and a spread would 422
 *  the whole batch on a field the collector cannot see or fix.
 */
export async function submitDays(
  token: string,
  days: WalkerDay[],
): Promise<DaySubmitResult> {
  if (!submitConfigured()) {
    throw new Error('No collection server is configured for this page.');
  }
  const worth = days.filter(dayWorthSending);
  if (worth.length === 0) {
    throw new Error('Nothing to send. A day needs a walker and at least one route.');
  }

  const res = await fetch(`${API.replace(/\/$/, '')}/collection/submit-day`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      token,
      days: worth.map((d) => ({
        walker_name: d.name.trim(),
        collected_on: d.date,
        arrival_time: d.arrival_time,
        departure_time: d.departure_time,
        routes: d.routes.map((r) => ({
          route_id: r.route_id,
          route_start: r.route_start,
          route_end: r.route_end,
          difficulty: r.difficulty,
          notes: r.notes,
          totes: r.totes.map((t) => ({
            bag_id: t.bag_id,
            addresses: t.addresses,
            sort_zone: t.sort_zone ?? null,
            stop: t.stop ?? null,
            stop_package_count: t.stop_package_count ?? null,
            stop_ov_count: t.stop_ov_count ?? null,
            stop_bag_count: t.stop_bag_count ?? null,
          })),
          // `ovs` is optional on days logged before OVs existed; absent means
          // "not recorded", and an empty list is the honest wire value.
          ovs: (r.ovs ?? []).map((o) => ({
            ov_id: o.ov_id, size: o.size, address: o.address, sort_zone: o.sort_zone,
          })),
          rts: r.rts.map((x) => ({ tba: x.tba, code: x.code, reason: x.reason })),
        })),
      })),
    }),
  });

  if (res.status === 404) {
    throw new Error('That collection link is not active. Ask for a current one.');
  }
  if (res.status === 429) {
    throw new Error('Too many submissions right now. Try again in a minute.');
  }
  if (res.status === 409) {
    throw new Error('Someone submitted that day at the same moment. Send it again.');
  }
  if (!res.ok) {
    // No server text echoed back: a public endpoint's error body is an
    // information-disclosure surface, and the collector cannot act on it.
    throw new Error('Could not send. Your entries are still saved on this device.');
  }
  return (await res.json()) as DaySubmitResult;
}
