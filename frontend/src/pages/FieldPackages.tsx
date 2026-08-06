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
  ScanLine, ChevronDown, ChevronRight,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import { PackageLookupPanel } from './PackageLookup';
import { SkeletonCard } from '../components/ui/Skeleton';
import type {
  FieldAddedResponse, FieldAddedPackage, PackageIntakeResponse,
  LabelReadResponse,
} from '../api/types';

type Tab = 'feed' | 'assign' | 'lookup';

/**
 * Re-encode an image the server cannot read into a JPEG it can.
 *
 * iPhones shoot HEIC by default, and neither Textract nor the endpoint's
 * allowlist accepts it. Before this, picking one off a Mac or an iPhone meant
 * the file greyed out in the picker with no explanation — the worst of the
 * possible failures, because nothing told the user what was wrong.
 *
 * Converted in the BROWSER rather than on the server: server-side would mean
 * adding pillow + pillow-heif and a native libheif to the image for one format,
 * on a path that already works everywhere else. Here it costs one decode
 * attempt and no dependency at all.
 *
 * Decoding depends on the OS codec: Safari and Chrome-on-macOS manage it,
 * Chrome-on-Linux generally does not. A failure is therefore expected, not
 * exceptional — the caller reports it in words and manual entry always
 * remains (ADR-246).
 *
 * It also DOWNSCALES. The first version returned any server-readable type
 * untouched, which meant a 12 MP phone JPEG went up at full size and came back
 * 413 — the format was never the only problem. Every image is now capped at
 * MAX_EDGE, matching what mobile has always done on capture.
 */
/** Longest edge sent to the server. Mobile already uses 2000 via
 *  react-native-image-picker, for the same reason: a label only needs enough
 *  pixels for OCR to resolve the text, and a 12 MP phone photo is mostly
 *  packaging. Matching that number keeps the two platforms comparable. */
const MAX_EDGE = 2000;
const SERVER_READABLE = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf'];

async function toServerReadableImage(file: File): Promise<File> {
  // PDFs cannot be canvas-processed and are already server-readable.
  if (file.type === 'application/pdf') return file;

  // An IMAGE always goes through, even a JPEG. The first version returned any
  // server-readable type untouched, so a 12 MP phone photo was uploaded at full
  // size and the endpoint rejected it with 413 — the format was never the only
  // problem, the SIZE was.
  const bitmap = await createImageBitmap(file);   // throws if the OS cannot decode

  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();

  const blob: Blob = await new Promise((resolve, reject) => {
    // 0.85 rather than 0.9: measured, a 2000px label at 0.9 still ran to
    // several MB, and the text stays legible at 0.85. The cap is 10 MB and a
    // downscaled label lands around 0.3-0.8 MB.
    canvas.toBlob(b => (b ? resolve(b) : reject(new Error('encode failed'))),
                  'image/jpeg', 0.85);
  });

  return new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg',
                  { type: 'image/jpeg' });
}

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
        {([['feed', 'Added today'], ['assign', 'Assign a package'], ['lookup', 'Find a package']] as [Tab, string][]).map(([k, label]) => (
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

      {tab === 'feed' ? <AddedFeed />
        : tab === 'assign' ? <AssignForm />
        : <PackageLookupPanel />}
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
      // HEIC and friends are re-encoded here; JPEG/PNG passes through
      // untouched. A decode failure is reported in words rather than
      // surfacing as a raw 415 from the server.
      let upload: File;
      try {
        upload = await toServerReadableImage(f);
      } catch {
        setScanNote(
          `This browser cannot read ${f.type || 'that format'}. ` +
          'Save the photo as JPEG or PNG, or enter the details by hand.',
        );
        return;   // `finally` still reveals the manual fields
      }
      
      const fd = new FormData();
      fd.append('file', upload);
      const res = await axiosClient.post<LabelReadResponse>(
        '/packages/intake/read-label', fd,
        // `undefined`, not 'multipart/form-data': axiosClient defaults every
        // request to application/json, and FastAPI then cannot parse the body
        // — the upload 422'd before reaching the handler's own checks.
        // Setting the type by hand is just as wrong, because multipart needs a
        // generated BOUNDARY; only the browser can supply it, and it does so
        // exactly when the header is absent.
        { headers: { 'Content-Type': undefined } },
      );
      const r = res.data;
      if (r.tba) setTba(r.tba);
      if (r.address_line) setAddress(r.address_line);
      // Every line OCR read, so a wrong pick is fixed by clicking the right one
      // rather than re-scanning (and re-billing Textract).
      setOcrLines(r.lines ?? []);

      // `warnings` distinguishes three outcomes that all set
      // needs_manual_entry, and the UI used to flatten them into one
      // message — so "the OCR service is down" and "OCR read your label
      // but found no tracking number" were indistinguishable.
      if (r.warnings?.includes('ocr_unavailable')) {
        setScanNote('Label reading is unavailable right now — enter the details by hand.');
      } else if (r.needs_manual_entry) {
        const missing = [
          r.warnings?.includes('no_tba_found') ? 'tracking number' : null,
          r.warnings?.includes('no_address_found') ? 'address' : null,
        ].filter(Boolean).join(' or ');
        setScanNote(
          missing
            ? `Could not find the ${missing} on this label — check the lines below or type it in.`
            : 'Could not read the whole label — fill in the rest by hand.',
        );
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
      // In `finally`, not the try: a scan that FAILS is precisely when the
      // fields are needed, and the catch branch already says "enter the
      // details by hand" — telling someone to type into inputs that are
      // still collapsed is worse than not offering the scan at all.
      setManualOpen(true);
    }
  }, []);

  /* Ranked candidates from the dry run. `assessment.candidates` is ordered by
     match strength (address > block_key > none) and each carries `status` and
     `can_accept`, so a dispatcher can see that a nearby route is COMPLETED and
     therefore not an option — rather than only being shown the one best fit.

     NOTE: `match` is block/stop proximity, not a distance. The picker is
     ordered by match strength; calling that "nearest" would overstate it. */
  /* The scanner is the primary path; the typed fields are the fallback for a
     radio call or a failed read. They start COLLAPSED so the scan drop-zone is
     not competing with four inputs for attention — but they open automatically
     the moment a scan populates them, because a read the dispatcher cannot see
     is worse than no read at all. */
  const [manualOpen, setManualOpen] = useState(false);
  const [routePreview, setRoutePreview] = useState<PackageIntakeResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const runPreview = useCallback(async () => {
    if (!tba.trim()) return;
    setPreviewing(true);
    setError(null);
    try {
      const res = await axiosClient.post<PackageIntakeResponse>(
        '/packages/intake/assign/preview', {
          tba: tba.trim().toUpperCase(),
          normalised_address: address.trim() || null,
          block_key: blockKey.trim() || null,
          route_id: null,          // ask what the system WOULD pick
        });
      setRoutePreview(res.data);
      // Adopt the suggestion only if the dispatcher has not already chosen.
      if (!routeId && res.data.route_id) setRouteId(res.data.route_id);
    } catch {
      // A failed preview must not block assigning by hand.
      setRoutePreview(null);
    } finally {
      setPreviewing(false);
    }
  }, [tba, address, blockKey, routeId]);

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
            {/* `htmlFor` + a SIBLING input, not a nested one. With the input inside
                the label, a click is forwarded to the input, bubbles back up through
                the label, and is forwarded again — opening the file chooser several
                times per click (observed: 5 stacked choosers from one interaction).
                An id/for pair means the label never contains its own target, so the
                forwarded click cannot re-enter it. */}
            <label
              htmlFor="label-file-input"
              className="text-xs text-primary hover:underline cursor-pointer"
            >
              or choose a file
            </label>
            <input
              id="label-file-input"
              type="file"
              // `image/*` so a HEIC is SELECTABLE — it greyed out with no explanation
                // before, which gives the user nothing to act on. Conversion happens
                // in scanLabel, and an unsupported file gets a sentence saying so.
                accept="image/*,application/pdf"
              capture="environment"
              className="hidden"
              disabled={scanning}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void scanLabel(f);
                e.target.value = '';   // so the same photo can be retried
              }}
            />
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

        {/* Manual entry — collapsed by default so the scanner reads as THE way
            in. Opens on request, and automatically once a scan has written into
            these fields (see setManualOpen in the scan handler). */}
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setManualOpen((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-brandText"
            aria-expanded={manualOpen}
          >
            {manualOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            {manualOpen ? "Hide manual entry" : "Enter the details by hand"}
          </button>

          {manualOpen && (
            <div className="space-y-4">
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
        </div>
            </div>
          )}
        </div>

      {/* Route: suggested first, then chosen from the ranked candidates. This
          was a raw "Route ID" text box asking for a UUID — nobody knows a route
          by its UUID, and the ranking, each route's status, and whether it can
          still accept work were all on the wire already and never shown.

          `can_accept: false` routes are RENDERED, disabled, with the reason.
          Hiding them would leave a dispatcher wondering why the obvious nearby
          route is missing.

          `match` is block/stop proximity, not a distance — the label says
          "address match" / "block match" rather than implying metres. */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Route</span>
          <button
            type="button"
            onClick={runPreview}
            disabled={previewing || tba.trim().length < 4}
            className="text-xs font-medium text-brandText disabled:opacity-50"
          >
            {previewing ? 'Checking…' : 'Suggest a route'}
          </button>
        </div>

        {!routePreview && (
          <p className="text-xs text-muted-foreground">
            Leave unset to let the system pick the best fit, or use
            <span className="text-foreground"> Suggest a route</span> to see the options first.
          </p>
        )}

        {routePreview?.assessment?.candidates?.length ? (
          <ul className="space-y-1.5">
            {routePreview.assessment.candidates.map((c) => {
              const chosen = routeId === c.route_id;
              const isBest = c.route_id === routePreview.assessment?.best_fit?.route_id;
              return (
                <li key={c.route_id}>
                  <button
                    type="button"
                    disabled={!c.can_accept}
                    onClick={() => setRouteId(chosen ? '' : c.route_id)}
                    className={`w-full text-left rounded-lg border px-3 py-2 text-sm transition-colors ${
                      chosen ? 'border-brandText bg-brandText/5' : 'border-border hover:bg-accent'
                    } ${c.can_accept ? '' : 'opacity-60 cursor-not-allowed'}`}
                  >
                    <span className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">Route {c.route_number ?? '—'}</span>
                      <span className="text-muted-foreground">{c.walker_name ?? 'unassigned'}</span>
                      {isBest && (
                        <span className="text-[11px] font-medium px-1.5 py-0.5 rounded-full text-success bg-success/10">
                          Best fit
                        </span>
                      )}
                      <span className="text-[11px] px-1.5 py-0.5 rounded-full text-muted-foreground bg-muted-foreground/10">
                        {c.match === 'address' ? 'address match' : c.match === 'block_key' ? 'block match' : 'no match'}
                      </span>
                      <span className={`text-[11px] px-1.5 py-0.5 rounded-full ml-auto ${
                        c.can_accept ? 'text-info bg-info/10' : 'text-warning bg-warning/10'
                      }`}>
                        {c.status ?? 'unknown'}{c.can_accept ? '' : ' · cannot accept'}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : routePreview ? (
          /* Two different situations reach zero candidates, and telling them
             apart is the whole value of showing anything here:

               decidable=false  we could not LOCATE the address — the address
                                is the problem, not the routes
               decidable=true   located fine, but no route can accept it

             Saying "no route can take this" for the first would send a
             dispatcher to check routes when they need to fix the address. */
          <p className="text-xs text-warning">
            {routePreview.assessment?.decidable === false
              ? routePreview.assessment?.zone_reason === 'no_coords'
                ? 'Could not place this address — check it, or assign the route by hand.'
                : routePreview.assessment?.zone_reason === 'outside'
                  ? 'This address is outside the delivery zone — it will escalate to dispatch review.'
                  : 'Not enough information to place this package — it will escalate to dispatch review.'
              : 'No route can take this package — assigning will escalate it to dispatch review.'}
          </p>
        ) : null}
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="space-y-1.5">
        <button
          type="submit"
          disabled={busy || tba.trim().length < 4}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
        >
          <PackagePlus className="w-4 h-4" />
          {busy ? 'Assigning…' : 'Assign package'}
        </button>

        {/* Say WHY the button is dead. Collapsing manual entry made this
            necessary: the TBA requirement is real, but with the field hidden
            the only signal was a greyed-out button and no explanation. */}
        {tba.trim().length < 4 && (
          <p className="text-xs text-muted-foreground">
            Scan a label, or{' '}
            <button
              type="button"
              onClick={() => setManualOpen(true)}
              className="text-brandText font-medium underline underline-offset-2"
            >
              enter a tracking number
            </button>
            {' '}to continue.
          </p>
        )}
      </div>

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
