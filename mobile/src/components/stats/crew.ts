/**
 * Crew slot ordering (ADR-271 §P, ADR-256).
 *
 * Its OWN module, not a helper inside StatsDrill.tsx: importing the screen
 * pulls in the API client and, through it, AsyncStorage — a native module that
 * needs a mock before a test can even load the file. A pure rule about who
 * outranks whom should not be reachable only through a React tree.
 */

/** Slot order for the crew list. CAPTAIN SITS DIRECTLY UNDER DRIVER: the two
 *  run the truck (TRUCK_SCOPED_ROLES, ADR-256) and belong together above the
 *  people who carry. A role with nobody in it never creates a group, so this
 *  needs no special case for "no captains today". */
export const CREW_ORDER = ['driver', 'captain', 'trainer', 'walker', 'trainee'];

/** One hue per role, so the eye can group the crew without reading the labels.
 *  Takes the tone values rather than the theme object so this module stays free
 *  of UI imports; the caller passes them from `useColors()`. */
export function roleTone(
  role: string,
  t: { warning: string; gold: string; info: string; success: string; primary: string },
): string {
  switch (role) {
    case 'driver':  return t.warning;
    case 'captain': return t.gold;
    case 'trainer': return t.info;
    case 'trainee': return t.success;
    default:        return t.primary;   // walker — the bulk of any crew
  }
}

/** Group a crew by slot role, ordered by CREW_ORDER.
 *
 *  An unrecognised role sorts to the FRONT, because `indexOf` returns -1. That
 *  is deliberate and pinned by test: a role this build has never heard of is
 *  more likely to be a new senior slot than a new carrier, and burying it at
 *  the bottom would hide it. Revisit if that assumption stops holding.
 */
export function groupCrew(
  crew: { name: string; role: string }[],
): [string, string[]][] {
  const groups = new Map<string, string[]>();
  for (const m of crew) {
    if (!groups.has(m.role)) groups.set(m.role, []);
    groups.get(m.role)!.push(m.name);
  }
  return [...groups.entries()].sort(
    (a, b) => CREW_ORDER.indexOf(a[0]) - CREW_ORDER.indexOf(b[0]));
}
