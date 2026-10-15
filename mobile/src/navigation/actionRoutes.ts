/**
 * Web paths -> mobile tab keys (ADR-494).
 *
 * `SPEC.actions[].route` is a WEB PATH, and that is deliberate: a gate's only
 * exit is its action link, so if the two surfaces disagreed about where it goes
 * one of them would lock the user against a dead end. One string, one contract.
 *
 * Mobile does not navigate by path. It has no linking config and no deep-link
 * prefixes; `MainShell` holds a tab key in state and `useTabSwitch` sets it. So
 * the contract needs a translation layer, and this is it — the reason
 * `SPEC.actions` was inert on mobile until now.
 *
 * ## Why a FUNCTION and not a dict
 *
 * `/my-route` resolves to two different tabs depending on operating mode:
 *
 *     MyRoute         feature: 'route_sort'       (full mode)
 *     WorkforceRoute  feature: 'workforce_sort'   (workforce mode)
 *
 * A static map would have to pick one, and would send half the tenants to a tab
 * that is not rendered for them — ADR-305's divergence showing up as a dead
 * link. So resolution takes the caller's capability list.
 *
 * ## Unmapped is a real answer
 *
 * `/dispatch` has no mobile tab at all: dispatch oversight is a web surface
 * (project memory records the intended mobile=do / web=see split). Returning
 * `null` is correct and the caller must handle it — see `resolveActionRoute`'s
 * contract. Inventing a nearest-match tab would send a walker somewhere they
 * did not ask to go, which is worse than offering no button.
 */

/** A tab key in `ALL_TABS`, or null when this surface has no equivalent. */
export type MobileTarget = string | null;

/**
 * Paths that resolve to exactly one tab regardless of mode.
 *
 * Keys are the web paths as they appear in `notification_spec.SPEC`. A path
 * absent from here and from the mode-dependent cases below is unmapped, which
 * `resolveActionRoute` reports as null rather than guessing.
 */
const STATIC: Record<string, string> = {
  '/account': 'Account',
  '/field-ops': 'FieldOps',
  '/schedule': 'Schedule',
  '/schedule-changes': 'SchChanges',
  '/trainer-dashboard': 'Training',
  // ADR-494 D4's destination. The mobile screen is a tab of its own rather
  // than a push inside Home: it is linked from a notification, so it must be
  // reachable without first knowing which tab it hides under.
  '/my-role': 'MyRole',
  '/incidents': 'Incidents',     // ADR-512: stolen-package report to review
};

/**
 * Paths with no mobile equivalent, listed EXPLICITLY.
 *
 * The distinction from "absent" matters: a path here is a decision, and a path
 * that is merely missing is an oversight. `test_adr494_mobile_route_map` walks
 * SPEC and requires every action route to be in STATIC, in the mode-dependent
 * branch, or in this set — so a new action route cannot be silently inert.
 */
export const DELIBERATELY_UNMAPPED: ReadonlySet<string> = new Set([
  // Dispatch oversight is a web surface. A walker's phone has no fleet view and
  // should not: the intended split is mobile=do, web=see.
  '/dispatch',
]);

/**
 * The tab key for a web path, given what this company can do.
 *
 * `features` is the capability list from `GET /companies/my-capabilities`
 * (ADR-289), the same list the tab gates use. Passing it rather than reading a
 * context keeps this a pure function, so the completeness test can call it
 * without mounting a provider.
 *
 * Returns null when no mobile surface exists. **Callers must render no button
 * in that case** — a button that navigates nowhere is the dismiss-only control
 * ADR-494 D1 set out to remove, and for a GATE it would be a wall with no exit.
 */
export function resolveActionRoute(path: string, features: string[]): MobileTarget {
  // `/my-route` is the one mode-dependent case. Checked before STATIC so the
  // branch is visible at the top rather than hidden behind a lookup miss.
  if (path === '/my-route') {
    if (features.includes('workforce_sort')) return 'WorkforceRoute';
    if (features.includes('route_sort')) return 'MyRoute';
    // Neither capability: the company has no routing surface at all, so there
    // is nothing to link to. Null, not a guess.
    return null;
  }

  if (DELIBERATELY_UNMAPPED.has(path)) return null;

  return STATIC[path] ?? null;
}
