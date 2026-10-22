/**
 * Change your own email: a code to the current address and one to the new
 * (ADR-541 R2), for tenant and platform accounts alike (ADR-563 D2).
 *
 * One component so the two account pages can't drift. Each passes its own
 * endpoints; the server reads the current address from Cognito and, once both
 * codes check out, writes the new one there, ends every session and tells the
 * old address. The page is then signed out (onChanged).
 */
import { useState } from 'react';
import { Mail } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';

const field = 'w-full px-3 py-2.5 rounded-xl border border-border bg-input text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all';

type Props = {
  currentEmail: string | null;
  requestPath: string;      // e.g. /employees/me/email/request-change
  confirmPath: string;      // e.g. /employees/me/email/confirm-change
  onChanged: () => void;    // sign out and say why
  /** Shown instead of "Change" when there's no verified address to confirm from. */
  noEmailHint?: string;
};

export default function EmailChangeSection({ currentEmail, requestPath, confirmPath, onChanged, noEmailHint }: Props) {
  const [step, setStep] = useState<'idle' | 'entering' | 'verifying'>('idle');
  const [newEmail, setNewEmail] = useState('');
  const [currentCode, setCurrentCode] = useState('');
  const [newCode, setNewCode] = useState('');
  const [masked, setMasked] = useState<{ current: string; new: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const reset = () => { setStep('idle'); setMsg(''); setCurrentCode(''); setNewCode(''); };

  const request = async () => {
    if (!newEmail.includes('@')) { setMsg('Enter a valid email address.'); return; }
    setBusy(true); setMsg('');
    try {
      const { data } = await axiosClient.post<{ current_masked: string; new_masked: string }>(
        requestPath, { new_email: newEmail.trim().toLowerCase() });
      setMasked({ current: data.current_masked, new: data.new_masked });
      setStep('verifying');
    } catch (e) {
      setMsg(errorText(e, 'Could not send the codes.'));
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    if (currentCode.trim().length < 6 || newCode.trim().length < 6) { setMsg('Enter both 6-digit codes.'); return; }
    setBusy(true); setMsg('');
    try {
      await axiosClient.post(confirmPath, { current_code: currentCode.trim(), new_code: newCode.trim() });
      onChanged();
    } catch (e) {
      setMsg(errorText(e, 'Could not verify the codes.'));
      setBusy(false);
    }
  };

  return (
    <div>
      {step === 'idle' ? (
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Email</span>
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm text-foreground truncate">{currentEmail || '—'}</span>
            {currentEmail ? (
              <button onClick={() => { setNewEmail(''); setStep('entering'); setMsg(''); }}
                      className="text-sm text-primary hover:underline shrink-0">
                Change
              </button>
            ) : noEmailHint ? (
              <span className="text-xs text-muted-foreground">{noEmailHint}</span>
            ) : null}
          </div>
        </div>
      ) : step === 'entering' ? (
        <div className="space-y-2 max-w-sm">
          <label htmlFor="email-new" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <Mail className="w-3.5 h-3.5" aria-hidden="true" /> New email address
          </label>
          <input id="email-new" value={newEmail} onChange={e => setNewEmail(e.target.value)}
                 type="email" autoComplete="email" className={field} />
          <p className="text-xs text-muted-foreground">
            We'll email a code to your current address and one to the new address. After the
            change you'll be signed out everywhere.
          </p>
          <div className="flex gap-2">
            <button onClick={reset} className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
            <button onClick={request} disabled={busy} className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
              {busy ? 'Sending…' : 'Send codes'}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-2 max-w-sm">
          <label htmlFor="email-code-current" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Code sent to {masked?.current ?? 'your current email'}
          </label>
          <input id="email-code-current" value={currentCode} onChange={e => setCurrentCode(e.target.value)}
                 inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000"
                 className={`${field} font-mono tracking-widest`} />
          <label htmlFor="email-code-new" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Code sent to {masked?.new ?? 'the new email'}
          </label>
          <input id="email-code-new" value={newCode} onChange={e => setNewCode(e.target.value)}
                 inputMode="numeric" maxLength={6} placeholder="000000"
                 className={`${field} font-mono tracking-widest`} />
          <p className="text-xs text-muted-foreground">Codes expire in 10 minutes.</p>
          <div className="flex gap-2">
            <button onClick={reset} className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
            <button onClick={confirm} disabled={busy || currentCode.length < 6 || newCode.length < 6}
                    className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
              {busy ? 'Verifying…' : 'Confirm'}
            </button>
          </div>
        </div>
      )}
      {msg && <p className="text-xs text-muted-foreground mt-1.5">{msg}</p>}
    </div>
  );
}
