/** How long a session may last, by role (ADR-463).
 *
 *  Pure: no React, no Amplify, no timers. The hook that enforces this is
 *  untestable without a DOM; these rules are the part worth asserting, so they
 *  live where a test can reach them.
 */

/** Roles that can read across a tenant, run dispatch, or export PII.
 *
 *  Mirrors the PreAuthentication trigger's PRIVILEGED_GROUPS (ADR-362) rather
 *  than employees.py's PRIVILEGED_ROLES, which omits super_admin and
 *  platform_support -- borrowing the shorter set would put a super admin on the
 *  field tier's looser clock, the opposite of intended.
 */
export const PRIVILEGED_GROUPS = [
  'super_admin', 'admin', 'management', 'dispatch', 'platform_support',
] as const;

export interface SessionLimits {
  /** Hard cap from the moment of authentication. */
  absoluteMs: number;
  /** Idle cap, or null when the tier has none. */
  idleMs: number | null;
  tier: 'privileged' | 'field';
}

const HOUR = 60 * 60 * 1000;
const MINUTE = 60 * 1000;

/* SP 800-63-4 puts the AAL2 ceiling at 24h absolute / 1h idle, and makes
   establishing an overall timeout a SHALL. These are deliberately stricter for
   the privileged tier: 12h is one shift, so a session opened at the morning
   sort cannot survive into the next day. */
const PRIVILEGED: SessionLimits = { absoluteMs: 12 * HOUR, idleMs: 30 * MINUTE, tier: 'privileged' };

/* No idle clock for field roles: their app backgrounds constantly on
   unreliable mobile networks, and a 30-minute idle timer would sign a walker
   out between two buildings (ADR-385, ADR-463 D3; reaffirmed by the owner,
   ADR-542). The absolute cap bounds them instead: 12h from sign-in since
   ADR-542 (was 24h) -- an 8-hour shift plus a buffer, matching mobile. */
const FIELD: SessionLimits = { absoluteMs: 12 * HOUR, idleMs: null, tier: 'field' };

export function limitsForGroups(groups: readonly string[]): SessionLimits {
  const privileged = groups.some(g => (PRIVILEGED_GROUPS as readonly string[]).includes(g));
  return privileged ? PRIVILEGED : FIELD;
}

/** Why a session should end, or null while it may continue.
 *
 *  `authTimeMs` is the ID token's `auth_time` claim -- when the user actually
 *  authenticated. NOT page load: anchoring to mount restarts the clock on every
 *  refresh, which is what makes an absolute timeout decorative.
 */
export function expiryReason(
  limits: SessionLimits,
  authTimeMs: number | null,
  lastActivityMs: number,
  nowMs: number,
): 'absolute' | 'idle' | null {
  // A missing auth_time must not END a session -- a token shape we did not
  // expect would sign everyone out. The idle clock still applies.
  if (authTimeMs !== null && nowMs - authTimeMs >= limits.absoluteMs) return 'absolute';
  if (limits.idleMs !== null && nowMs - lastActivityMs >= limits.idleMs) return 'idle';
  return null;
}

/** Milliseconds until the idle sign-out, or null when the tier has no idle clock. */
export function msUntilIdleSignOut(
  limits: SessionLimits,
  lastActivityMs: number,
  nowMs: number,
): number | null {
  if (limits.idleMs === null) return null;
  return Math.max(0, limits.idleMs - (nowMs - lastActivityMs));
}

/** ADR-576: where every tab records its latest activity.
 *
 *  The session is ONE Amplify session shared by every tab (localStorage), but
 *  each tab used to keep its own idle clock. A tab left open in the background
 *  reached 30 minutes and called signOut(), which revokes the shared refresh
 *  token, so the tab the person was actually working in landed on /login with
 *  no reason given. Idleness is a property of the person, not of one tab. */
export const LAST_ACTIVITY_KEY = 'asheflow_last_activity';

/** The latest activity across this tab and every other one. A missing or
 *  unreadable shared value never makes the session look MORE idle: this tab's
 *  own clock is the floor. */
export function latestActivity(ownMs: number, sharedRaw: string | null): number {
  const shared = sharedRaw === null ? NaN : Number(sharedRaw);
  return Number.isFinite(shared) && shared > ownMs ? shared : ownMs;
}
