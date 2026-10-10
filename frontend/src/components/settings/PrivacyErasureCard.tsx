/**
 * Erase on Amazon's request (ADR-493 D2). Admin only — lives in Company Settings.
 *
 * Two steps, by design. "Preview" is a dry run: the server returns exactly what
 * the real run would touch — per-table counts and every stored spelling the
 * address matched — and changes nothing. "Erase permanently" is enabled only for
 * the value that was previewed, and asks once more. The erasure cannot be undone:
 * it is ledgered so that even a backup restore re-applies it.
 */
import React, { useState } from 'react';
import { ShieldOff, Loader2, Search } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../ui/ErrorBanner';
import ConfirmDialog from '../ui/ConfirmDialog';
import { errorText } from '../../utils/errorText';
import type { ErasureRequest, ErasureResult } from '../../api/types';

export default function PrivacyErasureCard() {
  const [kind, setKind] = useState<ErasureRequest['kind']>('address');
  const [value, setValue] = useState('');
  const [preview, setPreview] = useState<ErasureResult | null>(null);
  const [previewedFor, setPreviewedFor] = useState<string | null>(null);
  const [done, setDone] = useState<ErasureResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestKey = `${kind}:${value.trim()}`;
  const previewIsCurrent = preview !== null && previewedFor === requestKey;

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const body: ErasureRequest = { kind, value: value.trim(), dry_run: dryRun };
      const { data } = await axiosClient.post<ErasureResult>('/privacy/erasure', body);
      if (dryRun) {
        setPreview(data);
        setPreviewedFor(requestKey);
        setDone(null);
      } else {
        setDone(data);
        setPreview(null);
        setPreviewedFor(null);
        setValue('');
      }
    } catch (e) {
      setError(errorText(e, dryRun ? 'Preview failed.' : 'Erasure failed. Nothing was changed.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-start gap-3">
        <ShieldOff className="w-5 h-5 text-muted-foreground mt-0.5 shrink-0" />
        <div className="min-w-0">
          <h3 className="section-title mb-1">Erase on Amazon's request</h3>
          <p className="text-sm text-subtle">
            The DSP agreement requires deleting a customer's personal information when Amazon
            asks. Enter the address or package ID from the request; AsheFlow removes it from
            every record in your company, including audit history. Preview first — erasure is
            permanent.
          </p>
        </div>
      </div>

      <ErrorBanner message={error} />

      <div className="flex flex-wrap items-end gap-3">
        <fieldset className="flex gap-3 text-sm">
          <legend className="sr-only">What Amazon named</legend>
          <label className="flex items-center gap-1.5">
            <input type="radio" name="erasure-kind" className="accent-primary"
              checked={kind === 'address'} onChange={() => setKind('address')} />
            Address
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" name="erasure-kind" className="accent-primary"
              checked={kind === 'tba'} onChange={() => setKind('tba')} />
            Package ID (TBA)
          </label>
        </fieldset>
        <input
          type="text"
          value={value}
          maxLength={200}
          onChange={e => setValue(e.target.value)}
          placeholder={kind === 'address' ? '433 W 32nd St' : 'TBA123456789000'}
          aria-label={kind === 'address' ? 'Address to erase' : 'Package ID to erase'}
          className="flex-1 min-w-[12rem] border border-input rounded-lg px-3 py-2 text-sm bg-background"
        />
        <button
          type="button"
          onClick={() => run(true)}
          disabled={busy || value.trim().length < 3}
          className="btn-ghost text-sm flex items-center gap-2"
        >
          {busy && !confirming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          Preview
        </button>
      </div>

      {previewIsCurrent && preview && (
        <div className="rounded-lg border border-border p-3 space-y-2 text-sm">
          {preview.total === 0 ? (
            <p className="text-subtle">Nothing in your company matches. There is nothing to erase.</p>
          ) : (
            <>
              <p className="text-foreground">
                <span className="font-semibold">{preview.total}</span> value
                {preview.total === 1 ? '' : 's'} would be erased.
              </p>
              {preview.matched.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Matched as: {preview.matched.join(' · ')}
                </p>
              )}
              <ul className="text-xs text-subtle grid sm:grid-cols-2 gap-x-4">
                {Object.entries(preview.counts).map(([where, n]) => (
                  <li key={where} className="flex justify-between gap-2">
                    <span className="font-mono truncate">{where}</span><span>{n}</span>
                  </li>
                ))}
              </ul>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  disabled={busy}
                  className="btn-danger text-sm"
                >
                  Erase permanently
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {done && (
        <p className="text-sm text-success" role="status">
          Erased {done.total} value{done.total === 1 ? '' : 's'}. Recorded in the audit log without the value itself.
        </p>
      )}

      <ConfirmDialog
        open={confirming}
        title="Erase permanently?"
        message={`This removes ${preview?.total ?? 0} value(s) from your company's records, including audit history. It cannot be undone.`}
        confirmLabel="Erase"
        variant="danger"
        onConfirm={() => { setConfirming(false); run(false); }}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
