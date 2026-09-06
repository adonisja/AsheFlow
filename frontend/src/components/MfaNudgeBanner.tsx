import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldAlert, ShieldX, X } from 'lucide-react';

import { useAuth } from '../contexts/AuthContext';

/** The warning half of ADR-377's grace period (ADR-381 D1).
 *
 *  The PreAuthentication trigger is LIVE on both pools, and until this existed
 *  the grace clock ran invisibly: a field user's first sign-in started a 14-day
 *  countdown they could not see, and the first thing they learned about it was
 *  being refused. That is the wall without the nudge — the exact failure ADR-362
 *  named when it insisted enrolment ship before enforcement.
 *
 *  ADR-377 D2 chose Okta's shape deliberately: nudge from day one with a "not
 *  now" that shows days remaining, then stop offering the skip when the window
 *  closes. This is that nudge.
 */
export default function MfaNudgeBanner() {
  const { mfaStatus } = useAuth();
  const [dismissed, setDismissed] = useState(false);

  /* `enrolled === null` means Cognito could not be read — NOT "no MFA
     required". is_enrolled returns null rather than false for exactly this
     reason: false past the deadline BLOCKS, so an AWS hiccup must not read as a
     lockout. Rendering nothing is the only correct behaviour; a banner here
     would nag someone who is already enrolled. */
  if (!mfaStatus || mfaStatus.enrolled === null) return null;
  if (!mfaStatus.required || mfaStatus.enrolled) return null;

  const { blocked, days_remaining } = mfaStatus;

  /* A blocked user cannot dismiss. There is nothing to come back to later —
     they are already refused at sign-in — so a dismissable banner would hide
     the only explanation they have. */
  if (dismissed && !blocked) return null;

  const tone = blocked
    ? { bg: 'bg-danger/10', border: 'border-danger/30',
        icon: <ShieldX className="w-4 h-4 text-danger shrink-0 mt-0.5" /> }
    : { bg: 'bg-warning/10', border: 'border-warning/30',
        icon: <ShieldAlert className="w-4 h-4 text-warning shrink-0 mt-0.5" /> };

  /* Says what is now true, not what failed. "Two-factor authentication is
     required" tells someone what to do; "MFA enforcement active" does not. */
  const headline = blocked
    ? 'Two-factor authentication is required to keep using AsheFlow'
    : 'Set up two-factor authentication';

  /* Round-up already happened server-side, so 1 means "today or tomorrow" and
     never a bare 0 on an account that still works. */
  const detail = blocked
    ? 'Your account is restricted until you set it up.'
    : `You have ${days_remaining} day${days_remaining === 1 ? '' : 's'} left.`;

  return (
    <div className={`rounded-lg border ${tone.border} ${tone.bg} p-3 flex items-start gap-3`}>
      {tone.icon}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{headline}</p>
        <p className="text-sm text-muted-foreground mt-0.5">
          {detail}{' '}
          <Link to="/account" className="underline font-medium hover:opacity-80">
            Open Account &rsaquo; Security
          </Link>
          {/* The same destination the PreAuthentication trigger names, so the
              two instructions cannot diverge. */}
        </p>
      </div>
      {!blocked && (
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss until next sign-in"
          className="text-muted-foreground/60 hover:text-foreground transition-colors shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}
