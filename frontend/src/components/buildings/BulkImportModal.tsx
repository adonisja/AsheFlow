/**
 * ADR-277 D4 — bulk building-profile import.
 *
 * Preview then confirm, deliberately. A bad building_type or an address that
 * already has a profile must be visible BEFORE anything is written, not
 * discovered as thirty rejected rows afterwards.
 *
 * The preview keeps invalid rows rather than filtering them out, so the
 * operator can see which of their lines will not import and fix the file —
 * a silently shortened list is the failure this design exists to avoid.
 */
import { useState } from 'react';
import { Upload, X, AlertTriangle, CheckCircle2, Copy } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import { errorText } from '../../utils/errorText';
import type { BulkProfilePreview, BulkProfileResult } from '../../api/types';

const TEMPLATE = 'address,building_type\n433 W 32 St,elevator\n1 Penn Plaza,biz_security\n';

const BUILDING_TYPES = [
  'mailroom', 'receptionist', 'doorman', 'walkup', 'elevator',
  'biz_front', 'biz_freight', 'biz_security', 'biz_loading_dock',
];

export default function BulkImportModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const [preview, setPreview] = useState<BulkProfilePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkProfileResult | null>(null);

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const { data } = await axiosClient.post<BulkProfilePreview>(
        '/building-profiles/bulk/preview',
        form,
      );
      setPreview(data);
    } catch (e) {
      setError(errorText(e, 'Could not read that file.'));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await axiosClient.post<BulkProfileResult>(
        '/building-profiles/bulk/confirm',
        // Only the rows that passed. The server re-validates regardless — the
        // preview is a courtesy to the human, not a trust boundary.
        { rows: preview.rows.filter((r) => r.ok) },
      );
      setResult(data);
      onImported();
    } catch (e) {
      setError(errorText(e, 'Import failed.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-lg border border-border bg-card p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold">Import building profiles</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              A CSV with <code>address</code> and <code>building_type</code>.
              Everything you import waits for one confirmation from somebody
              who has since been there.
            </p>
          </div>
          <button onClick={onClose} className="btn-ghost p-1" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        {!result && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-3">
              <label className="btn-primary inline-flex cursor-pointer items-center gap-1.5 text-sm">
                <Upload className="w-4 h-4" /> Choose CSV
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void upload(f);
                  }}
                />
              </label>
              <button
                type="button"
                onClick={() => void navigator.clipboard?.writeText(TEMPLATE)}
                className="btn-ghost inline-flex items-center gap-1.5 text-xs"
              >
                <Copy className="w-3.5 h-3.5" /> Copy template
              </button>
            </div>

            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Valid building types</summary>
              <p className="mt-1 font-mono">{BUILDING_TYPES.join(', ')}</p>
            </details>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {result ? (
          <div className="mt-4 space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="w-4 h-4 text-success" />
              <span>
                Imported <strong>{result.created}</strong>
                {result.skipped > 0 && `, skipped ${result.skipped}`}
              </span>
            </div>
            <button onClick={onClose} className="btn-primary text-sm">
              Done
            </button>
          </div>
        ) : preview ? (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span className="text-success font-semibold">{preview.valid_count} will import</span>
              {preview.duplicate_count > 0 && (
                <span className="text-muted-foreground">
                  {preview.duplicate_count} already profiled
                </span>
              )}
              {preview.error_count > 0 && (
                <span className="text-warning font-semibold">
                  {preview.error_count} need fixing
                </span>
              )}
            </div>

            <div className="max-h-64 overflow-y-auto rounded-md border border-border">
              <table className="w-full text-xs">
                <tbody>
                  {preview.rows.map((r) => (
                    <tr key={r.line} className="border-b border-border last:border-0">
                      <td className="px-2 py-1.5 text-muted-foreground w-10 tabular-nums">
                        {r.line}
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="truncate">{r.address || <em>(blank)</em>}</div>
                        {r.error && (
                          <div className="flex items-center gap-1 text-warning">
                            <AlertTriangle className="w-3 h-3 shrink-0" />
                            {r.error}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-right text-muted-foreground">
                        {r.building_type}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => void confirm()}
                disabled={busy || preview.valid_count === 0}
                className="btn-primary text-sm disabled:opacity-50"
              >
                {busy ? 'Importing…' : `Import ${preview.valid_count}`}
              </button>
              <button onClick={() => setPreview(null)} className="btn-ghost text-sm">
                Choose another file
              </button>
            </div>
          </div>
        ) : busy ? (
          <p className="mt-4 text-sm text-muted-foreground">Reading file…</p>
        ) : null}
      </div>
    </div>
  );
}
