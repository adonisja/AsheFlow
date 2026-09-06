import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ShieldAlert, ShieldX } from 'lucide-react';

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
        cta: 'bg-danger hover:bg-danger/90 focus-visible:ring-danger',
        icon: <ShieldX className="w-4 h-4 text-danger shrink-0 mt-0.5" /> }
    : { bg: 'bg-warning/10', border: 'border-warning/30',
        cta: 'bg-warning hover:bg-warning/90 focus-visible:ring-warning',
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
    <div
      className={`rounded-lg border ${tone.border} ${tone.bg} px-6 pt-2 pb-1
                  w-full flex flex-col gap-0`}
    >
      {/* Wide: one row — the two text lines pinned left, the button pinned
          right, `items-stretch` making it span the full height of BOTH lines.
          Narrow: a column, button full-width under the text. Forcing the row
          on a phone wrapped the blocked headline to four lines and stretched
          the button into a slab beside it (measured at 390px). */}
      <div className="flex flex-col sm:flex-row sm:items-stretch
                      sm:justify-between gap-2 sm:gap-4">
        <div className="flex items-start gap-3 min-w-0 grow">
          {tone.icon}
          <div className="min-w-0">
            <p className="text-sm font-medium">{headline}</p>
            <p className="text-sm text-muted-foreground mt-0.5">{detail}</p>
          </div>
        </div>

        {/* The CTA is a solid button rather than an underlined phrase buried
            mid-sentence — it is the only thing this banner exists to drive.
            /account is the same destination the PreAuthentication trigger
            names, so the two cannot diverge. */}
        <Link
          to="/account"
          className={`inline-flex items-center justify-center gap-1.5
                      w-full sm:w-auto sm:shrink-0
                      px-5 min-h-[44px] rounded-lg text-sm font-medium text-white
                      transition-colors focus-visible:outline-none
                      focus-visible:ring-2 focus-visible:ring-offset-2
                      ${tone.cta}`}
        >
          {blocked ? 'Set up now' : 'Set up'}
          <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>

      {/* "Skip" rather than a bare ×: the action is "not now, ask me again
          next sign-in" (ADR-377 D2's Okta shape), and × would promise a
          permanent close this banner does not honour. Centred beneath the row,
          and kept at 36px rather than the CTA's 44 — it sits under a large
          button with clear space around it, and a second full-height row made
          the banner noticeably taller for the secondary choice. */}
      {!blocked && (
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="self-center px-4 py-0.5 rounded-lg text-sm font-medium
                     text-muted-foreground hover:text-foreground
                     hover:bg-foreground/5 transition-colors"
        >
          Skip
        </button>
      )}
    </div>
  );
}
