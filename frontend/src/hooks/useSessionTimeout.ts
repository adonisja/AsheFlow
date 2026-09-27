/** Ends a session that has run too long or sat idle (ADR-463).
 *
 *  Two clocks, because they catch different failures. The absolute cap bounds
 *  one sign-in; the idle cap bounds an unattended terminal. Neither subsumes
 *  the other.
 *
 *  SCOPE, stated plainly: this is a CLIENT control. It protects against the
 *  station terminal left signed in as dispatch, which is the threat this
 *  product actually has. It does not stop someone holding a stolen refresh
 *  token from calling the API directly -- that is bounded by the token's own
 *  lifetime, which ADR-463 D5 records as owed work.
 */
import { useEffect, useRef, useState } from 'react';
import { fetchAuthSession, signOut } from 'aws-amplify/auth';

import {
  expiryReason,
  limitsForGroups,
  msUntilIdleSignOut,
  type SessionLimits,
} from '../utils/sessionPolicy';

/** How long before an idle sign-out the warning appears. */
const WARN_BEFORE_MS = 60 * 1000;

/** Ref writes are cheap, but the handler still runs per event. This bounds how
 *  often the *timestamp* is refreshed -- never how often activity COUNTS.
 *
 *  An earlier version discarded events inside this window instead of coalescing
 *  them, which left `lastActivity` stale: someone active every 20 seconds could
 *  still be signed out for inactivity. The window is well under the 30-minute
 *  idle cap, so coalescing costs at most a few seconds of precision. */
const ACTIVITY_THROTTLE_MS = 1000;

/** How often the clocks are checked. Well under the 60s warning window, so the
 *  warning cannot be skipped by a coarse tick. */
const TICK_MS = 15 * 1000;

/* Scrolling and mouse movement are activity too. Reading a long dispatch table
   without clicking is not idleness, and the earlier pointerdown/keydown-only
   list would have signed that reader out mid-page. */
const ACTIVITY_EVENTS = [
  'pointerdown', 'pointermove', 'keydown', 'scroll', 'wheel', 'touchstart',
] as const;

export interface SessionTimeoutState {
  /** Seconds until an idle sign-out, while inside the warning window. */
  idleWarningSeconds: number | null;
  /** Dismiss the warning by declaring activity. */
  staySignedIn: () => void;
}

export function useSessionTimeout(
  groups: readonly string[],
  enabled: boolean,
): SessionTimeoutState {
  const [idleWarningSeconds, setIdleWarningSeconds] = useState<number | null>(null);
  const lastActivity = useRef<number>(Date.now());
  const authTime = useRef<number | null>(null);
  const limits = useRef<SessionLimits>(limitsForGroups(groups));

  limits.current = limitsForGroups(groups);

  // auth_time is when the user AUTHENTICATED, which is the only honest anchor
  // for an absolute cap. Read once per mount; Amplify decodes the payload.
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      try {
        const session = await fetchAuthSession();
        const claim = session.tokens?.idToken?.payload?.auth_time;
        if (!cancelled && typeof claim === 'number') authTime.current = claim * 1000;
      } catch {
        // Leave it null. A missing auth_time must not end a session -- see
        // expiryReason, which treats null as "absolute clock unavailable".
      }
    })();
    return () => { cancelled = true; };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;

    const markActive = () => {
      const now = Date.now();
      // Coalesce, never discard: the timestamp always advances once the window
      // has passed, so the idle clock restarts on every burst of activity.
      if (now - lastActivity.current >= ACTIVITY_THROTTLE_MS) {
        lastActivity.current = now;
        // Any activity also clears a visible warning -- the user is plainly
        // still there, so making them click "Stay signed in" would be theatre.
        setIdleWarningSeconds(prev => (prev === null ? prev : null));
      }
    };
    // A tab returning to the foreground is activity; a tab leaving is not.
    const onVisibility = () => { if (!document.hidden) markActive(); };

    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, markActive, { passive: true });
    }
    document.addEventListener('visibilitychange', onVisibility);

    const tick = setInterval(() => {
      const now = Date.now();
      const reason = expiryReason(limits.current, authTime.current, lastActivity.current, now);
      if (reason) {
        // `reason` rides on the query string so the sign-in screen can say WHY.
        // A session that vanishes with no explanation reads as a bug.
        signOut().catch(() => {}).finally(() => {
          window.location.assign(`/login?ended=${reason}`);
        });
        return;
      }
      const remaining = msUntilIdleSignOut(limits.current, lastActivity.current, now);
      setIdleWarningSeconds(
        remaining !== null && remaining <= WARN_BEFORE_MS
          ? Math.ceil(remaining / 1000)
          : null,
      );
    }, TICK_MS);

    return () => {
      clearInterval(tick);
      for (const evt of ACTIVITY_EVENTS) {
        window.removeEventListener(evt, markActive);
      }
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled]);

  return {
    idleWarningSeconds,
    staySignedIn: () => {
      lastActivity.current = Date.now();
      setIdleWarningSeconds(null);
    },
  };
}
