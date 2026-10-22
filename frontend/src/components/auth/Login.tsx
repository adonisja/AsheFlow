import React, { useState, useEffect } from 'react';
import { signIn, confirmSignIn } from 'aws-amplify/auth';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { Eye, EyeOff } from 'lucide-react';
import { classifySignInError } from '../../utils/signInError';
import ResetRequest, { ResetRequestLink, type ResetSent } from './ResetRequest';
import SignInNotice from './SignInNotice';
import SetupKey from './SetupKey';
import QRCode from 'qrcode';
import logoFull from '../../assets/logo-full.svg';
import logoFullLight from '../../assets/logo-full-light.svg';

export default function Login() {
  const [username,               setUsername]               = useState('');
  const [password,               setPassword]               = useState('');
  const [newPassword,            setNewPassword]            = useState('');
  const [error,                  setError]                  = useState('');
  // ADR-548 D5: the enrolment-window refusal is a state, not an error.
  const [mfaSetupClosed,         setMfaSetupClosed]         = useState(false);
  const [successMsg,             setSuccessMsg]             = useState('');
  /* ADR-556 D3. The reset request is the card while it's open; on success the
     card returns to sign-in with the username kept and this next step. */
  const [resetOpen,              setResetOpen]              = useState(false);
  const [resetSent,              setResetSent]              = useState<ResetSent | null>(null);
  /* Written by useSessionTimeout on the way out (ADR-463). Read once: a
     reload should not keep re-announcing an old sign-out. */
  const [sessionEnded] = useState<string | null>(() => {
    // The URL, or the reason axiosClient stored before signing out (it can lose
    // the race to App's plain <Navigate to="/login">). Read once, then cleared.
    let stored: string | null = null;
    try {
      stored = sessionStorage.getItem('asheflow_session_ended');
      sessionStorage.removeItem('asheflow_session_ended');
    } catch { /* private mode */ }
    const v = new URLSearchParams(window.location.search).get('ended') ?? stored;
    return v === 'idle' || v === 'absolute' || v === 'credentials'
      || v === 'password' || v === 'email' ? v : null;
  });
  /* ADR-556 D5: who to contact after a forced sign-out. Written beside the
     reason by axiosClient; a platform account has no manager. Null = unknown. */
  const [endedAudience] = useState<'platform' | 'employee' | null>(() => {
    try {
      const a = sessionStorage.getItem('asheflow_session_ended_audience');
      sessionStorage.removeItem('asheflow_session_ended_audience');
      return a === 'platform' || a === 'employee' ? a : null;
    } catch { return null; }
  });
  /* ADR-362 — the step sign-in stopped on, if any.
     This was a single `isNewPasswordRequired` boolean plus a catch-all that
     rendered `Action required: CONFIRM_SIGN_IN_WITH_TOTP_CODE` and went no
     further: a dead end for every challenge except the one it knew. */
  const [challengeStep, setChallengeStep] = useState<
    | 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED'
    | 'CONFIRM_SIGN_IN_WITH_TOTP_CODE'
    | 'CONFIRM_SIGN_IN_WITH_EMAIL_CODE'
    | 'CONTINUE_SIGN_IN_WITH_MFA_SELECTION'
    | 'CONTINUE_SIGN_IN_WITH_TOTP_SETUP'
    | null
  >(null);
  const [mfaOptions, setMfaOptions] = useState<string[]>([]);
  /* ADR-386/387. Enrolment normally lives at /account, behind a completed
     sign-in. This challenge is the case where the user CANNOT complete one --
     a privileged account whose factor was removed, or any account under a pool
     that requires MFA. Without handling it here they are told to "contact your
     admin" with no way forward, and mobile's advice is to use this very screen. */
  const [totpSetupUri, setTotpSetupUri] = useState<string | null>(null);
  const [totpSecret, setTotpSecret] = useState('');
  const [totpQr, setTotpQr] = useState('');
  const [showPassword,           setShowPassword]           = useState(false);
  const [showNewPassword,        setShowNewPassword]        = useState(false);
  /* ADR-479. Covers the whole submit, INCLUDING the checkAuth that follows a
     successful confirm -- that call makes five serialised network round-trips,
     and it is the part the user was left staring at a stale form through. */
  const [submitting, setSubmitting] = useState(false);

  const navigate = useNavigate();
  const { isAuthenticated, checkAuth } = useAuth();

  useEffect(() => {
    if (isAuthenticated) navigate('/');
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setMfaSetupClosed(false);
    setSuccessMsg('');
    setResetSent(null);

    /* Read whatever step Amplify reports and put the matching field on screen.
       Amplify chains: choosing a factor resolves to the challenge for its code,
       so this runs after confirmSignIn too. */
    const advance = (response: { isSignedIn: boolean; nextStep?: { signInStep?: string; allowedMFATypes?: string[] } }) => {
      const step = response.nextStep?.signInStep;
      /* ADR-479. Do NOT clear challengeStep here.
         It used to be cleared before awaiting checkAuth, which left this
         component mounted with challengeStep null for the whole of that call --
         five serialised round-trips -- and null is what renders the logged-out
         username/password form. A fully authenticated user was shown the
         sign-in screen for over a second.
         Nothing needs to clear it now: checkAuth sets isAuthenticated, the
         effect above navigates to '/', and Login unmounts with its state. A
         .finally here would be a setState on an unmounted component -- a no-op
         that reads like it matters. The challenge UI stays up until the route
         changes, which is exactly as long as the sign-in is still finishing. */
      if (response.isSignedIn) { return checkAuth(); }

      switch (step) {
        case 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED':
          setChallengeStep(step);
          setSuccessMsg('You are logging in with a temporary password. Please set a new permanent password.');
          return;
        case 'CONFIRM_SIGN_IN_WITH_TOTP_CODE':
          setChallengeStep(step);
          setSuccessMsg('Enter the 6-digit code from your authenticator app.');
          return;
        case 'CONFIRM_SIGN_IN_WITH_EMAIL_CODE':
          setChallengeStep(step);
          setSuccessMsg('We emailed you a sign-in code.');
          return;
        case 'CONTINUE_SIGN_IN_WITH_TOTP_SETUP': {
          /* Amplify hands us the shared secret on the nextStep. Build the
             otpauth:// URI ourselves rather than calling setUpTOTP(): that helper
             is for a SIGNED-IN user and there is no session here yet. */
          const secret =
            (response.nextStep as { totpSetupDetails?: { sharedSecret?: string } })
              ?.totpSetupDetails?.sharedSecret ?? '';
          const uri = secret
            ? `otpauth://totp/AsheFlow:${encodeURIComponent(username)}`
              + `?secret=${secret}&issuer=AsheFlow`
            : '';
          setChallengeStep(step);
          setTotpSecret(secret);
          setTotpSetupUri(uri);
          if (uri) {
            QRCode.toDataURL(uri, { margin: 1, width: 180 })
              .then(setTotpQr)
              /* A missing QR is recoverable: the secret is shown as text and can
                 be typed in. Failing the whole sign-in over it would not be. */
              .catch(() => setTotpQr(''));
          }
          setSuccessMsg('Scan this with your authenticator app, then enter the code it shows.');
          return;
        }
        case 'CONTINUE_SIGN_IN_WITH_MFA_SELECTION':
          setChallengeStep(step);
          setMfaOptions(response.nextStep?.allowedMFATypes ?? []);
          setSuccessMsg('Choose how you want to confirm it is you.');
          return;
        default:
          // Still a catch-all, but it now names a step nobody has implemented
          // rather than one that was simply never handled.
          setError(
            step
              ? `This account needs a sign-in step this app does not support yet (${step}). Contact your admin.`
              : 'Sign in did not complete. Please try again.',
          );
      }
    };

    setSubmitting(true);
    try {
      if (challengeStep) {
        // One field serves every challenge: a new password, a 6-digit code, or
        // a chosen factor. Amplify takes them all as challengeResponse.
        await advance(await confirmSignIn({ challengeResponse: newPassword }));
        setNewPassword('');
      } else {
        await advance(await signIn({
          username,
          password,
          options: { authFlowType: 'USER_PASSWORD_AUTH' },
        }));
      }
    } catch (err: any) {
      const problem = classifySignInError(err?.message, 'Sign in failed. Check your credentials.');
      if (problem.kind === 'mfa_setup_closed') setMfaSetupClosed(true);
      else setError(problem.text);
    } finally {
      setSubmitting(false);
    }
  };

  /* ADR-529. Leave a challenge and return to the username/password form.
     There is no session to end: a challenge comes before any tokens exist.
     Amplify's half-finished attempt (CognitoSignInState.* in sessionStorage)
     is not cleared by signOut() and has no public reset; the next signIn
     replaces it and it expires on its own in 3 minutes. So this is a reset of
     what is on screen, not a sign-out. The username stays so a retry, or a
     typo fix, is one field away -- same as mobile's Start over. */
  const backToSignIn = () => {
    setChallengeStep(null);
    setNewPassword('');
    setPassword('');
    setMfaOptions([]);
    setTotpSetupUri(null);
    setTotpSecret('');
    setTotpQr('');
    setError('');
    setSuccessMsg('');
  };

  const isNewPassword = challengeStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED';
  const COPY: Record<string, { heading: string; sub: string; label: string; submit: string }> = {
    CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED: {
      heading: 'Update Password', sub: 'A new password is required to continue',
      label: 'New Password', submit: 'Set new password',
    },
    CONTINUE_SIGN_IN_WITH_TOTP_SETUP: {
      heading: 'Set up two-factor authentication',
      sub: 'Your account needs an authenticator app before you can sign in',
      label: 'Code from your app', submit: 'Verify and finish',
    },
    CONFIRM_SIGN_IN_WITH_TOTP_CODE: {
      heading: 'Enter your code', sub: 'From your authenticator app',
      label: 'Authentication code', submit: 'Verify',
    },
    CONFIRM_SIGN_IN_WITH_EMAIL_CODE: {
      heading: 'Check your email', sub: 'We sent you a sign-in code',
      label: 'Emailed code', submit: 'Verify',
    },
    CONTINUE_SIGN_IN_WITH_MFA_SELECTION: {
      heading: 'Choose a method', sub: 'How would you like to confirm it is you?',
      label: 'Method', submit: 'Continue',
    },
  };
  const copy = challengeStep ? COPY[challengeStep] : null;

  return (
    <div className="flex min-h-screen items-center justify-center px-4 relative overflow-hidden bg-background">
      {/* `bg-background`, not an inline gradient. This page hardcoded three
          near-white HSL stops in a `style` attribute, which CANNOT respond to
          the `dark` class — so the card went dark while the page behind it
          stayed white. The blob colours were also the RETIRED indigo/amber
          identity (plan §2.7). Matches Layout.tsx / SuperAdminLayout.tsx.

          Blobs are token-driven so they follow the theme; opacity is lifted in
          dark, where the surface sits closer to them in tone. */}
      <div className="absolute top-[-20%] left-[-10%] w-[500px] h-[500px] rounded-full opacity-20 dark:opacity-25"
           style={{ background: 'radial-gradient(circle, hsl(var(--primary) / 0.30), transparent 70%)' }} />
      <div className="absolute bottom-[-20%] right-[-10%] w-[400px] h-[400px] rounded-full opacity-15 dark:opacity-20"
           style={{ background: 'radial-gradient(circle, hsl(var(--brand) / 0.20), transparent 70%)' }} />

      <div className="layout-auth animate-slide-up relative z-10">
        {/* Logo */}
        <div className="flex items-center justify-center mb-10">
          {/* The wordmark is a baked-SVG, so it cannot follow the theme. Its dark
              text vanished on the navy background once this page started
              honouring dark mode. `logo-full-light.svg` already existed for
              exactly this and was wired up nowhere. */}
          <img src={logoFull} alt="AsheFlow" className="h-10 w-auto dark:hidden" />
          <img src={logoFullLight} alt="" aria-hidden className="h-10 w-auto hidden dark:block" />
        </div>

        <div className="card-elevated p-6 sm:p-8 2xl:p-10 backdrop-blur-sm bg-card/90">
          <h2 className="text-xl font-semibold text-center text-foreground mb-1">
            {resetOpen ? 'Request a two-factor reset' : copy ? copy.heading : 'Welcome back'}
          </h2>
          <p className="text-subtle text-center mb-8">
            {resetOpen ? "For when you can't use your authenticator"
              : copy ? copy.sub : 'Sign in to your AsheFlow account'}
          </p>

          {resetOpen ? (
            <ResetRequest
              username={username}
              onCancel={() => setResetOpen(false)}
              onSent={result => {
                // Back to the username/password form. backToSignIn keeps the
                // username, so the next attempt is one field away.
                backToSignIn();
                setMfaSetupClosed(false);
                setResetOpen(false);
                setResetSent(result);
              }}
            />
          ) : (
          <>
          {/* ADR-556 D3: what happens next, after a reset request. */}
          {resetSent && !challengeStep && (
            <SignInNotice tone="success" title={`Request sent to ${resetSent.sentTo}`}>
              <p>{resetSent.nextStep}</p>
            </SignInNotice>
          )}

          {/* ADR-548 D5. Not red: the person did nothing wrong, and there is one
              way out. Says what happened, then what to do, in that order. */}
          {/* ADR-548 D5. Not red: the person did nothing wrong, and there is
              one way out. What happened, then what to do. */}
          {mfaSetupClosed && (
            <SignInNotice tone="warning" title="Two-factor setup needed">
              <p>
                This account needs two-factor authentication, and the 24 hours
                to set it up after your first sign-in have passed.
              </p>
              <p>
                <span className="font-medium text-foreground">What to do: </span>
                request a reset below. Once someone resets it, sign in again
                and you will go straight to setup.
              </p>
            </SignInNotice>
          )}

          {error && (
            <div className="bg-danger/5 text-danger px-4 py-3 rounded-xl mb-6 text-sm font-medium border border-danger/20">
              {error}
            </div>
          )}

          {/* ADR-463. A session that vanishes with no explanation reads as a
              crash, and the user's next move is to report a bug. Styled as an
              error, not a success: the user lost work-in-progress. */}
          {/* ADR-529 D3: hidden once a challenge is up -- it explains the LAST
              session, and in red over a code field it reads as this attempt
              failing. */}
          {/* ADR-541: 'password' / 'email' are this person's own change, so
              they read as a success; 'credentials' is another device's change
              ending this session, which the person needs to notice. */}
          {/* ADR-556 D5. One notice per reason. 'credentials' is ONE server code
              for a password change, an email change and a two-factor reset (one
              stamp ends them all), so its wording names all three. */}
          {sessionEnded && !challengeStep && (
            sessionEnded === 'password' ? (
              <SignInNotice tone="success" title="Password changed">
                <p>You were signed out everywhere. Sign in with your new password.</p>
              </SignInNotice>
            ) : sessionEnded === 'email' ? (
              <SignInNotice tone="success" title="Email updated">
                <p>You were signed out everywhere. Sign in to continue.</p>
              </SignInNotice>
            ) : sessionEnded === 'credentials' ? (
              <SignInNotice tone="warning" title="You were signed out on every device">
                <p>This account's password, email or two-factor sign-in was changed. Sign in again to continue.</p>
                <p>
                  <span className="font-medium text-foreground">Didn't expect this? </span>
                  {endedAudience === 'platform' ? 'Contact AsheFlow support straight away.'
                    : endedAudience === 'employee' ? 'Tell your manager straight away.'
                    : 'Tell whoever manages your account straight away.'}
                </p>
              </SignInNotice>
            ) : (
              <SignInNotice tone="info" title={sessionEnded === 'idle' ? 'Signed out after inactivity' : 'Your session reached its time limit'}>
                <p>Sign in to continue.</p>
              </SignInNotice>
            )
          )}

          {successMsg && (
            /* ADR-556 D5: a step's instruction, not a success -- it was a green
               box over every challenge. Plain text under the heading now; the
               card's one notice slot is for things that happened. */
            <p className="text-sm text-muted-foreground text-center -mt-4 mb-6">{successMsg}</p>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {challengeStep === 'CONTINUE_SIGN_IN_WITH_MFA_SELECTION' ? (
              /* A choice between two factors is a pair of buttons, not a text
                 field the user has to guess the spelling of. */
              <div className="space-y-2">
                {mfaOptions.map(opt => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => { setNewPassword(opt); }}
                    className={`w-full text-left px-4 py-3 rounded-xl border transition-colors ${
                      newPassword === opt
                        ? 'border-primary bg-primary/5 text-foreground'
                        : 'border-border hover:bg-accent text-foreground'
                    }`}
                  >
                    {opt === 'TOTP' ? 'Authenticator app' : opt === 'EMAIL' ? 'Emailed code' : opt}
                  </button>
                ))}
              </div>
            ) : challengeStep ? (
              <div>
                {/* The enrolment half of the setup challenge. Shown above the
                    code field because the user must scan BEFORE they can have a
                    code to type. */}
                {challengeStep === 'CONTINUE_SIGN_IN_WITH_TOTP_SETUP' && totpSetupUri && (
                  <div className="mb-4 rounded-xl border border-border p-4 text-center">
                    {totpQr ? (
                      <img
                        src={totpQr}
                        alt="QR code for your authenticator app"
                        className="mx-auto rounded-lg"
                        width={180}
                        height={180}
                      />
                    ) : null}
                    {/* Always shown, not a fallback. A phone cannot scan a QR on
                        its own screen, so the typed secret is the ONLY path for
                        anyone signing in from the device holding the
                        authenticator. */}
                    {/* ADR-557: open it in the app or copy it, never retype it. */}
                    <div className="mt-3"><SetupKey secret={totpSecret} uri={totpSetupUri} /></div>
                  </div>
                )}
                <label className="block text-sm font-medium text-foreground mb-1.5">{copy!.label}</label>
                <div className="relative">
                  {/* Deliberately no placeholder: a password input masks its value with
                      bullets, so a bullet PLACEHOLDER is indistinguishable from an
                      already-entered password — the user cannot tell if the field is
                      empty. Worse in dark mode, where the two sit closer in luminance. */}
                  {/* A one-time code is not a secret to hide: masking it stops
                      the user checking what they typed, and the eye toggle is
                      noise. autoComplete="one-time-code" lets the browser and
                      iOS offer it from the email or authenticator. */}
                  <input
                    type={isNewPassword ? (showNewPassword ? 'text' : 'password') : 'text'}
                    inputMode={isNewPassword ? undefined : 'numeric'}
                    autoComplete={isNewPassword ? 'new-password' : 'one-time-code'}
                    autoFocus
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    required
                    className={isNewPassword ? 'input-field pr-10' : 'input-field'}
                  />
                  {isNewPassword && (
                    <button
                      type="button"
                      onClick={() => setShowNewPassword(v => !v)}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">Username</label>
                  <input
                    type="text"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    required
                    className="input-field"
                    placeholder="danny.rivera"
                    autoComplete="username"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      required
                      className="input-field pr-10"
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(v => !v)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      aria-pressed={showPassword}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </>
            )}

            {/* ADR-479 D2/D3. Disabled while in flight: without this the form is
                re-submittable during every challenge, and a one-time code sent
                twice fails with NotAuthorizedException -- surfacing "Sign in
                failed" on a sign-in that actually succeeded.
                The label names the wait rather than spinning anonymously; the
                app knows exactly what it is doing here. */}
            <button
              type="submit"
              disabled={submitting}
              className="btn-primary w-full mt-2 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {submitting
                ? (challengeStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED'
                    ? 'Saving your password...'
                    : 'Signing you in...')
                : copy ? copy.submit : 'Sign in'}
            </button>

            {/* ADR-529. The way out of every challenge step. Disabled in flight
                (D2): backing out mid-confirm would show the logged-out form
                while a sign-in that is about to succeed navigates away. */}
            {challengeStep && (
              <button
                type="button"
                onClick={backToSignIn}
                disabled={submitting}
                className="w-full text-sm text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Back to sign in
              </button>
            )}
          </form>

          {/* ADR-551 D1: the way out for someone who can't produce a code, or
              whose setup window closed. */}
          {(challengeStep === 'CONFIRM_SIGN_IN_WITH_TOTP_CODE'
            || challengeStep === 'CONFIRM_SIGN_IN_WITH_EMAIL_CODE'
            || mfaSetupClosed) && <ResetRequestLink onOpen={() => { setError(''); setResetOpen(true); }} />}

          {/* ADR-560: password sign-in only; Discord/Google sign-in removed. */}
          {!challengeStep && (
            <p className="text-center text-xs text-muted-foreground mt-8 text-balance">
              Accounts are managed by your dispatcher.{' '}
              <span className="text-foreground font-medium">No self-signup.</span>
            </p>
          )}
          </>
          )}
        </div>
      </div>
    </div>
  );
}
