import axiosClient from '../api/axiosClient';

/** Discovering the campaigns your own company may submit to (ADR-485 D9).
 *
 *  Deliberately a SEPARATE module from `collectionSubmit.ts`, which documents at
 *  length why it avoids `axiosClient`: that file serves the PUBLIC collection
 *  page, where there is no session to attach and the API may be unconfigured.
 *
 *  This call is the exact opposite — it only means anything for a signed-in
 *  tenant user, because the answer is derived from `caller.company_id`. Putting
 *  it in the public module would have forced a session-aware client into a file
 *  whose contract is that it has none.
 *
 *  WHY THIS EXISTS AT ALL
 *  ----------------------
 *  Before D9, a collector had to be handed a link out of band and paste it
 *  (`walkerlog.collectToken.<dataset>` in localStorage). That still works and is
 *  still the only path for someone outside the tenant. But a signed-in employee
 *  of a commissioned company should not have to chase a link for a campaign
 *  their own company was issued — the server already knows which ones those are.
 */
export interface MyCampaign {
  token: string;
  label: string;
  dataset: string;
  expires_at: string | null;
}

/** Campaigns this caller's company may submit to, or [] when there are none.
 *
 *  Resolves to [] rather than throwing on ANY failure. The paste field is still
 *  on screen and still works, so a failed discovery call must degrade to "no
 *  shortcuts offered" and never to a broken page — the same local-first posture
 *  the rest of this page takes (ADR-415 D5).
 */
export async function fetchMyCampaigns(): Promise<MyCampaign[]> {
  try {
    const res = await axiosClient.get<MyCampaign[]>('/collection/my-campaigns');
    return Array.isArray(res.data) ? res.data : [];
  } catch {
    // Includes the 401 a signed-out visitor gets on the public collection page,
    // which is an expected state here, not an error worth surfacing.
    return [];
  }
}
