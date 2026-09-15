import { useCallback, useRef, useState } from 'react';
import { Camera, Loader2, X, Check, AlertTriangle } from 'lucide-react';
import { parseLabelLines, readScore, type LabelRead } from '../../utils/labelParse';
import CropDialog from './CropDialog';

/** Reads a package label with the phone camera: barcode for the TBA, OCR for
 *  everything printed.
 *
 *  TWO ENGINES, BECAUSE THE LABEL HAS TWO KINDS OF DATA (ADR-399 D1):
 *
 *    barcode → the TBA, read on-device from the Code 128 symbol. Verified on a
 *              real label 2026-09-09: the payload is the bare TBA, unencrypted
 *              and checksummed, so a successful read needs no confirmation.
 *    OCR     → everything the symbols do NOT carry — above all the delivery
 *              address. ADR-404 established that no machine-readable mark on
 *              the label encodes a destination; it did not establish that the
 *              printed address is unreadable, and the backend's own
 *              `label_ingestor` extracts one today.
 *
 *  Both run against the SAME captured image, so one photo yields both fields.
 *  Everything is a suggestion the user accepts or discards — a creased label in
 *  a dim van is exactly where a misread becomes a delivery to the wrong street.
 *
 *  ENTIRELY ON-DEVICE. BarcodeDetector is a browser API; Tesseract runs as a
 *  worker in the page. No upload, no API call, no key — which is what keeps this
 *  tracker unauthenticated and local-only. Tesseract's ~2MB model is fetched
 *  lazily on first OCR, so the page does not pay for it unless used.
 */

type Phase = 'idle' | 'reading' | 'done' | 'error';

interface BarcodeDetectorLike {
  detect(src: ImageBitmapSource): Promise<{ rawValue: string; format: string }[]>;
}
interface BarcodeCtor { new (opts?: { formats?: string[] }): BarcodeDetectorLike }

const barcodeSupported = (): boolean =>
  typeof window !== 'undefined' && 'BarcodeDetector' in window;

/** Reads any 1D/2D symbol on the image. Returns the first TBA-shaped payload —
 *  the label also carries a QR code with the same value, so either will do. */
async function readBarcode(blob: Blob): Promise<string | null> {
  if (!barcodeSupported()) return null;
  try {
    const Ctor = (window as unknown as { BarcodeDetector: BarcodeCtor }).BarcodeDetector;
    const det = new Ctor({ formats: ['code_128', 'qr_code', 'code_39', 'itf'] });
    const bmp = await createImageBitmap(blob);
    const found = await det.detect(bmp);
    bmp.close?.();
    for (const f of found) {
      const v = f.rawValue.replace(/\s+/g, '').toUpperCase();
      if (/^TB[AMC]\d{12,15}$/.test(v) || /^GBA\d{12,15}$/.test(v)) return v;
    }
    return found[0]?.rawValue.trim() || null;
  } catch {
    return null;                     // unsupported format or a decode failure
  }
}

export default function LabelScanner({ onAccept, compact, label }: {
  /** Called with whatever the user confirmed. Either field may be null — a
   *  label that only yielded a TBA is still worth accepting. */
  onAccept: (r: { tba: string | null; address: string | null }) => void;
  compact?: boolean;
  /** Trigger text. Defaults to "Scan label"; a caller that only wants the
   *  address half should say so, since "Scan label" beside an address list
   *  reads as though it will replace the list. */
  label?: string;
}) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [progress, setProgress] = useState('');
  const [read, setRead] = useState<LabelRead | null>(null);
  const [barcodeTba, setBarcodeTba] = useState<string | null>(null);
  /** EDITABLE drafts, seeded from the read and corrected in place.
   *
   *  An OCR suggestion you can only accept or discard is barely a suggestion:
   *  a single misread character ("1SOO BROADWAY") forced a full retype, which
   *  is exactly the work scanning was meant to remove. The scan's job is to get
   *  you 95% of the way there; the last character is a keystroke, not a
   *  restart. */
  const [tbaDraft, setTbaDraft] = useState('');
  const [addressDraft, setAddressDraft] = useState('');
  const [error, setError] = useState('');
  /** The captured photo, held while the user frames the label. OCR does not
   *  start until they confirm the crop. */
  const [pending, setPending] = useState<Blob | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  /** OCR a CROPPED image. One pass, no rotation sweep: the crop dialog already
   *  framed and oriented the label, and a four-rotation sweep cost ~8.7s on a
   *  laptop — 30-40s on a phone. */
  const handle = useCallback(async (cropped: Blob) => {
    setPending(null);
    setPhase('reading'); setError(''); setRead(null); setBarcodeTba(null);
    try {
      // Barcode first: fast, offline, and checksummed, so a hit means OCR only
      // has to supply the address.
      setProgress('Looking for a barcode…');
      const bc = await readBarcode(cropped);
      setBarcodeTba(bc);

      setProgress('Reading the label…');
      const { default: Tesseract } = await import('tesseract.js');
      const r = await Tesseract.recognize(cropped, 'eng', {
        logger: (m: { status: string; progress: number }) => {
          if (m.status === 'recognizing text') {
            setProgress(`Reading the label… ${Math.round(m.progress * 100)}%`);
          }
        },
        // SELF-HOSTED — the field has no internet. See scripts/vendor-tesseract.sh.
        workerPath: '/tesseract/worker.min.js',
        corePath: '/tesseract/',
        langPath: '/tesseract/',
        gzip: true,
      } as Parameters<typeof Tesseract.recognize>[2]);

      type TL = { text: string; confidence: number };
      const lines: TL[] = (r.data as unknown as { lines?: TL[] }).lines
        ?? r.data.text.split('\n').map((t) => ({ text: t, confidence: r.data.confidence ?? 0 }));
      const parsed = parseLabelLines(
        lines.map((l) => [l.text.trim(), l.confidence] as [string, number]).filter(([t]) => t.length > 0),
      );
      // A barcode read beats OCR for the TBA every time: it is checksummed.
      if (bc && /^TB[AMC]\d{12,15}$/.test(bc)) parsed.tba = bc;

      setRead(parsed);
      setTbaDraft(parsed.tba ?? '');
      setAddressDraft(parsed.addressLine ?? '');
      setPhase('done');
    } catch {
      setError('Could not read that image. Try a tighter crop, or type it in.');
      setPhase('error');
    }
  }, []);

  const reset = () => {
    setPhase('idle'); setRead(null); setBarcodeTba(null);
    setTbaDraft(''); setAddressDraft(''); setError('');
  };

  return (
    <div className="min-w-0 space-y-2">
      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        disabled={phase === 'reading'}
        className={`inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs hover:border-primary/60 hover:bg-muted disabled:opacity-50 ${compact ? '' : 'w-full justify-center'}`}
      >
        {phase === 'reading'
          ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> {progress || 'Reading…'}</>
          : <><Camera className="w-3.5 h-3.5" /> {label ?? 'Scan label'}</>}
      </button>

      {/* `capture="environment"` opens the rear camera on a phone and a file
          picker on desktop — the pattern FieldOps and Incidents already use. */}
      <input
        ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          // Straight to the cropper — OCR waits until the label is framed.
          if (f) setPending(f);
          if (fileRef.current) fileRef.current.value = '';
        }}
      />

      {pending && (
        <CropDialog
          file={pending}
          onCancel={() => setPending(null)}
          onCrop={(b) => void handle(b)}
        />
      )}

      {error && (
        <p className="text-[11px] text-danger">{error}</p>
      )}

      {/* A LAN IP over plain http is not a secure context, and the browser then
          removes BarcodeDetector entirely — measured: the API is simply absent
          on http://192.168.x. OCR still runs, so without this line the barcode
          half fails INVISIBLY and reads as a broken scanner rather than a page
          served over the wrong protocol. */}
      {!barcodeSupported() && (
        <p className="text-[11px] text-warning">
          {window.isSecureContext
            ? 'Barcode reading unavailable in this browser. Using OCR only.'
            : 'Barcode reading needs HTTPS (this page is on http). Using OCR only.'}
        </p>
      )}

      {phase === 'done' && read && (
        <div className="min-w-0 rounded-lg border border-border p-2.5 space-y-2 text-xs">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold uppercase tracking-wide text-[10px] text-muted-foreground">
              Found on label
            </span>
            <button type="button" onClick={reset} className="text-muted-foreground hover:text-foreground">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Both fields are EDITABLE, not a read-only preview. A field the OCR
              missed entirely is typed here rather than after discarding, so a
              partial read is still worth keeping. */}
          <div className="space-y-1.5">
            <label className="flex min-w-0 items-center gap-2">
              <span className="w-14 shrink-0 text-muted-foreground">TBA</span>
              <input
                value={tbaDraft}
                onChange={(e) => setTbaDraft(e.target.value)}
                placeholder="not found, type it"
                className="min-w-0 flex-1 rounded border border-border bg-surface px-2 py-1 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
              {/* Marks a checksummed read, so an edit here is visibly a
                  departure from something trustworthy (ADR-399 D2). */}
              {barcodeTba && tbaDraft === barcodeTba && (
                <span className="shrink-0 rounded bg-success/15 px-1.5 py-0.5 text-[10px] font-medium text-success">
                  barcode
                </span>
              )}
            </label>

            <label className="flex min-w-0 items-center gap-2">
              <span className="w-14 shrink-0 text-muted-foreground">Address</span>
              <input
                value={addressDraft}
                onChange={(e) => setAddressDraft(e.target.value)}
                placeholder="not found, type it"
                className="min-w-0 flex-1 rounded border border-border bg-surface px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </label>

            {/* Restores the raw read after an edit — a correction that made
                things worse should not mean re-photographing the box. */}
            {(tbaDraft !== (read.tba ?? '') || addressDraft !== (read.addressLine ?? '')) && (
              <button
                type="button"
                onClick={() => { setTbaDraft(read.tba ?? ''); setAddressDraft(read.addressLine ?? ''); }}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                edited · revert to scan
              </button>
            )}
          </div>

          {/* More than one street-looking line means the return address was also
              read. The backend records the same warning and defers to a human. */}
          {read.addressCandidates.length > 1 && (
            <div className="space-y-1">
              <p className="flex items-start gap-1 text-[11px] text-warning">
                <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" /> More than one address. Pick one
              </p>
              {/* Capped and scrollable for the same reason: a poor read can
                  produce a dozen street-looking lines. */}
              {read.addressCandidates.slice(0, 8).map((a) => (
                <button
                  key={a} type="button" onClick={() => setAddressDraft(a)}
                  className={`block w-full break-words rounded border px-2 py-1 text-left ${
                    addressDraft === a ? 'border-primary/50 bg-primary/5' : 'border-border hover:bg-muted'
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
          )}

          {/* Nothing recognisable came back. Says so plainly rather than
              presenting an empty panel that looks like a bug. */}
          {readScore(read) === 0 && (
            <p className="flex items-start gap-1 text-[11px] text-warning">
              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
              Nothing readable found. Crop tighter around the label, or type it in.
            </p>
          )}

          {read.confidence !== null && read.confidence < 0.8 && (
            <p className="flex items-start gap-1 text-[11px] text-warning">
              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
              Low confidence ({Math.round(read.confidence * 100)}%). Check it before accepting
            </p>
          )}

          <div className="flex gap-2 pt-0.5">
            <button
              type="button"
              onClick={() => {
                onAccept({ tba: tbaDraft.trim() || null, address: addressDraft.trim() || null });
                reset();
              }}
              disabled={!tbaDraft.trim() && !addressDraft.trim()}
              className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground hover:brightness-110 disabled:opacity-40"
            >
              <Check className="w-3 h-3" /> Use this
            </button>
            <button
              type="button" onClick={reset}
              className="rounded-md border border-border px-2.5 py-1 text-[11px] hover:bg-muted"
            >
              Discard
            </button>
          </div>

          {/* Every line read, so "none of these" never means re-scanning. */}
          <details className="text-[11px] text-muted-foreground">
            <summary className="cursor-pointer">All {read.lines.length} lines read</summary>
            {/* Tap a line to use it as the address. OCR sometimes reads the
                street correctly but on a line the street-regex rejected (a unit
                number first, say), and the text is right there.

                SCROLLS inside a fixed height rather than expanding the panel.
                On a real scan this was 31 lines of OCR noise that pushed the
                form — and the field being typed into — off the screen. */}
            <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto font-mono">
              {read.lines.map((l, i) => (
                <li key={i}>
                  <button
                    type="button" onClick={() => setAddressDraft(l)}
                    className="w-full break-words rounded px-1 text-left hover:bg-muted"
                  >
                    {l}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </div>
  );
}
