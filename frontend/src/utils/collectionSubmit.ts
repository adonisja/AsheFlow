import { isUsable, type AddressProfile } from './addressProfile';

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
        workload_class: p.workload_class,
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
  return (await res.json()) as SubmitResult;
}
