/**
 * Confirming an email change from the NEW inbox (ADR-563 D3; ADR-451 D4).
 *
 * Two links land here:
 *   /email-change?token=…        an admin-started change for any account
 *   /owner-email-change?token=…  a super admin changing a company owner's email
 *                                (ADR-451 D4 sent this link with no page behind it)
 *
 * It asks for a click rather than confirming on load: email security scanners
 * open links, and some run the page's scripts. Nothing changes until the
 * person presses the button.
 */
import { useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { CheckCircle2, Mail } from 'lucide-react';
import SignInNotice from '../components/auth/SignInNotice';
import logoFull from '../assets/logo-full.svg';
import logoFullLight from '../assets/logo-full-light.svg';

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';

export default function EmailChangeConfirm() {
  const [params] = useSearchParams();
  const { pathname } = useLocation();
  const token = params.get('token') ?? '';
  const isOwner = pathname.startsWith('/owner-email-change');
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const confirm = async () => {
    setState('busy');
    try {
      const res = await fetch(`${API_BASE}${isOwner ? '/companies/owner/email-change/confirm' : '/auth/email-change/confirm'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setState('error');
        setMessage(typeof data?.detail === 'string' ? data.detail : "That link didn't work. Ask for a new one.");
        return;
      }
      setState('done');
      setMessage(typeof data?.detail === 'string' ? data.detail : 'Your email is changed.');
    } catch {
      setState('error');
      setMessage("Couldn't reach AsheFlow. Check your connection and try again.");
    }
  };

  return (
    <div className="min-h-dvh bg-background flex flex-col items-center justify-center px-4 py-10">
      <div className="layout-form w-full">
        <div className="flex items-center justify-center mb-10">
          <img src={logoFull} alt="AsheFlow" className="h-10 w-auto dark:hidden" />
          <img src={logoFullLight} alt="" aria-hidden className="h-10 w-auto hidden dark:block" />
        </div>
        <div className="card-elevated p-6 sm:p-8">
          <h1 className="text-xl font-semibold text-center text-foreground mb-1">Confirm your new email</h1>
          <p className="text-subtle text-center mb-8">
            It becomes the address your sign-in codes and security notices go to.
          </p>

          {!token ? (
            <SignInNotice tone="warning" title="This link is incomplete">
              <p>Open the link from the email again, or ask for a new one.</p>
            </SignInNotice>
          ) : state === 'done' ? (
            <>
              <SignInNotice tone="success" title="Email changed">
                <p>{message}</p>
                <p>Every device was signed out, and your old address was told about the change.</p>
              </SignInNotice>
              <Link to="/login" className="btn-primary w-full inline-flex justify-center">Go to sign in</Link>
            </>
          ) : (
            <>
              {state === 'error' && (
                <SignInNotice tone="warning" title="Not confirmed">
                  <p>{message}</p>
                </SignInNotice>
              )}
              <ul className="text-sm text-muted-foreground space-y-2 mb-6">
                <li className="flex gap-2"><Mail className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />Every device signed in to the account will be signed out.</li>
                <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />Your old address will be told about the change.</li>
              </ul>
              <button type="button" onClick={confirm} disabled={state === 'busy'}
                      className="btn-primary w-full disabled:opacity-60">
                {state === 'busy' ? 'Confirming…' : 'Confirm this email'}
              </button>
              <p className="text-xs text-muted-foreground text-center mt-4">
                Didn't expect this? Close this page and nothing will change.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
