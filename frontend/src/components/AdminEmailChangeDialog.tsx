/**
 * An admin starts an email change for someone who lost their inbox (ADR-563 D3).
 *
 * Used for tenant employees (by their company's admins) and for platform
 * accounts (by a super admin). Nothing changes when this is submitted: a link
 * goes to the NEW address, and only clicking it there changes the account. The
 * dialog says exactly that, so nobody expects the change to be instant.
 *
 * Same accessibility contract as ConfirmDialog: labelled, focus moves in and
 * back, Tab is trapped, Escape cancels.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Mail } from 'lucide-react';
import { errorText } from '../utils/errorText';

type Result = { pending_email_masked: string; expires_at: string };

type Props = {
  open: boolean;
  personName: string;
  submit: (newEmail: string) => Promise<Result>;
  onClose: () => void;
};

export default function AdminEmailChangeDialog({ open, personName, submit, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const returnFocusRef = useRef<Element | null>(null);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    if (!open) return;
    setEmail(''); setError(''); setResult(null); setBusy(false);
    returnFocusRef.current = document.activeElement;
    setTimeout(() => inputRef.current?.focus(), 0);
    return () => { (returnFocusRef.current as HTMLElement | null)?.focus?.(); };
  }, [open]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
    if (e.key !== 'Tab') return;
    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>('button, input, [href]');
    if (!focusable?.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }, [onClose]);

  if (!open) return null;

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.includes('@')) { setError('Enter a valid email address.'); return; }
    setBusy(true); setError('');
    try {
      setResult(await submit(email.trim().toLowerCase()));
    } catch (err) {
      setError(errorText(err, 'Could not start the change.'));
    } finally { setBusy(false); }
  };

  const expires = result ? new Date(result.expires_at).toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose} onKeyDown={onKeyDown}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" aria-hidden="true" />
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="aec-title"
           className="relative z-10 w-full max-w-md rounded-2xl bg-surface border border-border shadow-xl p-6 space-y-4 animate-slide-up"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-start gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-accent shrink-0 mt-0.5">
            <Mail className="w-5 h-5 text-primary" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p id="aec-title" className="font-semibold text-foreground">Change {personName}'s email</p>
            <p className="text-sm text-muted-foreground mt-1">
              For when they can't get into their current inbox. We'll send a link to the new
              address; nothing changes until they click it there. Then they're signed out
              everywhere and the old address is told.
            </p>
          </div>
        </div>

        {result ? (
          <>
            <p className="text-sm text-foreground" role="status">
              Link sent to <span className="font-medium">{result.pending_email_masked}</span>. It works once,
              until {expires}.
            </p>
            <div className="flex justify-end">
              <button type="button" onClick={onClose} className="btn-primary text-sm px-4 py-2">Done</button>
            </div>
          </>
        ) : (
          <form onSubmit={send} className="space-y-3">
            <label htmlFor="aec-email" className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              New email address
            </label>
            <input id="aec-email" ref={inputRef} type="email" autoComplete="off" value={email}
                   onChange={e => { setEmail(e.target.value); setError(''); }} className="input-field" />
            {error && <p className="text-xs text-danger">{error}</p>}
            <div className="flex gap-3 justify-end pt-1">
              <button type="button" onClick={onClose} className="btn-ghost text-sm px-4 py-2">Cancel</button>
              <button type="submit" disabled={busy} className="btn-primary text-sm px-4 py-2 disabled:opacity-60">
                {busy ? 'Sending…' : 'Send link'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
