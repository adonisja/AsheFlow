/**
 * Survey activity — who is surveying, what they hold, and what is stuck (ADR-545).
 *
 * For platform support and the owner. Support SEES survey work and UNSTICKS a
 * surveyor's account or claim; it never writes a survey record (ADR-504). So
 * there are counts and status here, never observation contents, and every
 * action is on an account or a claim.
 */
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import AccountId from '../../components/ui/AccountId';
import { Check, Copy, Loader2, RefreshCw } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import AdminEmailChangeDialog from '../../components/AdminEmailChangeDialog';
import SectionHeader from '../../components/ui/SectionHeader';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { errorText } from '../../utils/errorText';
import { formatDate, formatDateTime, getLocalYMD } from '../../utils/date';
import type {
  SurveyAccountStatus, SurveyActivity, SurveyActivityClaim, SurveyContributorHealth,
  SurveyContributorInvited, SurveyStaffReleaseResult, SurveyMfaResetResult,
  SurveyWithdrawalPreview, SurveyWithdrawalResult,
} from '../../api/types';

const STATUS: Record<SurveyAccountStatus, { label: string; tone: string }> = {
  active:          { label: 'Signed in',        tone: 'bg-success/10 text-success' },
  never_signed_in: { label: 'Never signed in',  tone: 'bg-warning/10 text-warning' },
  disabled:        { label: 'Account disabled', tone: 'bg-danger/10 text-danger' },
  missing:         { label: 'No account',       tone: 'bg-danger/10 text-danger' },
  unknown:         { label: "Couldn't check",   tone: 'bg-surface-muted text-muted-foreground' },
};

function ago(iso: string | null): string {
  if (!iso) return '—';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)}m ago`;
  const hrs = Math.round(mins / 60);
  return hrs < 48 ? `${hrs}h ago` : `${Math.round(hrs / 24)}d ago`;
}

function until(iso: string): string {
  const hrs = Math.round((new Date(iso).getTime() - Date.now()) / 3600000);
  return hrs <= 0 ? 'ending now' : hrs < 48 ? `in ${hrs}h` : `in ${Math.round(hrs / 24)}d`;
}

function Chip({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}

export default function SurveyActivityPage() {
  const [data, setData] = useState<SurveyActivity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [shownPassword, setShownPassword] = useState<{ name: string; pw: string } | null>(null);
  const [copied, setCopied] = useState(false);
  // In-page forms: one open at a time.
  const [releasing, setReleasing] = useState<SurveyActivityClaim | null>(null);
  const [reason, setReason] = useState('');
  const [readmitting, setReadmitting] = useState<SurveyContributorHealth | null>(null);
  // ADR-550 D2: reset a surveyor's two-factor, by surveyor ID, with a reason.
  // ADR-555 D2: only the register's owner may take records out of it.
  const { groups } = useAuth();
  const isOwner = groups.includes('super_admin');
  const [withdrawing, setWithdrawing] = useState<SurveyContributorHealth | null>(null);
  const [wRange, setWRange] = useState({ from: getLocalYMD(), to: getLocalYMD() });
  const [wPreview, setWPreview] = useState<number | null>(null);
  const [wReason, setWReason] = useState('');
  const [resetting, setResetting] = useState<SurveyContributorHealth | null>(null);
  // ADR-563 D3: super admin only -- a surveyor who lost their inbox.
  const [emailFor, setEmailFor] = useState<SurveyContributorHealth | null>(null);
  const [resetReason, setResetReason] = useState('');
  // ADR-550 D1: find a surveyor by name, email or surveyor ID.
  const [query, setQuery] = useState('');
  const [agreement, setAgreement] = useState({ version: '', signedOn: getLocalYMD(), confirmed: false });

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await axiosClient.get<SurveyActivity>('/survey/activity');
      setData(data);
    } catch (e) {
      setError(errorText(e, 'Could not load survey activity.'));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (key: string, fn: () => Promise<string>) => {
    setBusy(key); setError(null); setNotice(null);
    try {
      setNotice(await fn());
      await load();
    } catch (e) {
      setError(errorText(e, 'That did not work. Try again.'));
    } finally {
      setBusy(null);
    }
  };

  const resend = (c: SurveyContributorHealth) => run(`resend-${c.id}`, async () => {
    const { data } = await axiosClient.post<SurveyContributorInvited>(`/survey/contributors/${c.id}/resend`);
    if (data.temp_password) {
      setShownPassword({ name: c.display_name, pw: data.temp_password });
      return `The email to ${c.display_name} failed. Give them the temporary password below.`;
    }
    return `New sign-in details sent to ${c.display_name}.`;
  });

  const restore = (c: SurveyContributorHealth) => run(`restore-${c.id}`, async () => {
    await axiosClient.post(`/survey/contributors/${c.id}/restore-access`);
    return `${c.display_name} has surveyor access again.`;
  });

  const submitReadmit = () => readmitting && run(`readmit-${readmitting.id}`, async () => {
    await axiosClient.post(`/survey/contributors/${readmitting.id}/readmit`, {
      agreement_version: agreement.version.trim(),
      agreement_signed_on: agreement.signedOn,
      confirm_agreement_signed: agreement.confirmed,
    });
    const name = readmitting.display_name;
    setReadmitting(null);
    return `${name} is a contributor again.`;
  });

  const previewWithdrawal = () => withdrawing && run(`wpreview-${withdrawing.id}`, async () => {
    const { data } = await axiosClient.get<SurveyWithdrawalPreview>(
      `/survey/contributors/${withdrawing.id}/withdrawal-preview`,
      { params: { from_date: wRange.from, to_date: wRange.to } });
    setWPreview(data.count);
    return '';
  });

  const submitWithdrawal = () => withdrawing && wPreview !== null && run(`withdraw-${withdrawing.id}`, async () => {
    const { data } = await axiosClient.post<SurveyWithdrawalResult>(
      `/survey/contributors/${withdrawing.id}/withdraw-records`,
      { from_date: wRange.from, to_date: wRange.to, reason: wReason.trim(), expected_count: wPreview });
    const name = withdrawing.display_name;
    setWithdrawing(null); setWPreview(null); setWReason('');
    return `Withdrew ${data.count} of ${name}'s records across ${data.blocks_affected} block(s). Their doors are open again; the records stay as evidence.`;
  });

  const submitReset = () => resetting && run(`reset-${resetting.id}`, async () => {
    const { data } = await axiosClient.post<SurveyMfaResetResult>(
      `/survey/contributors/${resetting.id}/reset-mfa`, { reason: resetReason.trim() });
    const name = resetting.display_name;
    setResetting(null); setResetReason('');
    // From the server's outcome, not assumed (ADR-546 Case 1).
    return data.surveyor_emailed
      ? `${name}'s two-factor was reset and they were signed out everywhere. They were emailed the reason and will set it up again at their next sign-in.`
      : `${name}'s two-factor was reset and they were signed out everywhere. The email to them failed, so tell them yourself.`;
  });

  const submitRelease = () => releasing && run(`release-${releasing.id}`, async () => {
    const { data } = await axiosClient.post<SurveyStaffReleaseResult>(
      `/survey/claims/${releasing.id}/staff-release`, { reason: reason.trim() });
    const what = releasing.description;
    const holder = releasing.holder;
    setReleasing(null); setReason('');
    // ADR-546 D4: say what happened, not what was attempted.
    if (holder === 'Owner') return `${what} is free.`;
    return data.holder_emailed
      ? `${what} is free. ${holder} was emailed the reason.`
      : `${what} is free, but ${holder} couldn't be emailed. Let them know another way.`;
  });

  const copyPw = async () => {
    if (!shownPassword) return;
    try { await navigator.clipboard.writeText(shownPassword.pw); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { /* the password stays on screen to select by hand */ }
  };

  return (
    <div className="space-y-5">
      <SectionHeader eyebrow="Platform" title="Survey activity"
        description="Who is surveying, what they're holding, and what's stuck. You can help with accounts and claims; survey records stay with the people who made them." />

      <div className="flex items-center gap-2">
        <button type="button" onClick={load} className="btn-secondary text-sm px-3 py-2 min-h-11 flex items-center gap-1.5">
          <RefreshCw className="w-4 h-4" aria-hidden="true" /> Refresh
        </button>
      </div>

      <ErrorBanner message={error} />
      {notice && (
        <p role="status" className="rounded-lg border border-success/30 bg-success/5 px-3 py-2 text-sm text-success">{notice}</p>
      )}
      {shownPassword && (
        <div className="card p-4 space-y-2" role="status">
          <p className="text-sm">Temporary password for <strong>{shownPassword.name}</strong>. It's shown once; they'll choose their own at sign-in.</p>
          <div className="flex items-center gap-2">
            <code className="rounded-md border border-border bg-surface-muted px-3 py-2 font-mono text-sm select-all">{shownPassword.pw}</code>
            <button type="button" onClick={copyPw} className="btn-ghost min-h-11 px-3 text-sm flex items-center gap-1.5">
              {copied ? <Check className="w-4 h-4" aria-hidden="true" /> : <Copy className="w-4 h-4" aria-hidden="true" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button type="button" onClick={() => setShownPassword(null)} className="btn-ghost min-h-11 px-3 text-sm">Done</button>
          </div>
        </div>
      )}

      {data === null ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : (
        <div className="grid gap-5 2xl:grid-cols-2">
          {/* ── Surveyors ── */}
          <section className="card p-4 space-y-3 2xl:col-span-2" aria-labelledby="people-h">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="people-h" className="text-sm font-semibold">Surveyors</h2>
              <input type="search" value={query} onChange={e => setQuery(e.target.value)}
                     placeholder="Find by name, email or surveyor ID" aria-label="Find a surveyor"
                     className="input min-h-11 w-full sm:w-72" />
            </div>
            {data.contributors.length === 0 ? (
              <p className="text-sm text-muted-foreground">No surveyors yet. Add one from the Surveyors page.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-3">Name</th><th className="py-2 pr-3">Account</th>
                      <th className="py-2 pr-3">Last walk</th><th className="py-2 pr-3">Agreement</th><th className="py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {data.contributors.filter(c => {
                      const q = query.trim().toLowerCase();
                      if (!q) return true;
                      return c.display_name.toLowerCase().includes(q)
                        || (c.email ?? '').toLowerCase().includes(q)
                        || c.id.toLowerCase().startsWith(q);
                    }).map(c => {
                      const s = STATUS[c.account_status];
                      const needsGroup = !c.revoked_at && c.in_surveyor_group === false && c.account_status !== 'missing';
                      return (
                        <tr key={c.id} className="border-t border-border/60 align-top">
                          <td className="py-2 pr-3">
                            <div className="font-medium">{c.display_name}</div>
                            <div className="text-xs text-muted-foreground">{c.email ?? 'no email recorded'}</div>
                            <AccountId id={c.id} label="Surveyor ID" />
                          </td>
                          <td className="py-2 pr-3 space-x-1 space-y-1">
                            {c.revoked_at
                              ? <Chip className="bg-surface-muted text-muted-foreground">Revoked {formatDate(c.revoked_at)}</Chip>
                              : <Chip className={s.tone}>{s.label}</Chip>}
                            {needsGroup && <Chip className="bg-danger/10 text-danger">Missing surveyor access</Chip>}
                            {/* ADR-551 D3: they asked for a reset from the sign-in screen. */}
                            {c.reset_requested_at && !c.revoked_at &&
                              <Chip className="bg-warning/15 text-warning">Reset requested {ago(c.reset_requested_at)}</Chip>}
                          </td>
                          <td className="py-2 pr-3 whitespace-nowrap">{ago(c.last_walk_at)}</td>
                          <td className="py-2 pr-3">{c.agreement_version}, {formatDate(c.agreement_signed_on)}</td>
                          <td className="py-2 text-right whitespace-nowrap">
                            {!c.revoked_at && c.account_status === 'never_signed_in' && (
                              <button type="button" disabled={busy !== null} onClick={() => resend(c)}
                                      className="btn-ghost min-h-11 px-3 text-sm disabled:opacity-50">
                                {busy === `resend-${c.id}` ? 'Sending…' : 'Resend sign-in'}
                              </button>
                            )}
                            {needsGroup && (
                              <button type="button" disabled={busy !== null} onClick={() => restore(c)}
                                      className="btn-ghost min-h-11 px-3 text-sm disabled:opacity-50">
                                {busy === `restore-${c.id}` ? 'Restoring…' : 'Restore access'}
                              </button>
                            )}
                            {!c.revoked_at && c.account_status === 'active' && (
                              <button type="button" disabled={busy !== null}
                                      onClick={() => { setResetting(c); setResetReason(''); }}
                                      className="btn-ghost min-h-11 px-3 text-sm disabled:opacity-50">
                                Reset two-factor
                              </button>
                            )}
                            {isOwner && !c.revoked_at && (
                              <button type="button" disabled={busy !== null} onClick={() => setEmailFor(c)}
                                      className="btn-ghost min-h-11 px-3 text-sm disabled:opacity-50">
                                Change email
                              </button>
                            )}
                            {isOwner && (
                              <button type="button" disabled={busy !== null}
                                      onClick={() => { setWithdrawing(c); setWPreview(null); setWReason(''); setWRange({ from: getLocalYMD(), to: getLocalYMD() }); }}
                                      className="btn-ghost min-h-11 px-3 text-sm text-danger disabled:opacity-50">
                                Withdraw records…
                              </button>
                            )}
                            {c.revoked_at && (
                              <button type="button" disabled={busy !== null}
                                      onClick={() => { setReadmitting(c); setAgreement({ version: '', signedOn: getLocalYMD(), confirmed: false }); }}
                                      className="btn-ghost min-h-11 px-3 text-sm disabled:opacity-50">
                                Re-admit
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {withdrawing && (
              <form className="rounded-lg border border-danger/30 p-3 space-y-3"
                    onSubmit={e => { e.preventDefault(); submitWithdrawal(); }}>
                <p className="text-sm">
                  Withdraw <strong>{withdrawing.display_name}</strong>'s records{' '}
                  <AccountId id={withdrawing.id} label="Surveyor ID" />. They stop counting everywhere and the doors
                  they locked open again. The records themselves stay, as evidence (ADR-504).
                </p>
                <div className="flex flex-wrap items-end gap-3">
                  <label className="text-sm space-y-1">
                    <span className="block text-xs text-muted-foreground">From</span>
                    <input type="date" required max={getLocalYMD()} value={wRange.from} className="input min-h-11"
                           onChange={e => { setWRange(r => ({ ...r, from: e.target.value })); setWPreview(null); }} />
                  </label>
                  <label className="text-sm space-y-1">
                    <span className="block text-xs text-muted-foreground">To</span>
                    <input type="date" required max={getLocalYMD()} value={wRange.to} className="input min-h-11"
                           onChange={e => { setWRange(r => ({ ...r, to: e.target.value })); setWPreview(null); }} />
                  </label>
                  <button type="button" onClick={previewWithdrawal} disabled={busy !== null}
                          className="btn-ghost min-h-11 px-3 text-sm disabled:opacity-50">
                    {busy?.startsWith('wpreview') ? 'Counting…' : 'Count records'}
                  </button>
                </div>
                {wPreview !== null && (
                  <>
                    <p className="text-sm font-medium" aria-live="polite">
                      {wPreview === 0 ? 'No records to withdraw in that range.' : `${wPreview} record(s) in that range.`}
                    </p>
                    {wPreview > 0 && (
                      <>
                        <label htmlFor="withdraw-reason" className="block text-xs text-muted-foreground">Reason (10–200 characters)</label>
                        <textarea id="withdraw-reason" required minLength={10} maxLength={200} rows={2}
                                  value={wReason} onChange={e => setWReason(e.target.value)} className="input w-full" />
                      </>
                    )}
                  </>
                )}
                <div className="flex gap-2">
                  <button type="button" onClick={() => setWithdrawing(null)} className="btn-ghost min-h-11 px-3 text-sm">Cancel</button>
                  <button type="submit" disabled={!wPreview || wReason.trim().length < 10 || busy !== null}
                          className="btn-primary min-h-11 px-3 text-sm bg-danger disabled:opacity-50">
                    {busy?.startsWith('withdraw') ? 'Withdrawing…' : wPreview ? `Withdraw ${wPreview} record(s)` : 'Withdraw'}
                  </button>
                </div>
              </form>
            )}

            {resetting && (
              <form className="rounded-lg border border-border p-3 space-y-3"
                    onSubmit={e => { e.preventDefault(); submitReset(); }}>
                <p className="text-sm">
                  Reset two-factor for <strong>{resetting.display_name}</strong>{' '}
                  <AccountId id={resetting.id} label="Surveyor ID" />. This clears their authenticator, signs them out
                  everywhere, and gives them 24 hours from their next sign-in to set it up again. They're emailed the reason.
                </p>
                <label htmlFor="reset-reason" className="block text-xs text-muted-foreground">
                  Reason (10–200 characters). Never paste a code or password.
                </label>
                <textarea id="reset-reason" required minLength={10} maxLength={200} rows={2}
                          value={resetReason} onChange={e => setResetReason(e.target.value)}
                          className="input w-full" />
                <div className="flex gap-2">
                  <button type="button" onClick={() => setResetting(null)} className="btn-ghost min-h-11 px-3 text-sm">Cancel</button>
                  <button type="submit" disabled={resetReason.trim().length < 10 || busy !== null}
                          className="btn-primary min-h-11 px-3 text-sm disabled:opacity-50">
                    {busy?.startsWith('reset') ? 'Resetting…' : 'Reset two-factor'}
                  </button>
                </div>
              </form>
            )}

            {readmitting && (
              <form className="rounded-lg border border-border p-3 space-y-3"
                    onSubmit={e => { e.preventDefault(); submitReadmit(); }}>
                <p className="text-sm">
                  Re-admitting <strong>{readmitting.display_name}</strong> is admission again: they need to have signed
                  the contributor agreement again.
                </p>
                <div className="flex flex-wrap gap-3">
                  <label className="text-sm space-y-1">
                    <span className="block text-xs text-muted-foreground">Agreement version</span>
                    <input id="readmit-version" required maxLength={20} value={agreement.version}
                           onChange={e => setAgreement(a => ({ ...a, version: e.target.value }))}
                           className="input min-h-11" />
                  </label>
                  <label className="text-sm space-y-1">
                    <span className="block text-xs text-muted-foreground">Signed on</span>
                    <input id="readmit-date" type="date" required max={getLocalYMD()} value={agreement.signedOn}
                           onChange={e => setAgreement(a => ({ ...a, signedOn: e.target.value }))}
                           className="input min-h-11" />
                  </label>
                </div>
                <label className="flex items-start gap-2 text-sm">
                  <input id="readmit-confirm" type="checkbox" checked={agreement.confirmed} className="mt-1"
                         onChange={e => setAgreement(a => ({ ...a, confirmed: e.target.checked }))} />
                  I hold their newly signed contributor agreement.
                </label>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setReadmitting(null)} className="btn-ghost min-h-11 px-3 text-sm">Cancel</button>
                  <button type="submit" disabled={!agreement.confirmed || !agreement.version.trim() || busy !== null}
                          className="btn-primary min-h-11 px-3 text-sm disabled:opacity-50">
                    {busy?.startsWith('readmit') ? 'Re-admitting…' : 'Re-admit'}
                  </button>
                </div>
              </form>
            )}
          </section>

          {/* ── Blocks held ── */}
          <section className="card p-4 space-y-3" aria-labelledby="claims-h">
            <h2 id="claims-h" className="text-sm font-semibold">Blocks being held</h2>
            <p className="text-xs text-muted-foreground">A hold lasts 48 hours. Release one that's stuck so someone else can walk it.</p>
            {data.claims.length === 0 ? (
              <p className="text-sm text-muted-foreground">No blocks are held right now.</p>
            ) : (
              <ul className="space-y-2">
                {data.claims.map(cl => (
                  <li key={cl.id} className="rounded-lg border border-border p-3 space-y-2">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-medium">{cl.description}</div>
                        <div className="text-xs text-muted-foreground">
                          {cl.area_name} · {cl.holder} · held {ago(cl.claimed_at)} · ends {until(cl.expires_at)}
                          {cl.walk_open && ' · walk open'}
                        </div>
                      </div>
                      {releasing?.id !== cl.id && (
                        <button type="button" disabled={busy !== null}
                                onClick={() => { setReleasing(cl); setReason(''); }}
                                className="btn-ghost min-h-11 px-3 text-sm text-danger disabled:opacity-50">
                          Release
                        </button>
                      )}
                    </div>
                    {releasing?.id === cl.id && (
                      <form className="space-y-2" onSubmit={e => { e.preventDefault(); submitRelease(); }}>
                        <label htmlFor="release-reason" className="block text-xs text-muted-foreground">
                          Reason (sent to {cl.holder === 'Owner' ? 'nobody: this is your own hold' : cl.holder}). Never include codes.
                        </label>
                        <textarea id="release-reason" required minLength={10} maxLength={200} rows={2}
                                  value={reason} onChange={e => setReason(e.target.value)}
                                  className="input w-full" placeholder="Held for two days with no doors recorded" />
                        <p className="text-xs text-muted-foreground">Anything already recorded on this block is kept.</p>
                        <div className="flex gap-2">
                          <button type="button" onClick={() => setReleasing(null)} className="btn-ghost min-h-11 px-3 text-sm">Cancel</button>
                          <button type="submit" disabled={reason.trim().length < 10 || busy !== null}
                                  className="btn-danger min-h-11 px-3 text-sm disabled:opacity-50">
                            {busy?.startsWith('release') ? 'Releasing…' : 'Release the block'}
                          </button>
                        </div>
                      </form>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── Open walks ── */}
          <section className="card p-4 space-y-3" aria-labelledby="walks-h">
            <h2 id="walks-h" className="text-sm font-semibold">Walks in progress</h2>
            {data.open_walks.length === 0 ? (
              <p className="text-sm text-muted-foreground">No walks are open.</p>
            ) : (
              <ul className="space-y-2">
                {data.open_walks.map(w => (
                  <li key={w.id} className="rounded-lg border border-border p-3">
                    <div className="font-medium">{w.street}</div>
                    <div className="text-xs text-muted-foreground">
                      {w.area_name ? `${w.area_name} · ` : ''}{w.holder} · started {formatDateTime(new Date(w.started_at))}
                      {' · '}last door {ago(w.last_observation_at)} · {w.doors_done} of {w.doors_total} doors
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
      <AdminEmailChangeDialog
        open={emailFor !== null}
        personName={emailFor?.display_name ?? ''}
        onClose={() => setEmailFor(null)}
        submit={async (newEmail) => (await axiosClient.post(
          `/survey/contributors/${emailFor!.id}/email/change`, { new_email: newEmail })).data}
      />
    </div>
  );
}
