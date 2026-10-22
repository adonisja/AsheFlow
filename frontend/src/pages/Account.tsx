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
import { signOut } from 'aws-amplify/auth';
import { useAuth } from '../contexts/AuthContext';
import EmailChangeSection from '../components/EmailChangeSection';
import SignInNameSection from '../components/SignInNameSection';
import ChosenNameSection from '../components/ChosenNameSection';
import type { SignInNameStatus } from '../api/types';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import { Lock, CheckCircle2, Mail, MessageSquare, ChevronDown, ChevronUp } from 'lucide-react';
import Avatar from '../components/ui/Avatar';
import StatsDrill from '../components/stats/StatsDrill';
import MyScorecardPanel from '../components/MyScorecardPanel';
import SecurityPanel from '../components/SecurityPanel';

type Tab = 'settings' | 'stats' | 'scorecard';

const TABS: { key: Tab; label: string }[] = [
  { key: 'settings',  label: 'Settings' },
  { key: 'stats',     label: 'My Stats' },
  { key: 'scorecard', label: 'Scorecard' },
];

/** ADR-398 D3: the field tabs are shown on DATA **or** FIELD ROLE, and each
 *  half of that disjunction covers a case the other gets wrong.
 *
 *  Data alone hides the tab from a walker on day one — the page where their
 *  first numbers will appear, missing until numbers exist. Role alone hides it
 *  from a manager promoted out of the field, whose history does not stop being
 *  theirs on promotion. Only the OR handles both, and leaves a career manager
 *  who never walked a route with neither tab. */
const FIELD_ROLES = ['driver', 'walker', 'trainer', 'trainee', 'captain'];

type Step = 'idle' | 'entering' | 'verifying';

export default function Account() {
  const { user, groups, setShownName } = useAuth();
  const [tab, setTab] = useState<Tab>('settings');

  // ADR-398 D3 — see FIELD_ROLES above for why this is a disjunction.
  // `hasFieldData` starts null (unknown) so the tabs do not flicker in and out
  // while the probe is in flight; a field role alone already settles it.
  const [hasFieldData, setHasFieldData] = useState<boolean | null>(null);
  const isFieldRole = groups.some(g => FIELD_ROLES.includes(g));
  const showFieldTabs = isFieldRole || hasFieldData === true;
  const visibleTabs = TABS.filter(
    t => t.key === 'settings' || showFieldTabs,
  );

  // Probe only when the role does not already settle it — a walker never needs
  // this request. `years` is the signal rather than `lifetime.delivered`,
  // because delivered is null in workforce mode until a route is Flex-scanned
  // (ADR-305): a worked-but-unscanned route is real work and must count here.
  useEffect(() => {
    if (isFieldRole) return;
    let alive = true;
    axiosClient
      .get<{ years?: unknown[] }>('/assignment-history/me/stats')
      .then(r => { if (alive) setHasFieldData((r.data.years?.length ?? 0) > 0); })
      .catch(() => { if (alive) setHasFieldData(false); });
    return () => { alive = false; };
  }, [isFieldRole]);

  // A tab that disappears under the user must not leave the page blank.
  useEffect(() => {
    if (!showFieldTabs && tab !== 'settings') setTab('settings');
  }, [showFieldTabs, tab]);

  // ── password (ADR-541: confirmed by a code to the verified email, then every
  //    session ends -- including this one, so the person signs in with it) ──
  const [pStep,    setPStep]    = useState<'idle' | 'code'>('idle');
  const [pSentTo,  setPSentTo]  = useState('');
  const [pCode,    setPCode]    = useState('');
  const [next,     setNext]     = useState('');
  const [confirm,  setConfirm]  = useState('');
  const [error,    setError]    = useState('');
  const [success,  setSuccess]  = useState(false);
  const [loading,  setLoading]  = useState(false);

  // ── email change (ADR-270: web never had this; the backend flow already
  //    existed and mobile has used it since it shipped) ──
  const [currentEmail, setCurrentEmail] = useState('');

  // ── discord link ──
  const [dStep, setDStep] = useState<Step>('idle');
  const [dId, setDId] = useState('');
  const [dCode, setDCode] = useState('');
  const [dBusy, setDBusy] = useState(false);
  const [dMsg, setDMsg] = useState('');
  const [dHelp, setDHelp] = useState(false);
  const [currentDiscord, setCurrentDiscord] = useState<string | null>(null);
  // ADR-567: the person's own names (only they and management/admin see the legal one).
  const [names, setNames] = useState<{ legal: string; chosen: string | null } | null>(null);

  // AuthUser carries only Cognito claims (username/displayName), not our
  // employee row — so email and discord_id come from the API. Reading them
  // here also means the rows stay correct after a change without a re-login.
  useEffect(() => {
    axiosClient.get('/employees/me')
      .then(({ data }) => {
        setCurrentEmail(data?.email ?? '');
        setCurrentDiscord(data?.discord_id ?? null);
        if (data?.legal_name) setNames({ legal: data.legal_name, chosen: data.chosen_name ?? null });
      })
      .catch(() => {/* silent: the rows fall back to placeholders */});
  }, []);

  // ADR-566 D4. Hidden until the environment's pool accepts sign-in names.
  const [signInName, setSignInName] = useState<SignInNameStatus | null>(null);
  useEffect(() => {
    axiosClient.get<SignInNameStatus>('/employees/me/sign-in-name')
      .then(({ data }) => setSignInName(data))
      .catch(() => {/* silent: the row just stays hidden */});
  }, []);

  /** After a credential change the server has ended every session, this one
   *  included (ADR-541 D2). Sign out locally and say why on the sign-in screen. */
  const leaveAfterChange = (which: 'password' | 'email') => {
    signOut().catch(() => {}).finally(() => {
      window.location.assign(`/login?ended=${which}`);
    });
  };

  const requestPasswordCode = async () => {
    setError(''); setLoading(true);
    try {
      const { data } = await axiosClient.post<{ sent_to: string }>('/employees/me/password/request-code');
      setPSentTo(data.sent_to);
      setPStep('code');
    } catch (err) {
      setError(errorText(err, 'Could not send the code. Try again.'));
    } finally { setLoading(false); }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (pCode.trim().length < 6) { setError('Enter the 6-digit code from the email.'); return; }
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (next.length < 8)  { setError('Password must be at least 8 characters.'); return; }
    setLoading(true);
    try {
      await axiosClient.post('/employees/me/password/confirm', { code: pCode.trim(), new_password: next });
      setSuccess(true);
      leaveAfterChange('password');
    } catch (err) {
      setError(errorText(err, 'Could not change your password. Try again.'));
      setLoading(false);
    }
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
        {visibleTabs.map(t => (
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

            {/* ADR-567: the name everyone else sees. */}
            {names && (
              <div className="py-2.5 border-t border-border">
                <ChosenNameSection
                  legalName={names.legal}
                  chosen={names.chosen}
                  onChanged={me => {
                    setNames({ legal: me.legal_name ?? names.legal, chosen: me.chosen_name ?? null });
                    setShownName(me.name);
                  }}
                />
                {/* D8: the username is built from the legal name. */}
                {names.chosen && signInName?.available && !signInName.sign_in_name && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Your username is based on your legal name. Add a sign-in name below to sign in without it.
                  </p>
                )}
              </div>
            )}

            {signInName?.available && (
              <div className="py-2.5 border-t border-border">
                <SignInNameSection path="/employees/me/sign-in-name" available
                                   current={signInName.sign_in_name} username={signInName.username} />
              </div>
            )}

            {/* Email — two-step verified change (ADR-541 R2), shared with the
                platform account page (ADR-563 D2). */}
            <div className="py-2.5 border-t border-border">
              <EmailChangeSection
                currentEmail={currentEmail || null}
                requestPath="/employees/me/email/request-change"
                confirmPath="/employees/me/email/confirm-change"
                onChanged={() => leaveAfterChange('email')}
              />
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
                      <li className="list-none pt-1">It's a 17–20 digit number, not your username.</li>
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
                Password changed. Signing you out…
              </div>
            ) : !currentEmail ? (
              <p className="text-sm text-muted-foreground max-w-prose">
                Changing your password needs an email address to send a code to.
                Ask your manager or an admin to add your email from the People page.
              </p>
            ) : pStep === 'idle' ? (
              <div className="space-y-3 max-w-sm">
                <p className="text-sm text-muted-foreground">
                  We'll email a code to your address on file. After the change
                  you'll be signed out everywhere, including here.
                </p>
                {error && <p className="text-xs text-danger">{error}</p>}
                <button type="button" onClick={requestPasswordCode} disabled={loading}
                        className="btn-primary text-sm px-4 py-2 disabled:opacity-50">
                  {loading ? 'Sending…' : 'Email me a code'}
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4 max-w-sm">
                <p className="text-xs text-muted-foreground">Code sent to {pSentTo}. It works once.</p>
                <div className="space-y-1">
                  <label htmlFor="pw-code" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Code from the email</label>
                  <input id="pw-code" value={pCode} onChange={e => { setPCode(e.target.value); setError(''); }}
                         inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000" required
                         className={`${field} font-mono tracking-widest`} />
                </div>
                {[
                  { id: 'pw-new', label: 'New password', value: next, setter: setNext },
                  { id: 'pw-confirm', label: 'Confirm new password', value: confirm, setter: setConfirm },
                ].map(({ id, label, value, setter }) => (
                  <div key={id} className="space-y-1">
                    <label htmlFor={id} className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{label}</label>
                    <input
                      id={id}
                      type="password"
                      value={value}
                      onChange={e => { setter(e.target.value); setError(''); }}
                      required
                      autoComplete="new-password"
                      className={field}
                    />
                  </div>
                ))}
                <p className="text-xs text-muted-foreground">
                  At least 8 characters, with upper and lower case letters, a number and a symbol.
                </p>
                {error && <p className="text-xs text-danger">{error}</p>}
                <div className="flex gap-2">
                  <button type="button" onClick={() => { setPStep('idle'); setPCode(''); setError(''); }}
                          className="btn-ghost text-sm px-3 py-2">Cancel</button>
                  <button
                    type="submit"
                    disabled={loading}
                    className="btn-primary text-sm px-4 py-2 flex items-center gap-2 disabled:opacity-50"
                  >
                    {loading && <span className="w-3.5 h-3.5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />}
                    {loading ? 'Changing…' : 'Change password'}
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* ADR-362 — enrolment must exist before the PreAuthentication trigger
              refuses anyone: its message names this page. */}
          <SecurityPanel />
        </>
      )}

      {tab === 'stats' && (
        <>
          <p className="text-xs text-muted-foreground">
            AsheFlow's record of your deliveries. Amazon's own weekly assessment
            is under Scorecard. The two are measured separately and can differ.
          </p>
          <StatsDrill />
        </>
      )}

      {tab === 'scorecard' && <MyScorecardPanel />}
    </div>
  );
}
