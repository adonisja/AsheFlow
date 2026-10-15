/**
 * Survey contributors (ADR-509): onboard and revoke.
 *
 * The one platform page open to platform support as well as the owner. It can
 * only create NEW accounts (an existing email is refused), never the caller's
 * own, and never an account linked to the excluded company's employees. The
 * server enforces all three; this page explains them.
 */
import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, Loader2, UserPlus } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import ErrorBanner from '../../components/ui/ErrorBanner';
import ConfirmDialog from '../../components/ui/ConfirmDialog';
import { errorText } from '../../utils/errorText';
import { formatDate } from '../../utils/date';
import type { SurveyContributor, SurveyContributorInvite, SurveyContributorInvited } from '../../api/types';

const today = () => new Date().toISOString().slice(0, 10);
const inputCls = 'w-full rounded-lg border border-input bg-background px-3 py-2 text-sm';

export default function Surveyors() {
  const [rows, setRows] = useState<SurveyContributor[] | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [version, setVersion] = useState('v1');
  const [signedOn, setSignedOn] = useState(today());
  const [holdsAgreement, setHoldsAgreement] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SurveyContributorInvited | null>(null);
  const [toRevoke, setToRevoke] = useState<SurveyContributor | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows((await axiosClient.get<SurveyContributor[]>('/survey/contributors')).data);
    } catch (e) {
      setError(errorText(e, "Couldn't load contributors."));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const invite = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body: SurveyContributorInvite = {
        name: name.trim(), email: email.trim(), agreement_version: version.trim(),
        agreement_signed_on: signedOn, confirm_agreement_signed: true,
      };
      const { data } = await axiosClient.post<SurveyContributorInvited>('/survey/contributors/invite', body);
      setResult(data);
      setCopied(false);
      setName(''); setEmail(''); setHoldsAgreement(false);
      await load();
    } catch (e) {
      setError(errorText(e, "Couldn't create the account."));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!toRevoke) return;
    setBusy(true);
    setError(null);
    try {
      await axiosClient.post(`/survey/contributors/${toRevoke.id}/revoke`);
      setToRevoke(null);
      await load();
    } catch (e) {
      setError(errorText(e, "Couldn't revoke access."));
    } finally {
      setBusy(false);
    }
  };

  const ready = name.trim() && email.trim() && version.trim() && signedOn && holdsAgreement;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-5">
      <SectionHeader eyebrow="Platform" title="Surveyors"
        description="People who add to the survey register. Each one signs the contributor agreement first; this creates their account and admits them in one step." />

      <ErrorBanner message={error} />

      {result && (
        <div className="card p-4 text-sm space-y-2" role="status">
          <p>
            <span className="font-semibold">{result.contributor.display_name}</span> can now sign in as{' '}
            <span className="font-mono">{result.contributor.cognito_username}</span>.
          </p>
          {result.email_delivered ? (
            <p className="text-muted-foreground">Their sign-in details were emailed to them.</p>
          ) : (
            <div className="space-y-1">
              <p className="text-warning">
                The email didn't send. Give them this temporary password yourself. It is shown once.
              </p>
              <div className="flex items-center gap-2">
                <code className="rounded-md border border-border px-2 py-1 font-mono">{result.temp_password}</code>
                <button type="button" className="btn-ghost inline-flex items-center gap-1 px-2 py-1.5 text-xs"
                  aria-label={copied ? 'Password copied' : 'Copy password'}
                  onClick={() => {
                    navigator.clipboard.writeText(result.temp_password ?? '')
                      .then(() => setCopied(true))
                      .catch(() => setError("Couldn't copy. Select the password and copy it yourself."));
                  }}>
                  {copied ? <><Check className="h-4 w-4 text-success" /> Copied</> : <><Copy className="h-4 w-4" /> Copy</>}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <section className="card p-4 space-y-3" aria-labelledby="invite-h">
        <h2 id="invite-h" className="text-sm font-semibold">Add a surveyor</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Name</span>
            <input className={inputCls} value={name} maxLength={100} onChange={e => setName(e.target.value)} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Email</span>
            <input className={inputCls} type="email" value={email} onChange={e => setEmail(e.target.value)} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Agreement version</span>
            <input className={inputCls} value={version} maxLength={20} onChange={e => setVersion(e.target.value)} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Signed on</span>
            <input className={inputCls} type="date" value={signedOn} max={today()} onChange={e => setSignedOn(e.target.value)} />
          </label>
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-primary" checked={holdsAgreement}
            onChange={e => setHoldsAgreement(e.target.checked)} />
          <span>I have their signed contributor agreement, and they don't work for our delivery company.</span>
        </label>
        <p className="text-xs text-muted-foreground">
          This creates a new account only. If they already have one, the owner admits it instead.
        </p>
        <button type="button" onClick={() => void invite()} disabled={!ready || busy}
          className="btn-primary text-sm inline-flex items-center gap-2">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
          Create account and admit
        </button>
      </section>

      <section className="card p-4 space-y-2" aria-labelledby="list-h">
        <h2 id="list-h" className="text-sm font-semibold">Contributors</h2>
        {rows === null ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No surveyors yet. Once someone has signed the contributor agreement, add them above.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3">Name</th><th className="py-2 pr-3">Email</th>
                  <th className="py-2 pr-3">Agreement</th><th className="py-2 pr-3">Admitted</th>
                  <th className="py-2 pr-3">Status</th><th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id} className="border-t border-border/60">
                    <td className="py-2 pr-3">{r.display_name}</td>
                    <td className="py-2 pr-3 text-muted-foreground">{r.email ?? 'not recorded'}</td>
                    <td className="py-2 pr-3">{r.agreement_version}, signed {formatDate(r.agreement_signed_on)}</td>
                    <td className="py-2 pr-3">{formatDate(r.admitted_at)}</td>
                    <td className="py-2 pr-3">{r.revoked_at ? `Revoked ${formatDate(r.revoked_at)}` : 'Active'}</td>
                    <td className="py-2 text-right">
                      {!r.revoked_at && (
                        <button type="button" className="btn-ghost text-xs text-danger" onClick={() => setToRevoke(r)}>
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={toRevoke !== null}
        title={`Revoke ${toRevoke?.display_name ?? ''}?`}
        message="They stop being able to add to the register immediately. What they already recorded stays, still attributed to their account."
        confirmLabel="Revoke"
        variant="danger"
        onConfirm={() => void revoke()}
        onCancel={() => setToRevoke(null)}
      />
    </div>
  );
}
