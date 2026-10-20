/**
 * My Account for platform accounts — super admin, platform support, surveyor (ADR-549 D5).
 *
 * The tenant Account page is built on an Employee row these accounts do not
 * have: every call it makes answered 403, so "My Account" showed a page that
 * could change nothing, and for support and surveyors the route refused them
 * outright. This page talks to /platform/me, keyed on the Cognito identity.
 *
 * Three things only: who you are (read-only — a super admin sets platform
 * names and emails, ADR-394), your password (by emailed code, then signed out
 * everywhere, ADR-541's rule), and your second factor (SecurityPanel, which
 * talks to Amplify directly and so already works for any Cognito user).
 */
import React, { useEffect, useState } from 'react';
import { signOut } from 'aws-amplify/auth';
import { Lock, CheckCircle2, UserCircle2 } from 'lucide-react';

import axiosClient from '../../api/axiosClient';
import type { PlatformMe } from '../../api/types';
import SecurityPanel from '../../components/SecurityPanel';
import SectionHeader from '../../components/ui/SectionHeader';
import { errorText } from '../../utils/errorText';

const field = 'w-full px-3 py-2.5 rounded-xl border border-border bg-input text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all';

export default function PlatformAccount() {
  const [me, setMe] = useState<PlatformMe | null>(null);
  const [meError, setMeError] = useState('');

  const [step, setStep] = useState<'idle' | 'code'>('idle');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    axiosClient.get<PlatformMe>('/platform/me')
      .then(r => setMe(r.data))
      .catch(err => setMeError(errorText(err, 'Could not load your account.')));
  }, []);

  const requestCode = async () => {
    setError(''); setLoading(true);
    try {
      const { data } = await axiosClient.post<{ sent_to: string | null }>('/platform/me/password/request-code');
      setSentTo(data.sent_to);
      setStep('code');
    } catch (err) {
      setError(errorText(err, 'Could not send the code. Try again.'));
    } finally { setLoading(false); }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (code.trim().length < 6) { setError('Enter the 6-digit code from the email.'); return; }
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (next.length < 8) { setError('Password must be at least 8 characters.'); return; }
    setLoading(true);
    try {
      await axiosClient.post('/platform/me/password/confirm', { code: code.trim(), new_password: next });
      setDone(true);
      // Every session ended, this one included (ADR-541 D2 / ADR-549 D3).
      signOut().catch(() => {}).finally(() => window.location.assign('/login?ended=password'));
    } catch (err) {
      setError(errorText(err, 'Could not change your password. Try again.'));
      setLoading(false);
    }
  };

  const noEmail = me !== null && (!me.email || !me.email_verified);

  return (
    <div className="layout-form space-y-6">
      <SectionHeader eyebrow="Platform" title="My account"
                     description="Your sign-in details. Changing your password signs you out everywhere." />

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Who you are */}
        <div className="card">
          <div className="flex items-center gap-3 mb-5">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
              <UserCircle2 className="w-4 h-4 text-primary" />
            </div>
            <h2 className="section-title">Profile</h2>
          </div>
          {meError ? (
            <p className="text-sm text-danger">{meError}</p>
          ) : !me ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-3 text-sm">
              <dt className="text-muted-foreground">Name</dt><dd className="text-foreground min-w-0 break-words">{me.name || '—'}</dd>
              <dt className="text-muted-foreground">Username</dt><dd className="text-foreground font-mono min-w-0 break-all">{me.username}</dd>
              <dt className="text-muted-foreground">Email</dt>
              <dd className="text-foreground min-w-0 break-all">
                {me.email || '—'}
                {me.email && !me.email_verified && <span className="ml-2 text-xs text-warning">not verified</span>}
              </dd>
              <dt className="text-muted-foreground">Role</dt><dd className="text-foreground">{me.role_label}</dd>
            </dl>
          )}
          <p className="text-xs text-muted-foreground mt-5">
            A super admin sets platform names and email addresses.
          </p>
        </div>

        {/* Password */}
        <div className="card">
          <div className="flex items-center gap-3 mb-5">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
              <Lock className="w-4 h-4 text-primary" />
            </div>
            <h2 className="section-title">Change password</h2>
          </div>

          {done ? (
            <div className="flex items-center gap-2 text-success text-sm font-medium py-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" /> Password changed. Signing you out…
            </div>
          ) : noEmail ? (
            <p className="text-sm text-muted-foreground max-w-prose">
              Changing your password needs a verified email address to send a code to.
              Ask a super admin to set your email.
            </p>
          ) : step === 'idle' ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                We'll email a code to your address. After the change you'll be
                signed out everywhere, including here.
              </p>
              {error && <p className="text-xs text-danger">{error}</p>}
              <button type="button" onClick={requestCode} disabled={loading || !me}
                      className="btn-primary text-sm px-4 py-2 disabled:opacity-50">
                {loading ? 'Sending…' : 'Email me a code'}
              </button>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <p className="text-xs text-muted-foreground">
                Code sent{sentTo ? ` to ${sentTo}` : ''}. It works once.
              </p>
              <div className="space-y-1">
                <label htmlFor="pa-code" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Code from the email</label>
                <input id="pa-code" value={code} onChange={e => { setCode(e.target.value); setError(''); }}
                       inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000" required
                       className={`${field} font-mono tracking-widest`} />
              </div>
              {[
                { id: 'pa-new', label: 'New password', value: next, setter: setNext },
                { id: 'pa-confirm', label: 'Confirm new password', value: confirm, setter: setConfirm },
              ].map(({ id, label, value, setter }) => (
                <div key={id} className="space-y-1">
                  <label htmlFor={id} className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{label}</label>
                  <input id={id} type="password" value={value} required autoComplete="new-password"
                         onChange={e => { setter(e.target.value); setError(''); }} className={field} />
                </div>
              ))}
              <p className="text-xs text-muted-foreground">
                At least 8 characters, with upper and lower case letters, a number and a symbol.
              </p>
              {error && <p className="text-xs text-danger">{error}</p>}
              <div className="flex gap-2">
                <button type="button" onClick={() => { setStep('idle'); setCode(''); setError(''); }}
                        className="btn-ghost text-sm px-3 py-2">Cancel</button>
                <button type="submit" disabled={loading}
                        className="btn-primary text-sm px-4 py-2 disabled:opacity-50">
                  {loading ? 'Changing…' : 'Change password'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>

      {/* Second factor: required for every platform account (ADR-549 D1). */}
      <div className="card">
        <SecurityPanel />
      </div>
    </div>
  );
}
