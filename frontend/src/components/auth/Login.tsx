import React, { useState, useEffect } from 'react';
import { signIn, signInWithRedirect, confirmSignIn } from 'aws-amplify/auth';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { Eye, EyeOff } from 'lucide-react';
import logoFull from '../../assets/logo-full.svg';
import logoFullLight from '../../assets/logo-full-light.svg';

export default function Login() {
  const [username,               setUsername]               = useState('');
  const [password,               setPassword]               = useState('');
  const [newPassword,            setNewPassword]            = useState('');
  const [error,                  setError]                  = useState('');
  const [successMsg,             setSuccessMsg]             = useState('');
  const [isNewPasswordRequired,  setIsNewPasswordRequired]  = useState(false);
  const [showPassword,           setShowPassword]           = useState(false);
  const [showNewPassword,        setShowNewPassword]        = useState(false);

  const navigate = useNavigate();
  const { isAuthenticated, checkAuth, federatedError, clearFederatedError } = useAuth();

  useEffect(() => {
    if (isAuthenticated) navigate('/');
  }, [isAuthenticated, navigate]);

  // Show federated error (from Hub signIn_failure) as the page-level error,
  // then clear it so it doesn't persist across retries.
  useEffect(() => {
    if (federatedError) {
      setError(federatedError);
      clearFederatedError();
    }
  }, [federatedError, clearFederatedError]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');

    try {
      if (isNewPasswordRequired) {
        const response = await confirmSignIn({ challengeResponse: newPassword });
        if (response.isSignedIn) {
          await checkAuth();
        } else {
          setError(`Action required: ${response.nextStep?.signInStep}`);
        }
      } else {
        const response = await signIn({
          username,
          password,
          options: { authFlowType: 'USER_PASSWORD_AUTH' },
        });

        if (response.nextStep?.signInStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED') {
          setIsNewPasswordRequired(true);
          setSuccessMsg('You are logging in with a temporary password. Please set a new permanent password.');
        } else if (response.isSignedIn) {
          await checkAuth();
        } else {
          setError(`Action required: ${response.nextStep?.signInStep}`);
        }
      }
    } catch (err: any) {
      setError(err.message || 'Sign in failed. Check your credentials.');
    }
  };

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

      <div className="w-full max-w-sm animate-slide-up relative z-10">
        {/* Logo */}
        <div className="flex items-center justify-center mb-10">
          {/* The wordmark is a baked-SVG, so it cannot follow the theme. Its dark
              text vanished on the navy background once this page started
              honouring dark mode. `logo-full-light.svg` already existed for
              exactly this and was wired up nowhere. */}
          <img src={logoFull} alt="AsheFlow" className="h-10 w-auto dark:hidden" />
          <img src={logoFullLight} alt="" aria-hidden className="h-10 w-auto hidden dark:block" />
        </div>

        <div className="card-elevated p-8 backdrop-blur-sm bg-card/90">
          <h2 className="text-xl font-semibold text-center text-foreground mb-1">
            {isNewPasswordRequired ? 'Update Password' : 'Welcome back'}
          </h2>
          <p className="text-subtle text-center mb-8">
            {isNewPasswordRequired
              ? 'A new password is required to continue'
              : 'Sign in to your AsheFlow account'}
          </p>

          {error && (
            <div className="bg-danger/5 text-danger px-4 py-3 rounded-xl mb-6 text-sm font-medium border border-danger/20">
              {error}
            </div>
          )}

          {successMsg && (
            <div className="bg-success/5 text-success px-4 py-3 rounded-xl mb-6 text-sm font-medium border border-success/20">
              {successMsg}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isNewPasswordRequired ? (
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">New Password</label>
                <div className="relative">
                  {/* Deliberately no placeholder: a password input masks its value with
                      bullets, so a bullet PLACEHOLDER is indistinguishable from an
                      already-entered password — the user cannot tell if the field is
                      empty. Worse in dark mode, where the two sit closer in luminance. */}
                  <input
                    type={showNewPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    required
                    className="input-field pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword(v => !v)}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
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
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </>
            )}

            <button type="submit" className="btn-primary w-full mt-2">
              {isNewPasswordRequired ? 'Set new password' : 'Sign in'}
            </button>
          </form>

          {/* Federation — for employees whose Cognito account is linked to Discord/Google */}
          {!isNewPasswordRequired && (
            <div className="mt-8">
              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-border" />
                </div>
                <div className="relative flex justify-center text-xs">
                  <span className="px-3 bg-card text-muted-foreground uppercase tracking-wider">or</span>
                </div>
              </div>

              <div className="mt-6 space-y-3">
                <button
                  type="button"
                  onClick={() => signInWithRedirect({ provider: { custom: 'Discord' } })}
                  className="btn-secondary w-full flex items-center justify-center gap-2"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z"/>
                  </svg>
                  Continue with Discord
                </button>
                <button
                  type="button"
                  onClick={() => signInWithRedirect({ provider: 'Google' })}
                  className="btn-secondary w-full flex items-center justify-center gap-2"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                  Continue with Google
                </button>
              </div>

              <p className="text-center text-xs text-muted-foreground mt-6 text-balance">
                Accounts are managed by your dispatcher.{' '}
                <span className="text-foreground font-medium">No self-signup.</span>
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
