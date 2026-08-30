/**
 * "Which truck am I on?" — one implementation (ADR-331).
 *
 * Four screens hand-rolled this against the `/dispatch/{date}` payload, and the
 * ADR-330 sweep is the proof that duplication eventually diverges: one of them
 * read the DAY's `workflow_status` instead of its own truck's status, which
 * closed the confirm window on 19 crew members' phones because a DIFFERENT
 * truck had finalized.
 *
 * Deliberately NOT a React hook despite the name. It holds no state and runs no
 * effect — every caller already has the payload from a fetch it controls. A
 * `useX` that is really a pure function invites a `useEffect` later and turns
 * four synchronous derivations into four re-render sources. The name follows
 * the codebase's reading habit; the implementation is a function, on purpose.
 */

export type TruckStatus = 'planned' | 'active' | 'completed';

/** The `truck_assignments` entry as `/dispatch/{date}` actually returns it.
 *
 * Verified against the router rather than assumed — DriverSurveyScreen reads
 * `ta.members`, `ta.truck_name` and `ta.driver_name`, none of which have ever
 * been in this payload, so its assignment header has never rendered (ADR-331
 * D3, recorded as Open).
 */
export interface TruckAssignmentEntry {
  truck_id: string;
  status?: TruckStatus | string;
  /** Some payloads carry `id`, others `assignment_id`. ReattemptScreen read
   *  both because it hit one of each; absorbing that here is the point. */
  assignment_id?: string;
  id?: string;
  is_hub?: boolean;
  dock_zone?: string | null;
}

/** The shape this needs from a crew member. Screens declare their own
 *  `CrewMember` types with different fields — and one keys on `id` rather than
 *  `employee_id` — so this stays structural, and generic, to avoid forcing a
 *  type change on every caller. */
export interface CrewMemberLike {
  employee_id?: string;
  id?: string;
}

export interface DispatchPayloadLike<M> {
  assigned_crews?: Record<string, M[]> | null;
  truck_assignments?: TruckAssignmentEntry[] | null;
}

export interface MyTruck<M> {
  /** null when the employee is on no truck for this date. */
  truckId: string | null;
  /** The caller's own crew, exactly as the payload gave it. Empty when unresolved. */
  crew: M[];
  assignmentId: string | null;
  /** THIS truck's status — never the day's `workflow_status`.
   *
   *  Returning the per-truck value by construction is what makes the ADR-329 /
   *  ADR-330 class of bug unexpressible through this path. `workflow_status` is
   *  still on the response for genuinely day-level questions (ADR-329 D3), and
   *  is deliberately NOT surfaced here so reaching for it stays a visible choice.
   */
  status: TruckStatus | null;
  isHub: boolean;
  dockZone: string | null;
}

const EMPTY = Object.freeze([]) as never[];

export function useMyTruck<M extends CrewMemberLike>(
  dispatch: DispatchPayloadLike<M> | null | undefined,
  employeeId: string | null | undefined,
): MyTruck<M> {
  const none: MyTruck<M> = {
    truckId: null, crew: EMPTY as M[], assignmentId: null,
    status: null, isHub: false, dockZone: null,
  };
  if (!dispatch || !employeeId) return none;

  const crews = dispatch.assigned_crews ?? {};
  const entry = Object.entries(crews).find(([, crew]) =>
    (crew ?? []).some(m => (m.employee_id ?? m.id) === employeeId),
  );
  if (!entry) return none;

  const [truckId, crew] = entry;
  const ta = (dispatch.truck_assignments ?? []).find(t => t.truck_id === truckId);

  const status = ta?.status;
  return {
    truckId,
    crew: crew ?? (EMPTY as M[]),
    // Both spellings, for the reason above.
    assignmentId: ta?.id ?? ta?.assignment_id ?? null,
    status:
      status === 'planned' || status === 'active' || status === 'completed'
        ? status
        : null,
    isHub: ta?.is_hub === true,
    dockZone: ta?.dock_zone ?? null,
  };
}
