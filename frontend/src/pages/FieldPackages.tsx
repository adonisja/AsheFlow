/**
 * Field packages — oversight and manual assignment (ADR-246).
 *
 * Two jobs on one page, because they are the same conversation:
 *
 *   Added today   what walkers put on routes, and who added it
 *   Assign        place a package dispatch was told about by radio
 *
 * ### Why this page exists at all
 *
 * `write_audit` records every field-added package, but `GET /audit` is gated
 * management+admin — **dispatch cannot read it**. Pointing oversight at the
 * audit log would satisfy the requirement on paper and not in practice, so the
 * backend exposes the same rows under a dispatch-readable gate, shaped as a
 * day's feed rather than an event stream.
 *
 * Oversight is visibility, not a gate: a walker's self-add has already
 * committed by the time it appears here. A review queue would either block a
 * delivery that costs nothing or be rubber-stamped.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  PackagePlus, Inbox, AlertTriangle, CheckCircle2, MapPinOff, HelpCircle,
  ScanLine,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import { SkeletonCard } from '../components/ui/Skeleton';
import type {
  FieldAddedResponse, FieldAddedPackage, PackageIntakeResponse,
  LabelReadResponse,
} from '../api/types';

type Tab = 'feed' | 'assign';

function todayISO(): string {
  // Local date, not UTC — a UTC date rolls the feed over mid-evening for US
  // operators and hides the packages added at the end of the shift.
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** One sentence per outcome, phrased for a dispatcher rather than a walker. */
function outcomeSummary(r: PackageIntakeResponse): { tone: 'ok' | 'warn' | 'bad' | 'info'; text: string } {
  switch (r.outcome) {
    case 'added':
      return {
        tone: 'ok',
        text: `Added to Route ${r.route_number ?? '—'}${r.walker_name ? ` (${r.walker_name})` : ''}.`
          + (r.reason?.startsWith('best_fit_in_progress')
            ? ' The closest route had already departed, so it was absorbed into one that could still take it.'
            : ''),
      };
    case 'duplicate':
      return {
        tone: 'warn',
        text: r.existing_holder
          ? `Already registered to ${r.existing_holder}${r.existing_route_number ? ` on Route ${r.existing_route_number}` : ''}. Nothing was changed.`
          : 'Already registered on a route. Nothing was changed.',
      };
    case 'removal':
      return {
        tone: 'bad',
        text: 'Outside the company zone — logged as a removal for return to the station.',
      };
    default:
      return {
        tone: 'info',
        text: r.reason === 'no_coords' || r.reason === 'no_boundary'
          ? 'Address could not be placed. Correct it and try again, or create a removal.'
          : 'No route can take this right now.',
      };
  }
}

export default function FieldPackages() {
  const [tab, setTab] = useState<Tab>('feed');

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm w-fit">
        {([['feed', 'Added today'], ['assign', 'Assign a package']] as [Tab, string][]).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
              tab === k
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'feed' ? <AddedFeed /> : <AssignForm />}
    </div>
  );
}

function AddedFeed() {
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState<FieldAddedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<FieldAddedResponse>(
        '/packages/intake/field-added', { params: { route_date: d } },
      );
      setData(res.data);
    } catch {
      setError('Could not load field-added packages.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(date); }, [date, load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label htmlFor="feed-date" className="text-sm text-muted-foreground">Date</label>
        <input
          id="feed-date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="border border-border rounded-lg px-3 py-1.5 bg-background text-sm"
        />
        {data && (
          <span className="text-sm text-muted-foreground">
            {data.total} package{data.total === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {error && <ErrorBanner message={error} />}
      {loading && <SkeletonCard />}

      {!loading && data && data.packages.length === 0 && (
        <div className="border border-border rounded-xl p-8 text-center text-muted-foreground">
          <Inbox className="w-6 h-6 mx-auto mb-2 opacity-60" />
          <p className="text-sm">No packages were added from the field on this date.</p>
        </div>
      )}

      {!loading && data && data.packages.length > 0 && (
        <div className="border border-border rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-accent/50 text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-4 py-2">TBA</th>
                <th className="text-left font-medium px-4 py-2">Route</th>
                <th className="text-left font-medium px-4 py-2">Walker</th>
                <th className="text-left font-medium px-4 py-2">Added by</th>
                <th className="text-left font-medium px-4 py-2">Time</th>
                <th className="text-left font-medium px-4 py-2">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {data.packages.map((p: FieldAddedPackage, i) => (
                <tr key={`${p.tba}-${i}`} className="border-t border-border">
                  <td className="px-4 py-2 font-mono text-xs">{p.tba}</td>
                  <td className="px-4 py-2">{p.route_number ?? '—'}</td>
                  <td className="px-4 py-2">{p.walker_name ?? '—'}</td>
                  <td className="px-4 py-2">{p.added_by_name ?? '—'}</td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {new Date(p.added_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </td>
                  <td className="px-4 py-2">
                    <OutcomePill outcome={p.outcome} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OutcomePill({ outcome }: { outcome: string }) {
  const map: Record<string, { cls: string; icon: React.ReactNode; label: string }> = {
    added: {
      cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
      icon: <CheckCircle2 className="w-3 h-3" />, label: 'Added',
    },
    removal: {
      cls: 'bg-red-500/10 text-red-600 dark:text-red-400',
      icon: <MapPinOff className="w-3 h-3" />, label: 'Out of zone',
    },
    duplicate: {
      cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
      icon: <AlertTriangle className="w-3 h-3" />, label: 'Duplicate',
    },
  };
  const m = map[outcome] ?? {
    cls: 'bg-sky-500/10 text-sky-600 dark:text-sky-400',
    icon: <HelpCircle className="w-3 h-3" />, label: outcome,
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.cls}`}>
      {m.icon}{m.label}
    </span>
  );
}

function AssignForm() {
  const [tba, setTba] = useState('');
  const [address, setAddress] = useState('');
  const [blockKey, setBlockKey] = useState('');
  const [routeId, setRouteId] = useState('');
  const [result, setResult] = useState<PackageIntakeResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [ocrLines, setOcrLines] = useState<string[]>([]);

  // Object URLs leak until revoked; drop the previous one whenever it changes
  // and on unmount.
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  /**
   * OCR assists the form; it never replaces it. Both fields stay editable and a
   * failed read leaves what was already typed alone — the walker/dispatcher is
   * looking at the label either way (ADR-246).
   */
  const scanLabel = useCallback(async (f: File) => {
    setScanning(true);
    setScanNote(null);
    setOcrLines([]);
    setPreview(prev => {
      if (prev) URL.revokeObjectURL(prev);
      return f.type.startsWith('image/') ? URL.createObjectURL(f) : null;
    });
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await axiosClient.post<LabelReadResponse>(
        '/packages/intake/read-label', fd,
      );
      const r = res.data;
      if (r.tba) setTba(r.tba);
      if (r.address_line) setAddress(r.address_line);
      // Every line OCR read, so a wrong pick is fixed by clicking the right one
      // rather than re-scanning (and re-billing Textract).
      setOcrLines(r.lines ?? []);

      if (r.needs_manual_entry) {
        setScanNote('Could not read the whole label — fill in the rest by hand.');
      } else if (r.confidence !== null && r.confidence < 0.85) {
        // A confident-looking wrong read is the failure that matters, so a
        // shaky score asks for eyes rather than staying silent.
        setScanNote('Low-confidence read — check both fields before assigning.');
      } else {
        setScanNote('Read from the label. Check it before assigning.');
      }
    } catch {
      setScanNote('Scan unavailable — enter the details by hand.');
    } finally {
      setScanning(false);
    }
  }, []);

  const submit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await axiosClient.post<PackageIntakeResponse>('/packages/intake/assign', {
        tba: tba.trim().toUpperCase(),
        normalised_address: address.trim() || null,
        block_key: blockKey.trim() || null,
        route_id: routeId.trim() || null,
      });
      setResult(res.data);
    } catch {
      setError('Could not assign this package.');
    } finally {
      setBusy(false);
    }
  }, [tba, address, blockKey, routeId]);

  const summary = result ? outcomeSummary(result) : null;
  const toneCls = summary && {
    ok: 'border-emerald-500/40 bg-emerald-500/5',
    warn: 'border-amber-500/40 bg-amber-500/5',
    bad: 'border-red-500/40 bg-red-500/5',
    info: 'border-sky-500/40 bg-sky-500/5',
  }[summary.tone];

  return (
    <form onSubmit={submit} className="max-w-xl space-y-4">
      <p className="text-sm text-muted-foreground">
        For a package a walker reported by radio, or one that came back from the
        field without an address we could place. Leave the route blank to let the
        system pick the best fit.
      </p>

      {/* Drop / paste / browse. Dispatch usually has the label as a photo a
          walker messaged them, so paste-from-clipboard is the fastest path and
          drag-and-drop is the next; the file picker is the fallback, not the
          headline. Manual entry below always works regardless (ADR-246). */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) void scanLabel(f);
        }}
        onPaste={(e) => {
          const f = Array.from(e.clipboardData.files)[0];
          if (f) void scanLabel(f);
        }}
        // Focusable so a paste lands here without the user clicking a field
        // first — the browser only delivers clipboard events to focused nodes.
        tabIndex={0}
        className={`rounded-xl border-2 border-dashed p-4 transition-colors outline-none
          focus-visible:ring-2 focus-visible:ring-primary/40 ${
          dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40'
        }`}
      >
        <div className="flex items-center gap-3">
          {preview ? (
            <img
              src={preview}
              alt=""
              className="w-14 h-14 rounded-lg object-cover border border-border shrink-0"
            />
          ) : (
            <ScanLine className="w-6 h-6 text-muted-foreground shrink-0" />
          )}

          <div className="min-w-0 flex-1">
            <p className="text-sm">
              {scanning ? 'Reading the label…' : 'Drop or paste a label image'}
            </p>
            <label className="text-xs text-primary hover:underline cursor-pointer">
              or choose a file
              <input
                type="file"
                accept="image/jpeg,image/png,application/pdf"
                capture="environment"
                className="hidden"
                disabled={scanning}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void scanLabel(f);
                  e.target.value = '';   // so the same photo can be retried
                }}
              />
            </label>
            {scanNote && (
              <p className="text-xs text-muted-foreground mt-1">{scanNote}</p>
            )}
          </div>
        </div>

        {/* Every line OCR read. A misassigned field is fixed by clicking the
            right line rather than re-scanning — which would re-bill Textract
            and, on a creased label, probably misread it the same way again. */}
        {ocrLines.length > 0 && (
          <div className="mt-3 pt-3 border-t border-border">
            <p className="text-xs text-muted-foreground mb-1.5">
              Read from the label — click a line to use it:
            </p>
            <div className="flex flex-wrap gap-1.5">
              {ocrLines.map((line, i) => (
                <span key={`${line}-${i}`} className="inline-flex items-center rounded-md border border-border overflow-hidden text-xs">
                  <span className="px-2 py-1 font-mono truncate max-w-[16rem]">{line}</span>
                  <button
                    type="button"
                    onClick={() => setTba(line.replace(/\s+/g, '').toUpperCase())}
                    className="px-1.5 py-1 border-l border-border hover:bg-accent"
                    title="Use as tracking number"
                  >
                    TBA
                  </button>
                  <button
                    type="button"
                    onClick={() => setAddress(line)}
                    className="px-1.5 py-1 border-l border-border hover:bg-accent"
                    title="Use as address"
                  >
                    Addr
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <Field label="Tracking number (TBA)" required>
        <input
          value={tba}
          onChange={(e) => setTba(e.target.value)}
          placeholder="TBA303912345447"
          className="w-full border border-border rounded-lg px-3 py-2 bg-background font-mono text-sm"
          minLength={4}
          required
        />
      </Field>

      <Field label="Address on the label">
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="1 Main St"
          className="w-full border border-border rounded-lg px-3 py-2 bg-background text-sm"
        />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Block key">
          <input
            value={blockKey}
            onChange={(e) => setBlockKey(e.target.value)}
            placeholder="optional"
            className="w-full border border-border rounded-lg px-3 py-2 bg-background text-sm"
          />
        </Field>
        <Field label="Route ID">
          <input
            value={routeId}
            onChange={(e) => setRouteId(e.target.value)}
            placeholder="best fit if blank"
            className="w-full border border-border rounded-lg px-3 py-2 bg-background font-mono text-xs"
          />
        </Field>
      </div>

      {error && <ErrorBanner message={error} />}

      <button
        type="submit"
        disabled={busy || tba.trim().length < 4}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
      >
        <PackagePlus className="w-4 h-4" />
        {busy ? 'Assigning…' : 'Assign package'}
      </button>

      {result && summary && (
        <div className={`border rounded-xl p-4 text-sm ${toneCls}`}>
          <p className="font-mono text-xs text-muted-foreground mb-1">{result.tba}</p>
          <p>{summary.text}</p>
        </div>
      )}
    </form>
  );
}

function Field({
  label, required, children,
}: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">
        {label}{required && <span className="text-red-500"> *</span>}
      </span>
      {children}
    </label>
  );
}
