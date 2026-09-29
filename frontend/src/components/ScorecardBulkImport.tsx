/**
 * Bulk scorecard import, and the binding queue it produces (ADR-476).
 *
 * A week of scorecards is one upload of Amazon's DSP export rather than fifty
 * image uploads — which is the difference between a feature that gets used and
 * one that does not.
 *
 * THE QUEUE IS THE POINT, not an error state. Amazon identifies a person by
 * Transporter ID; we cannot know whose it is until somebody says. So an unknown
 * ID parks with its data intact and waits for a human, because a fuzzy name
 * match that is right 98% of the time misroutes one row in fifty — silently,
 * permanently, and visibly to the wrong person.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Link2, Upload, Users } from 'lucide-react';

import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import ErrorBanner from './ui/ErrorBanner';
import SelectMenu from './ui/SelectMenu';
import type { BulkImportResult, PendingBinding } from '../api/types';

export default function ScorecardBulkImport() {
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkImportResult | null>(null);

  const [pending, setPending] = useState<PendingBinding[] | null>(null);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [binding, setBinding] = useState<string | null>(null);

  const loadPending = useCallback(async () => {
    try {
      const r = await axiosClient.get<PendingBinding[]>('/scorecards/pending-bindings');
      setPending(r.data);
    } catch {
      setPending([]);
    }
  }, []);

  useEffect(() => { void loadPending(); }, [loadPending]);

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await axiosClient.post<BulkImportResult>(
        '/scorecards/bulk-import', form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      setResult(r.data);
      await loadPending();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not import that file.'));
    } finally {
      setBusy(false);
    }
  };

  const bind = async (transporterId: string) => {
    const employeeId = choice[transporterId];
    if (!employeeId) return;
    setBinding(transporterId);
    setError(null);
    try {
      const r = await axiosClient.post<BulkImportResult>(
        '/scorecards/pending-bindings/bind',
        { transporter_id: transporterId, employee_id: employeeId },
      );
      setResult(r.data);
      await loadPending();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not bind that ID.'));
    } finally {
      setBinding(null);
    }
  };

  const queueCount = pending?.length ?? 0;

  return (
    <div className="space-y-4">
      {/* ---- upload ---- */}
      <div className="card">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-foreground">
            Import a week from Amazon
          </h3>
          <p className="text-xs text-muted-foreground mt-1">
            Each row is filed by its Transporter ID, so nobody is matched by name.
          </p>
        </div>

        {/* The house drop zone (components/BulkImportModal). Dragging the export
            straight off a download folder is the natural gesture here, and a
            bare button does not invite it. */}
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f && !busy) void upload(f);
          }}
          onClick={() => !busy && fileRef.current?.click()}
          className={`border-2 border-dashed rounded-2xl p-8 flex flex-col items-center gap-3 cursor-pointer transition-colors ${
            dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50 hover:bg-accent/30'
          } ${busy ? 'opacity-60 pointer-events-none' : ''}`}
        >
          <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
            <Upload className="w-6 h-6 text-primary" />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-foreground">
              {busy ? 'Importing…' : 'Drop the DSP export here or click to browse'}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              One file covers everyone for that week · CSV · max 8 MB
            </p>
          </div>
        </div>

        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={e => {
            const f = e.target.files?.[0];
            // Cleared so choosing the SAME file again re-fires onChange -- a
            // re-upload after fixing bindings is the normal path here.
            e.target.value = '';
            if (f) void upload(f);
          }}
        />

        {/* Stated, as BulkImportModal does: an export whose columns changed
            should be recognisable as wrong BEFORE it is uploaded. */}
        <div className="bg-accent/40 rounded-xl p-4 mt-4">
          <p className="text-xs font-semibold text-foreground uppercase tracking-wider">
            Expected columns
          </p>
          <p className="text-xs text-muted-foreground mt-1.5">
            <span className="text-foreground font-medium">Week</span> ·{' '}
            <span className="text-foreground font-medium">Transporter ID</span> ·{' '}
            <span className="text-foreground font-medium">Delivery Associate</span> ·
            Overall Standing, and a value column per metric. Anything we do not
            recognise is reported rather than skipped quietly.
          </p>
        </div>

        {error && <div className="mt-3"><ErrorBanner message={error} /></div>}

        {result && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              <Stat label="Imported" value={result.imported} tone="success" />
              {result.queued > 0 &&
                <Stat label="Need binding" value={result.queued} tone="warning" />}
              {result.name_mismatches > 0 &&
                <Stat label="Name differs" value={result.name_mismatches} tone="warning" />}
              {result.errors > 0 &&
                <Stat label="Errors" value={result.errors} tone="danger" />}
              {result.skipped_no_id > 0 &&
                <Stat label="No ID" value={result.skipped_no_id} tone="danger" />}
            </div>

            {/* A changed export announces itself here rather than by quietly
                losing a column (ADR-476 D6). */}
            {result.unknown_headers.length > 0 && (
              <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2">
                <p className="text-xs font-semibold text-warning">
                  Columns we did not recognise
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {result.unknown_headers.join(' · ')}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Everything else imported. If Amazon has renamed a metric, these
                  are the columns that were skipped.
                </p>
              </div>
            )}

            {/* Only the rows that need a human. A list of every successful row
                is noise on a file of eighty. */}
            {result.rows.filter(r => r.outcome !== 'imported').length > 0 && (
              <ul className="divide-y divide-border text-xs">
                {result.rows.filter(r => r.outcome !== 'imported').map((r, i) => (
                  <li key={`${r.transporter_id}-${r.week}-${i}`} className="py-2">
                    <span className="font-medium text-foreground">
                      {r.da_name || r.transporter_id}
                    </span>
                    <span className="text-muted-foreground"> · {r.week} · </span>
                    <span className={
                      r.outcome === 'error' ? 'text-danger' : 'text-warning'
                    }>
                      {r.outcome === 'queued' ? 'needs binding'
                        : r.outcome === 'name_mismatch' ? 'name differs'
                        : 'error'}
                    </span>
                    {r.detail && (
                      <p className="text-muted-foreground mt-0.5">{r.detail}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* ---- the binding queue ---- */}
      {queueCount > 0 && (
        <div className="card">
          <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Users className="w-4 h-4 text-warning" />
            {queueCount === 1
              ? 'One ID needs a name'
              : `${queueCount} IDs need a name`}
          </h3>
          <p className="text-xs text-muted-foreground mt-1">
            Amazon identifies these people by Transporter ID. Match each to
            someone on your roster once and every week we are holding for them
            imports — and future weeks match on their own.
          </p>

          <div className="mt-4 space-y-2">
            {pending!.map(p => (
              <div
                key={p.transporter_id}
                className="flex flex-wrap items-center gap-3 py-2.5 border-b border-border last:border-0"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground truncate">
                    {p.da_name || <span className="italic text-muted-foreground">No name on the export</span>}
                  </p>
                  <p className="text-[11px] text-muted-foreground font-mono">
                    {p.transporter_id}
                    <span className="ml-2 font-sans">
                      {p.weeks.length === 1
                        ? `${p.weeks.length} week held`
                        : `${p.weeks.length} weeks held`}
                    </span>
                  </p>
                </div>

                {/* The house dropdown, not a native <select> (ui/SelectMenu).
                    It carries the role as a `hint` per option, which is what
                    makes two people with similar names distinguishable here --
                    exactly the case this queue exists to get right.

                    No pre-selection: the closest name is listed FIRST, which is
                    a suggestion, and choosing is the operator's. */}
                <div className="w-56">
                  <SelectMenu
                    value={choice[p.transporter_id] ?? ''}
                    placeholder="Select the person…"
                    ariaLabel={`Bind ${p.da_name || p.transporter_id} to an employee`}
                    options={p.suggestions.map(s => ({
                      value: s.employee_id,
                      label: s.name,
                      hint: s.role,
                    }))}
                    onChange={v => setChoice(c => ({ ...c, [p.transporter_id]: v }))}
                  />
                </div>

                <button
                  type="button"
                  disabled={!choice[p.transporter_id] || binding === p.transporter_id}
                  onClick={() => void bind(p.transporter_id)}
                  className="btn-ghost text-sm inline-flex items-center gap-1.5 disabled:opacity-40"
                >
                  <Link2 className="w-3.5 h-3.5" />
                  {binding === p.transporter_id ? 'Binding…' : 'Bind'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {pending !== null && queueCount === 0 && result && result.imported > 0 && (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <CheckCircle2 className="w-3.5 h-3.5 text-success" />
          Every Transporter ID in that file is bound to someone.
        </p>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: {
  label: string; value: number; tone: 'success' | 'warning' | 'danger';
}) {
  const cls = tone === 'success' ? 'bg-success/10 text-success'
    : tone === 'warning' ? 'bg-warning/10 text-warning'
    : 'bg-danger/10 text-danger';
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium ${cls}`}>
      {tone !== 'success' && <AlertTriangle className="w-3 h-3" />}
      {value} {label}
    </span>
  );
}
