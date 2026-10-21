/**
 * "Can't use your authenticator?" — ask for a two-factor reset (ADR-551).
 *
 * Shown where a person is stuck: the code step of sign-in, and the
 * "Two-factor setup needed" refusal. Two steps, both on the sign-in card:
 * a code to the account's verified email (that proves the inbox owner is
 * asking), then the request goes to whoever can reset this account. It never
 * resets anything itself; a person does that.
 *
 * ADR-556 D3: while open this IS the sign-in card's content, not a box under
 * a live code field. Login owns open/closed; on success it returns to the
 * username/password form (username kept) and shows the server's next step.
 */
import { useState } from 'react';

import axiosClient from '../../api/axiosClient';
import { errorText } from '../../utils/errorText';

type Step = 'start' | 'code';

/** `username` is the one the person just typed to reach this screen. They
 *  are not asked again (owner, 2026-10-20). The server resolves it to the
 *  account's permanent ID (Cognito sub, then the employee or contributor
 *  record) and keeps the request by that ID; nothing downstream uses the name. */
/** The way in: under the code step, or under the setup-closed notice. */
export function ResetRequestLink({ onOpen }: { onOpen: () => void }) {
  return (
    /* Two lines (owner, 2026-10-21): the question muted, the action in the
       action colour so it reads as something to click. One button, one label. */
    <button type="button" onClick={onOpen}
            className="group w-full mt-3 flex flex-col items-center gap-0.5 text-sm rounded-lg py-1.5">
      <span className="text-muted-foreground">Can't use your authenticator?</span>
      <span className="font-semibold text-primary group-hover:underline">Request a reset</span>
    </button>
  );
}

type Props = {
  username: string;
  /** Back to wherever the person was. */
  onCancel: () => void;
  /** Who it went to and the server's next step (ADR-556 D4/D5). */
  onSent: (result: ResetSent) => void;
};

export type ResetSent = { sentTo: string; nextStep: string };

export default function ResetRequest({ username, onCancel, onSent }: Props) {
  const [step, setStep] = useState<Step>('start');
  const name = username;
  const [code, setCode] = useState('');
  // ADR-551 D2b: the server's ticket from step 1. Unreadable here; it is what
  // tells step 2 which account, so the name is never sent again.
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

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
      const { data } = await axiosClient.post<{ detail: string; sent_to: string; next_step?: string }>(
        '/auth/mfa-reset/confirm', { request_token: token, code: code.trim() });
      // next_step is new (ADR-556 D5); an older server only sends detail.
      onSent({ sentTo: data.sent_to, nextStep: data.next_step ?? data.detail });
    } catch (err) {
      setError(errorText(err, 'Could not send the request. Try again.'));
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4 text-sm" aria-live="polite">

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
            <button type="button" onClick={onCancel} className="btn-ghost text-sm px-3 py-2">Cancel</button>
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

    </div>
  );
}
