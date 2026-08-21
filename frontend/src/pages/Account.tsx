/**
 * My Account — three tabs, matching mobile's MyAccountScreen (ADR-270).
 *
 * The page previously stacked profile info, the Amazon scorecard summary, our
 * own performance stats and a password form on one scroll. Four unrelated
 * contexts with nothing separating them, where mobile had already split them.
 *
 * The tabs divide by WHO SAYS IT — the same rule mobile states:
 *   Settings   you      (identity, credentials, appearance)
 *   My Stats   us       (AsheFlow's DeliveryStop/RTS/rating record)
 *   Scorecard  Amazon   (their weekly assessment)
 *
 * That rule is why My Stats and Scorecard are not merged: they are independent
 * sources that can legitimately disagree, and appeals exist to contest exactly
 * that disagreement.
 */
import React, { useEffect, useState } from 'react';
import { updatePassword } from 'aws-amplify/auth';
import { fetchAuthSession } from 'aws-amplify/auth';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import { Lock, CheckCircle2, Mail, MessageSquare, ChevronDown, ChevronUp } from 'lucide-react';
import Avatar from '../components/ui/Avatar';
import StatsDrill from '../components/stats/StatsDrill';
import MyScorecardPanel from '../components/MyScorecardPanel';

type Tab = 'settings' | 'stats' | 'scorecard';

const TABS: { key: Tab; label: string }[] = [
  { key: 'settings',  label: 'Settings' },
  { key: 'stats',     label: 'My Stats' },
  { key: 'scorecard', label: 'Scorecard' },
];

type Step = 'idle' | 'entering' | 'verifying';

export default function Account() {
  const { user, groups } = useAuth();
  const [tab, setTab] = useState<Tab>('settings');

  // ── password ──
  const [current,  setCurrent]  = useState('');
  const [next,     setNext]     = useState('');
  const [confirm,  setConfirm]  = useState('');
  const [error,    setError]    = useState('');
  const [success,  setSuccess]  = useState(false);
  const [loading,  setLoading]  = useState(false);

  // ── email change (ADR-270: web never had this; the backend flow already
  //    existed and mobile has used it since it shipped) ──
  const [eStep, setEStep] = useState<Step>('idle');
  const [newEmail, setNewEmail] = useState('');
  const [eCode, setECode] = useState('');
  const [eBusy, setEBusy] = useState(false);
  const [eMsg, setEMsg] = useState('');
  const [currentEmail, setCurrentEmail] = useState('');

  // ── discord link ──
  const [dStep, setDStep] = useState<Step>('idle');
  const [dId, setDId] = useState('');
  const [dCode, setDCode] = useState('');
  const [dBusy, setDBusy] = useState(false);
  const [dMsg, setDMsg] = useState('');
  const [dHelp, setDHelp] = useState(false);
  const [currentDiscord, setCurrentDiscord] = useState<string | null>(null);

  // AuthUser carries only Cognito claims (username/displayName), not our
  // employee row — so email and discord_id come from the API. Reading them
  // here also means the rows stay correct after a change without a re-login.
  useEffect(() => {
    axiosClient.get('/employees/me')
      .then(({ data }) => {
        setCurrentEmail(data?.email ?? '');
        setCurrentDiscord(data?.discord_id ?? null);
      })
      .catch(() => {/* silent: the rows fall back to placeholders */});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess(false);
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (next.length < 8)  { setError('Password must be at least 8 characters.'); return; }
    setLoading(true);
    try {
      await updatePassword({ oldPassword: current, newPassword: next });
      setSuccess(true);
      setCurrent(''); setNext(''); setConfirm('');
    } catch (err: any) {
      const msg = err?.message ?? '';
      if (msg.includes('NotAuthorizedException') || msg.includes('Incorrect')) {
        setError('Current password is incorrect.');
      } else if (msg.includes('LimitExceededException')) {
        setError('Too many attempts. Please wait a few minutes and try again.');
      } else {
        setError(msg || 'Failed to update password. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  /** Cognito needs the caller's own access token to change their email — the
   *  backend cannot mint one, which is why both steps take it in the body. */
  const accessToken = async () => {
    const s = await fetchAuthSession();
    return s.tokens?.accessToken?.toString() ?? '';
  };

  const requestEmail = async () => {
    if (!newEmail.includes('@')) { setEMsg('Enter a valid email address.'); return; }
    setEBusy(true); setEMsg('');
    try {
      await axiosClient.post('/employees/me/email/request-change', {
        access_token: await accessToken(),
        new_email: newEmail.trim().toLowerCase(),
      });
      setEStep('verifying');
    } catch (e) {
      setEMsg(errorText(e, 'Could not send the code.'));
    } finally { setEBusy(false); }
  };

  const confirmEmail = async () => {
    if (eCode.trim().length < 6) { setEMsg('Enter the 6-digit code.'); return; }
    setEBusy(true); setEMsg('');
    try {
      await axiosClient.post('/employees/me/email/confirm-change', {
        access_token: await accessToken(),
        code: eCode.trim(),
        new_email: newEmail.trim().toLowerCase(),
      });
      setCurrentEmail(newEmail.trim().toLowerCase());
      setEStep('idle'); setNewEmail(''); setECode('');
      setEMsg('Email updated. Sign in again to refresh your session.');
    } catch (e) {
      setEMsg(errorText(e, 'Could not verify the code.'));
    } finally { setEBusy(false); }
  };

  const requestDiscord = async () => {
    // Mirror the server's ADR-083 rule locally so a typo is caught before it
    // DMs a stranger, not after.
    if (!/^[0-9]{17,20}$/.test(dId.trim())) {
      setDMsg('A Discord ID is 17–20 digits. See "How do I find this?" below.');
      return;
    }
    setDBusy(true); setDMsg('');
    try {
      await axiosClient.post('/employees/me/discord/request-link', {
        discord_id: dId.trim(),
      });
      setDStep('verifying');
    } catch (e) {
      setDMsg(errorText(e, 'Could not send the code.'));
    } finally { setDBusy(false); }
  };

  const confirmDiscord = async () => {
    if (dCode.trim().length !== 6) { setDMsg('Enter the 6-digit code.'); return; }
    setDBusy(true); setDMsg('');
    try {
      const res = await axiosClient.post('/employees/me/discord/confirm-link', {
        discord_id: dId.trim(),
        code: dCode.trim(),
      });
      setCurrentDiscord(res.data?.discord_id ?? dId.trim());
      setDStep('idle'); setDId(''); setDCode('');
      setDMsg('Discord account linked.');
    } catch (e) {
      setDMsg(errorText(e, 'Could not link that account.'));
    } finally { setDBusy(false); }
  };

  const field = 'w-full px-3 py-2.5 rounded-xl border border-border bg-input text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all';

  return (
    <div className="space-y-6 animate-slide-up">
      <h1 className="page-title">My Account</h1>

      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm w-fit">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
              tab === t.key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'settings' && (
        <>
          {/* Identity */}
          <div className="card">
            <div className="flex items-center gap-4 mb-6">
              <Avatar size={56} />
              <div>
                <h2 className="text-lg font-bold text-foreground">{user?.displayName || user?.username}</h2>
                <p className="text-sm text-muted-foreground capitalize">{groups[0]?.replace('_', ' ') ?? ''}</p>
              </div>
            </div>

            <div className="flex items-center justify-between py-2.5 border-t border-border">
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Username</span>
              <span className="text-sm font-medium text-foreground font-mono">{user?.username || '—'}</span>
            </div>

            {/* Email — two-step verified change, same backend flow mobile uses */}
            <div className="py-2.5 border-t border-border">
              {eStep === 'idle' ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Email</span>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm text-foreground truncate">{currentEmail || '—'}</span>
                    <button
                      onClick={() => { setNewEmail(currentEmail); setEStep('entering'); setEMsg(''); }}
                      className="text-sm text-primary hover:underline shrink-0"
                    >
                      Edit
                    </button>
                  </div>
                </div>
              ) : eStep === 'entering' ? (
                <div className="space-y-2 max-w-sm">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                    <Mail className="w-3.5 h-3.5" /> New email address
                  </label>
                  <input value={newEmail} onChange={e => setNewEmail(e.target.value)}
                         type="email" autoComplete="email" className={field} />
                  <p className="text-xs text-muted-foreground">
                    A verification code will be sent to the new address.
                  </p>
                  <div className="flex gap-2">
                    <button onClick={() => { setEStep('idle'); setEMsg(''); }}
                            className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
                    <button onClick={requestEmail} disabled={eBusy}
                            className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
                      {eBusy ? 'Sending…' : 'Send Code'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 max-w-sm">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Verification code
                  </label>
                  <p className="text-xs text-muted-foreground">Sent to {newEmail}</p>
                  <input value={eCode} onChange={e => setECode(e.target.value)}
                         inputMode="numeric" maxLength={6} placeholder="000000"
                         className={`${field} font-mono tracking-widest`} />
                  <div className="flex gap-2">
                    <button onClick={() => { setEStep('idle'); setEMsg(''); }}
                            className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
                    <button onClick={confirmEmail} disabled={eBusy || eCode.length < 6}
                            className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
                      {eBusy ? 'Verifying…' : 'Confirm'}
                    </button>
                  </div>
                </div>
              )}
              {eMsg && <p className="text-xs text-muted-foreground mt-1.5">{eMsg}</p>}
            </div>

            {/* Discord — verified link (ADR-270). Not a free edit: discord_id is
                the bot's DM address and the third step of the auth lookup chain,
                so a code is DM'd to the claimed account to prove ownership. */}
            <div className="py-2.5 border-t border-border">
              {dStep === 'idle' ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Discord</span>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`text-sm truncate font-mono ${currentDiscord ? 'text-foreground' : 'text-muted-foreground'}`}>
                      {currentDiscord ?? 'Not linked'}
                    </span>
                    <button
                      onClick={() => { setDId(currentDiscord ?? ''); setDStep('entering'); setDMsg(''); }}
                      className="text-sm text-primary hover:underline shrink-0"
                    >
                      {currentDiscord ? 'Change' : 'Link'}
                    </button>
                  </div>
                </div>
              ) : dStep === 'entering' ? (
                <div className="space-y-2 max-w-sm">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                    <MessageSquare className="w-3.5 h-3.5" /> Discord ID
                  </label>
                  <input value={dId} onChange={e => setDId(e.target.value)}
                         inputMode="numeric" placeholder="219476523456789012"
                         className={`${field} font-mono`} />
                  <p className="text-xs text-muted-foreground">
                    We'll DM a 6-digit code to that Discord account to confirm it's yours.
                  </p>

                  {/* Steps inline rather than a link out: nobody knows their own
                      snowflake, and Developer Mode is off by default. */}
                  <button onClick={() => setDHelp(h => !h)}
                          className="flex items-center gap-1 text-xs text-primary hover:underline">
                    {dHelp ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    How do I find this?
                  </button>
                  {dHelp && (
                    <ol className="text-xs text-muted-foreground space-y-1 pl-4 list-decimal">
                      <li>Open Discord → Settings (gear icon)</li>
                      <li>Advanced → turn on <span className="text-foreground">Developer Mode</span></li>
                      <li>Right-click your own name or avatar</li>
                      <li>Choose <span className="text-foreground">Copy User ID</span></li>
                      <li className="list-none pt-1">It's a 17–20 digit number — not your username.</li>
                    </ol>
                  )}

                  <div className="flex gap-2">
                    <button onClick={() => { setDStep('idle'); setDMsg(''); setDHelp(false); }}
                            className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
                    <button onClick={requestDiscord} disabled={dBusy}
                            className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
                      {dBusy ? 'Sending…' : 'Send Code'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 max-w-sm">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Verification code
                  </label>
                  <p className="text-xs text-muted-foreground">
                    Check your Discord DMs for a code from the AsheFlow bot.
                  </p>
                  <input value={dCode} onChange={e => setDCode(e.target.value)}
                         inputMode="numeric" maxLength={6} placeholder="000000"
                         className={`${field} font-mono tracking-widest`} />
                  <div className="flex gap-2">
                    <button onClick={() => { setDStep('idle'); setDMsg(''); }}
                            className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
                    <button onClick={confirmDiscord} disabled={dBusy || dCode.length < 6}
                            className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
                      {dBusy ? 'Linking…' : 'Confirm'}
                    </button>
                  </div>
                </div>
              )}
              {dMsg && <p className="text-xs text-muted-foreground mt-1.5">{dMsg}</p>}
            </div>
          </div>

          {/* Change password */}
          <div className="card">
            <div className="flex items-center gap-3 mb-5">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
                <Lock className="w-4 h-4 text-primary" />
              </div>
              <h2 className="section-title">Change Password</h2>
            </div>

            {success ? (
              <div className="flex items-center gap-2 text-success text-sm font-medium py-2">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                Password updated successfully.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4 max-w-sm">
                {[
                  { label: 'Current password', value: current, setter: setCurrent, auto: 'current-password' },
                  { label: 'New password',     value: next,    setter: setNext,    auto: 'new-password' },
                  { label: 'Confirm new password', value: confirm, setter: setConfirm, auto: 'new-password' },
                ].map(({ label, value, setter, auto }) => (
                  <div key={label} className="space-y-1">
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{label}</label>
                    <input
                      type="password"
                      value={value}
                      onChange={e => { setter(e.target.value); setError(''); setSuccess(false); }}
                      required
                      autoComplete={auto}
                      className={field}
                    />
                  </div>
                ))}
                {error && <p className="text-xs text-danger">{error}</p>}
                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary text-sm px-4 py-2 flex items-center gap-2 disabled:opacity-50"
                >
                  {loading && <span className="w-3.5 h-3.5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />}
                  {loading ? 'Updating…' : 'Update Password'}
                </button>
              </form>
            )}
          </div>
        </>
      )}

      {tab === 'stats' && (
        <>
          <p className="text-xs text-muted-foreground">
            AsheFlow's record of your deliveries. Amazon's own weekly assessment
            is under Scorecard — the two are measured separately and can differ.
          </p>
          <StatsDrill />
        </>
      )}

      {tab === 'scorecard' && <MyScorecardPanel />}
    </div>
  );
}
