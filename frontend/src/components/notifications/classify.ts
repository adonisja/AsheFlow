/**
 * Which notifications are waiting on THIS person (ADR-275 D1).
 *
 * The banner used to render one card per unread row, so its height was a
 * function of the data. Measured on staging: one account sits at 14 unread,
 * which is ~1,200px of banner on a ~900px viewport — the page content is
 * entirely below the fold.
 *
 * The fix is not a smaller card or a scrollbar. It is a rule about what earns
 * the space: a notification that needs an ANSWER stays expanded, and everything
 * else collapses into one row.
 *
 * Split by ACTIONABILITY, not recency or count. `dispatch_assignment` is 79% of
 * all notifications and the only type that requires a response; an unanswered
 * one can strand a truck. Newest-N-expanded (Ant Design's default) would let an
 * older unanswered assignment fall inside the collapsed group, which is the one
 * outcome that costs something operationally.
 *
 * MIRRORED ON MOBILE. This rule decides what a walker sees on a phone in a van,
 * so the two copies must agree; a change here lands on both surfaces in the
 * same commit (the rule ADR-269 set, and ADR-271 §T re-learned).
 */

/** The shape both surfaces share. Deliberately structural rather than importing
 *  a web-only type — mobile declares its own Notification. */
export interface ClassifiableNotification {
  id: string;
  type: string;
  dispatch_date?: string | null;
}

/** Confirmation state per dispatch date, as the banner already fetches it. */
export type ConfirmationStatus = 'pending' | 'confirmed' | 'declined' | null;

/**
 * True when this notification is waiting on the caller's response.
 *
 * Three conditions, all required:
 *   1. it is a type that CAN be answered
 *   2. the caller has not already answered it in this session
 *   3. the backend still says the window is open
 *
 * (3) is deliberately permissive when the status is UNKNOWN (`undefined`): the
 * status fetch is async, and treating "not loaded yet" as "closed" would
 * collapse a live assignment for the first second after mount — exactly when a
 * walker is looking at it. An unknown window shows the card; a known-closed one
 * does not.
 */
export function isActionRequired(
  n: ClassifiableNotification,
  opts: {
    answeredInSession?: Record<string, unknown>;
    confirmationStatus?: Record<string, ConfirmationStatus>;
  } = {},
): boolean {
  if (n.type !== 'dispatch_assignment') return false;
  if (opts.answeredInSession?.[n.id]) return false;
  if (!n.dispatch_date) return false;

  const status = opts.confirmationStatus?.[n.dispatch_date];
  // undefined = not fetched yet -> assume open (see above). null = no
  // confirmation row -> nothing to answer.
  if (status === undefined) return true;
  return status === 'pending';
}

/** Partition into what needs an answer and what is only news. Order within each
 *  group is preserved, so the caller's sort still governs. */
export function partitionNotifications<T extends ClassifiableNotification>(
  notifications: T[],
  opts: Parameters<typeof isActionRequired>[1] = {},
): { action: T[]; info: T[] } {
  const action: T[] = [];
  const info: T[] = [];
  for (const n of notifications) {
    (isActionRequired(n, opts) ? action : info).push(n);
  }
  return { action, info };
}
