/** Two-factor enrolment (ADR-362 phase 2).
 *
 *  This screen has to exist before anything enforces MFA. The PreAuthentication
 *  trigger refuses a privileged sign-in with "go to Account > Security to set it
 *  up" — pointing someone at a page that does not exist turns a security control
 *  into a lockout with no way out.
 *
 *  Two factors are offered because they suit different people. An authenticator
 *  app works offline and costs nothing, which fits someone at a desk. An emailed
 *  code needs no app at all, and every account already has a verified address —
 *  that matters for field staff, who are being asked to install nothing.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  setUpTOTP,
  verifyTOTPSetup,
  updateMFAPreference,
  fetchMFAPreference,
  getCurrentUser,
} from 'aws-amplify/auth';
import QRCode from 'qrcode';
import { ShieldCheck, Smartphone, Mail, CheckCircle2, AlertTriangle } from 'lucide-react';

export default function SecurityPanel() {
  const [enabled, setEnabled] = useState({ totp: false, email: false });
  const [preferred, setPreferred] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  /* TOTP setup state. The secret is shown alongside the QR because a desktop
     authenticator, or a phone camera that will not focus in a dim warehouse,
     needs a string to paste. */
  const [setupUri, setSetupUri] = useState<string | null>(null);
  const [setupSecret, setSetupSecret] = useState('');
  const [qrDataUrl, setQrDataUrl] = useState('');
  const [code, setCode] = useState('');

  const refresh = useCallback(async () => {
    try {
      const pref = await fetchMFAPreference();
      setEnabled({
        totp: pref.enabled?.includes('TOTP') ?? false,
        email: pref.enabled?.includes('EMAIL') ?? false,
      });
      setPreferred(pref.preferred ?? null);
    } catch {
      setError('Could not read your security settings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const beginTotp = async () => {
    setBusy(true); setError('');
    try {
      const output = await setUpTOTP();
      const user = await getCurrentUser();
      const uri = output.getSetupUri('AsheFlow', user.username).toString();
      setSetupUri(uri);
      setSetupSecret(output.sharedSecret);
      setQrDataUrl(await QRCode.toDataURL(uri, { margin: 1, width: 200 }));
    } catch {
      setError('Could not start setup. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const confirmTotp = async () => {
    setBusy(true); setError('');
    try {
      await verifyTOTPSetup({ code: code.trim() });
      // Enrolling without setting a preference leaves the factor registered and
      // never challenged, which looks like MFA and is not.
      await updateMFAPreference({ totp: 'PREFERRED' });
      setSetupUri(null); setCode('');
      await refresh();
    } catch {
      setError('That code was not accepted. Check the time on your device and try again.');
    } finally {
      setBusy(false);
    }
  };

  const toggleEmail = async (on: boolean) => {
    setBusy(true); setError('');
    try {
      await updateMFAPreference({ email: on ? 'ENABLED' : 'DISABLED' });
      await refresh();
    } catch {
      setError('Could not update your email code setting.');
    } finally {
      setBusy(false);
    }
  };

  const anyFactor = enabled.totp || enabled.email;

  /* ADR-386 layer 1. Neither client has a TOTP-disable path, so the only way to
     reach zero factors from this UI is turning email off while it is the only
     one. For a privileged user the PreAuthentication trigger then refuses their
     next sign-in outright, locking them out with no self-service path, because
     enrolment lives behind that sign-in.

     A UI affordance, NOT enforcement. Amplify calls Cognito directly with
     `aws.cognito.signin.user.admin`, a scope that cannot be stripped (ADR-377
     D1), so developer tools still reach it. That is why ADR-386 pairs this with
     detection and containment instead of trusting a hidden button. */
  const isLastFactor = enabled.email && !enabled.totp;

  if (loading) {
    return <div className="card"><p className="text-sm text-muted-foreground">Loading…</p></div>;
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3 mb-5">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <ShieldCheck className="w-4 h-4 text-primary" />
        </div>
        <h2 className="section-title">Two-Factor Authentication</h2>
      </div>

      {/* State first. Someone opening this page is answering "am I covered?" */}
      {anyFactor ? (
        <div className="flex items-center gap-2 text-success text-sm font-medium mb-5">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          Your account is protected by a second factor.
        </div>
      ) : (
        <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2.5 mb-5">
          <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />
          <p className="text-xs text-foreground leading-relaxed">
            No second factor is set up. Admin, management and dispatch accounts
            need one to sign in.
          </p>
        </div>
      )}

      {error && <p className="text-xs text-danger mb-4">{error}</p>}

      <div className="space-y-3">
        {/* Authenticator app */}
        <div className="rounded-xl border border-border p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="flex items-start gap-3 min-w-0">
              <Smartphone className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  Authenticator app
                  {preferred === 'TOTP' && (
                    <span className="ml-2 text-[10px] uppercase tracking-wide bg-accent rounded-md px-1.5 py-0.5">
                      default
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  A 6-digit code from an app on your phone. Works without signal.
                </p>
              </div>
            </div>
            {enabled.totp ? (
              <span className="text-xs text-success font-medium shrink-0">Enabled</span>
            ) : (
              <button
                onClick={beginTotp}
                disabled={busy || !!setupUri}
                className="btn-primary text-xs px-3 py-1.5 disabled:opacity-50 shrink-0"
              >
                Set up
              </button>
            )}
          </div>

          {setupUri && (
            <div className="mt-4 pt-4 border-t border-border space-y-3">
              <p className="text-xs text-muted-foreground">
                Scan this with your authenticator app, then enter the code it shows.
              </p>
              {qrDataUrl && (
                <img src={qrDataUrl} alt="Setup QR code" className="rounded-lg border border-border" />
              )}
              <div>
                <p className="text-[11px] text-muted-foreground mb-1">
                  Cannot scan? Enter this key instead:
                </p>
                <code className="block text-xs bg-accent rounded-lg px-3 py-2 break-all">
                  {setupSecret}
                </code>
              </div>
              <div className="flex items-center gap-2">
                <input
                  value={code}
                  onChange={e => { setCode(e.target.value); setError(''); }}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="000000"
                  className="input-field max-w-[8rem]"
                />
                <button
                  onClick={confirmTotp}
                  disabled={busy || code.trim().length < 6}
                  className="btn-primary text-xs px-3 py-2 disabled:opacity-50"
                >
                  {busy ? 'Checking…' : 'Confirm'}
                </button>
                <button
                  onClick={() => { setSetupUri(null); setCode(''); setError(''); }}
                  className="text-xs text-muted-foreground hover:text-foreground px-2"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Email code */}
        <div className="rounded-xl border border-border p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="flex items-start gap-3 min-w-0">
              <Mail className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  Emailed code
                  {preferred === 'EMAIL' && (
                    <span className="ml-2 text-[10px] uppercase tracking-wide bg-accent rounded-md px-1.5 py-0.5">
                      default
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Sent to your work email. No app to install.
                </p>
              </div>
            </div>
            <button
              onClick={() => toggleEmail(!enabled.email)}
              disabled={busy || isLastFactor}
              title={isLastFactor
                ? 'Set up an authenticator app first. An account cannot be left without a second factor.'
                : undefined}
              className={`text-xs px-3 py-1.5 rounded-lg border disabled:opacity-50 shrink-0 ${
                enabled.email
                  ? 'border-border hover:bg-accent text-foreground'
                  : 'border-primary bg-primary text-primary-foreground'
              }`}
            >
              {enabled.email ? 'Turn off' : 'Turn on'}
            </button>
          </div>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground mt-4">
        Lost your phone? An admin can reset your second factor.
      </p>
    </div>
  );
}
