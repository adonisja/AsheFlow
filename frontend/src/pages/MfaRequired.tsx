import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { ShieldAlert, LogOut } from 'lucide-react';

import SecurityPanel from '../components/SecurityPanel';
import { useAuth } from '../contexts/AuthContext';
import type { MfaStatus } from '../api/types';

/** The wall a blocked privileged account meets (ADR-465 D1/D2).
 *
 *  Not a modal and not a banner: `ProtectedRoute` redirects here from every
 *  other route while `mfaStatus.blocked`, so there is no app state behind it
 *  to dismiss back to.
 *
 *  The only exits are enrolling or signing out. Signing out lands on /login,
 *  and the next successful sign-in returns here -- `blocked` is recomputed from
 *  Cognito every time, never from a dismissed flag. For a privileged account
 *  that holds only inside the 24-hour enrolment window (ADR-548); after it,
 *  PreAuthentication refuses the sign-in, which is why the page states the
 *  deadline instead of promising a free sign-out.
 */
/** What signing out of the wall costs, AFTER the tier-neutral sentence
 *  (ADR-469: "will not skip this step" is true for both tiers and stays
 *  unbranched). Only the deadline differs (ADR-548 D4). */
function signOutDeadline(status: MfaStatus | null): string {
  if (status?.tier === 'field') {
    return 'You will return here next time you sign in.';
  }
  if (status?.setup_window_ends_at) {
    const ends = new Date(status.setup_window_ends_at).toLocaleString(undefined, {
      weekday: 'short', hour: 'numeric', minute: '2-digit',
    });
    return `You can come back to finish until ${ends}. After that, you'll need to request a reset from the sign-in screen.`;
  }
  // Deadline unreadable: say the rule rather than a time we do not have.
  return "You can come back to finish within 24 hours of your first sign-in. After that, you'll need to request a reset from the sign-in screen.";
}

export default function MfaRequired() {
  const { mfaStatus, groups } = useAuth();
  const isSurveyorOnly = groups.includes('surveyor')
    && !groups.some(g => g === 'super_admin' || g === 'platform_support');
  const [signingOut, setSigningOut] = useState(false);

  /* ADR-527. The router sends a blocked account HERE, but nothing sent it back:
     after enrolling, SecurityPanel re-fetches mfaStatus (ADR-393) and blocked
     turns false, yet this route kept rendering the wall, so a user who had just
     finished was stuck with signing out as the only way off the page (seen on
     prod, 2026-10-16). Leaving is the reward for enrolling, not a bypass:
     blocked is still recomputed from Cognito on every load. Waits for a KNOWN
     status (non-null) so a page load never flashes past the wall. */
  if (mfaStatus && !mfaStatus.blocked) {
    return <Navigate to="/" replace />;
  }

  const handleSignOut = async () => {
    setSigningOut(true);
    try { await signOut(); } catch { /* already signed out; leave anyway */ }
    window.location.assign('/login');
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg space-y-6 animate-slide-up">

        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-warning/15 mx-auto">
            <ShieldAlert className="w-7 h-7 text-warning" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-foreground tracking-tight">
              Set up two-factor authentication
            </h1>
            {/* Says what is true now, not what failed. This account has access
                worth protecting, which is WHY the wall exists -- a bare
                "required" reads as bureaucracy.

                ADR-469 D4. TWO audiences, because `blocked` has two causes. A
                privileged account is blocked from its first sign-in and holds
                company-wide access (ADR-377: no grace). A FIELD account is
                blocked only after its 14-day window closes -- and telling a
                walker on day 15 that their role "can see and change things
                across the whole company" is untrue and reads as a mistake on a
                page that gives them no way past it. */}
            <p className="text-sm text-muted-foreground mt-1">
              {mfaStatus?.tier === 'field'
                ? <>Your {mfaStatus.grace_days_total}-day window to set this up
                    has passed, so AsheFlow needs a second factor before you can
                    continue.</>
                : isSurveyorOnly
                  /* ADR-549 D1: true for a surveyor, unlike "across the whole
                     company" -- what they protect is their own attestation. */
                  ? <>Survey records carry your name and your signed agreement,
                      so AsheFlow needs a second factor before you can continue.</>
                  : <>Your role can see and change things across the whole company,
                      so AsheFlow needs a second factor before you can continue.</>}
            </p>
          </div>
        </div>

        <div className="card p-5">
          <SecurityPanel />
        </div>

        <div className="text-center space-y-3">
          <p className="text-xs text-subtle">
            You will need an authenticator app such as Google Authenticator,
            1Password or Authy. Nothing else in AsheFlow is reachable until this
            is finished.
          </p>
          <button
            onClick={handleSignOut}
            disabled={signingOut}
            className="btn-ghost inline-flex items-center gap-1.5 text-sm text-muted-foreground disabled:opacity-50"
          >
            <LogOut className="w-3.5 h-3.5" />
            {signingOut ? 'Signing out…' : 'Sign out instead'}
          </button>
          {/* Said plainly rather than discovered: leaving does not skip this.
              ADR-548 D4: for a privileged account it also has a deadline. The
              old line ("you will return here next time you sign in") was false
              for them -- signing out spent their only pass -- and is now true
              only until setup_window_ends_at. */}
          <p className="text-xs text-subtle">
            Signing out will not skip this step. {signOutDeadline(mfaStatus)}
          </p>
        </div>

        {mfaStatus?.enrolled === null && (
          <p className="text-center text-xs text-warning">
            We could not confirm your setup status just now. If you have already
            enrolled, sign out and back in.
          </p>
        )}
      </div>
    </div>
  );
}
