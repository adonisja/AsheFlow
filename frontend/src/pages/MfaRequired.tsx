import { useState } from 'react';
import { signOut } from 'aws-amplify/auth';
import { ShieldAlert, LogOut } from 'lucide-react';

import SecurityPanel from '../components/SecurityPanel';
import { useAuth } from '../contexts/AuthContext';

/** The wall a blocked privileged account meets (ADR-465 D1/D2).
 *
 *  Not a modal and not a banner: `ProtectedRoute` redirects here from every
 *  other route while `mfaStatus.blocked`, so there is no app state behind it
 *  to dismiss back to.
 *
 *  The only exits are enrolling or signing out. Signing out lands on /login,
 *  and the next successful sign-in returns here -- `blocked` is recomputed from
 *  Cognito every time, never from a dismissed flag. That loop IS the
 *  enforcement: refusing costs a sign-in and changes nothing.
 */
export default function MfaRequired() {
  const { mfaStatus } = useAuth();
  const [signingOut, setSigningOut] = useState(false);

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
                "required" reads as bureaucracy. */}
            <p className="text-sm text-muted-foreground mt-1">
              Your role can see and change things across the whole company, so
              AsheFlow needs a second factor before you can continue.
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
          {/* Said plainly rather than discovered: leaving does not skip this. */}
          <p className="text-xs text-subtle">
            Signing out will not skip this step. You will return here next time
            you sign in.
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
