/**
 * Hand an open campaign to the company whose staff collected it (ADR-495 D3).
 *
 * Platform view only. One-way: the server refuses a second assignment, because
 * moving the rows again would move one DSP's customer addresses to another.
 * The attestation checkbox is the recorded statement that makes the move
 * custody rather than disclosure, and the button stays disabled without it.
 */
import { useEffect, useState } from 'react';
import { Building2, Loader2 } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../ui/ErrorBanner';
import ConfirmDialog from '../ui/ConfirmDialog';
import { errorText } from '../../utils/errorText';
import type { AssignCampaignRequest, CollectionTokenSummary } from '../../api/types';

type CompanyOption = { id: string; name: string };

export default function AssignCampaign({ token, onAssigned }: {
  token: CollectionTokenSummary;
  onAssigned: () => void;
}) {
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [attested, setAttested] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get<CompanyOption[]>('/admin/companies/')
      .then(r => setCompanies(r.data))
      .catch(e => setError(errorText(e, 'Could not load companies.')));
  }, []);

  if (token.revoked_at === null) {
    return (
      <p className="text-[11px] text-muted-foreground">
        To move this campaign's addresses to a company for review, revoke the link first.
      </p>
    );
  }

  const company = companies.find(c => c.id === companyId);

  const assign = async () => {
    setBusy(true);
    setError(null);
    try {
      const body: AssignCampaignRequest = { company_id: companyId, attest_collected_for_company: attested };
      await axiosClient.post(`/collection/tokens/${token.id}/assign`, body);
      onAssigned();
    } catch (e) {
      setError(errorText(e, 'Assignment failed. Nothing was moved.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-surface/60 p-2.5 space-y-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1">
        <Building2 className="w-3.5 h-3.5" /> Assign to a company
      </p>
      <p className="text-[11px] text-muted-foreground">
        Moves {token.submission_count} collected address{token.submission_count === 1 ? '' : 'es'} into
        one company, whose admins then review them into Building Profiles. This can't be changed later.
      </p>
      <ErrorBanner message={error} />
      <select value={companyId} onChange={e => setCompanyId(e.target.value)}
        aria-label="Company" className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs">
        <option value="">Choose a company…</option>
        {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <label className="flex items-start gap-1.5 text-[11px]">
        <input type="checkbox" className="mt-0.5 accent-primary" checked={attested}
          onChange={e => setAttested(e.target.checked)} />
        <span>This company's staff collected these addresses while working for it.</span>
      </label>
      <button type="button" disabled={!companyId || !attested || busy}
        onClick={() => setConfirming(true)}
        className="btn-secondary w-full text-xs inline-flex items-center justify-center gap-1.5">
        {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Assign
      </button>
      <ConfirmDialog
        open={confirming}
        title={`Assign to ${company?.name ?? 'this company'}?`}
        message={`"${token.label}" and its ${token.submission_count} rows move to ${company?.name ?? 'this company'} permanently.`}
        confirmLabel="Assign"
        onConfirm={() => { setConfirming(false); void assign(); }}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
