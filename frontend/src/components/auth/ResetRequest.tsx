/**
 * "Can't use your authenticator?" — ask for a two-factor reset (ADR-551).
 *
 * Shown where a person is stuck: the code step of sign-in, and the
 * "Two-factor setup needed" refusal. Two steps, both on the sign-in card:
 * a code to the account's verified email (that proves the inbox owner is
 * asking), then the request goes to whoever can reset this account. It never
 * resets anything itself; a person does that.
 */
import { useState } from 'react';
import { KeyRound } from 'lucide-react';

import axiosClient from '../../api/axiosClient';
import { errorText } from '../../utils/errorText';

type Step = 'closed' | 'start' | 'code' | 'done';

/** `username` is the one the person just typed to reach this screen. They
 *  are not asked again (owner, 2026-10-20). The server resolves it to the
 *  account's permanent ID (Cognito sub, then the employee or contributor
 *  record) and keeps the request by that ID; nothing downstream uses the name. */
export default function ResetRequest({ username }: { username: string }) {
  const [step, setStep] = useState<Step>('closed');
  const name = username;
  const [code, setCode] = useState('');
  // ADR-551 D2b: the server's ticket from step 1. Unreadable here; it is what
  // tells step 2 which account, so the name is never sent again.
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState('');

  const send = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await axiosClient.post<{ request_token: string }>('/auth/mfa-reset/request', { username: name.trim() });
      setToken(data.request_token);
      setStep('code');
    } catch (err) {
      setError(errorText(err, 'Could not send the code. Try again.'));
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await axiosClient.post<{ detail: string }>('/auth/mfa-reset/confirm',
        { request_token: token, code: code.trim() });
      setResult(data.detail);
      setStep('done');
    } catch (err) {
      setError(errorText(err, 'Could not send the request. Try again.'));
    } finally { setBusy(false); }
  };

  if (step === 'closed') {
    return (
      <button type="button" onClick={() => setStep('start')}
              className="w-full text-sm text-primary hover:underline mt-3">
        Can't use your authenticator? Request a reset
      </button>
    );
  }

  return (
    <div className="mt-4 rounded-xl border border-border bg-surface-muted/40 p-4 space-y-3 text-sm" aria-live="polite">
      <p className="flex items-center gap-2 font-semibold text-foreground">
        <KeyRound className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
        Request a two-factor reset
      </p>

      {step === 'start' && (
        <>
          <p className="text-muted-foreground">
            We'll email a code to your account's address. Enter it here and your request goes to
            whoever can reset your account. Nothing changes until they do.
          </p>
          <p className="text-xs text-muted-foreground">
            For <span className="font-mono text-foreground">{name}</span>
          </p>
          {error && <p className="text-xs text-danger">{error}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={() => setStep('closed')} className="btn-ghost text-sm px-3 py-2">Cancel</button>
            <button type="button" onClick={send} disabled={busy || !name.trim()}
                    className="btn-primary text-sm px-4 py-2 disabled:opacity-50">
              {busy ? 'Sending…' : 'Email me a code'}
            </button>
          </div>
        </>
      )}

      {step === 'code' && (
        <>
          <p className="text-muted-foreground">
            If that account has a verified email, a code is on its way. It works once, for 10 minutes.
          </p>
          <label htmlFor="rr-code" className="block text-xs font-medium text-muted-foreground">Code from the email</label>
          <input id="rr-code" value={code} onChange={e => { setCode(e.target.value); setError(''); }}
                 inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000"
                 className="input-field font-mono tracking-widest" />
          {error && <p className="text-xs text-danger">{error}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={() => setStep('start')} className="btn-ghost text-sm px-3 py-2">Back</button>
            <button type="button" onClick={confirm} disabled={busy || code.trim().length < 6}
                    className="btn-primary text-sm px-4 py-2 disabled:opacity-50">
              {busy ? 'Sending…' : 'Send the request'}
            </button>
          </div>
        </>
      )}

      {step === 'done' && <p className="text-foreground">{result}</p>}
    </div>
  );
}
