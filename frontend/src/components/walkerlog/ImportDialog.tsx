import { useCallback, useRef, useState } from 'react';
import { FileSpreadsheet, Camera, Loader2, X, Check, AlertTriangle, Users } from 'lucide-react';
import { parseWorkbook, type ParsedSheet } from '../../utils/workbookImport';
import { parseCrewLines, type CrewCandidate } from '../../utils/crewParse';
import CropDialog from './CropDialog';

/** Brings a day's data in: the load-sheet workbook, and the crew screenshot.
 *
 *  Two importers in one dialog because they are two halves of the same setup —
 *  the workbook says what the truck is carrying, the screenshot says who is
 *  carrying it, and both arrive on the same morning for the same date.
 *
 *  Both CONFIRM before writing. The workbook shows what each sheet parsed to
 *  and any self-inconsistency; the screenshot shows every name as an editable,
 *  tickable row. Nothing is seeded from a read nobody looked at.
 */

type Tab = 'sheet' | 'crew';

export default function ImportDialog({ date, initialTab = 'sheet', onClose, onImportSheets, onImportCrew }: {
  date: string;
  /** Which importer to land on — the caller's button decides. */
  initialTab?: Tab;
  onClose: () => void;
  onImportSheets: (sheets: ParsedSheet[]) => Promise<void>;
  onImportCrew: (names: string[]) => Promise<void>;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [sheets, setSheets] = useState<ParsedSheet[] | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [crew, setCrew] = useState<CrewCandidate[] | null>(null);
  const [pendingShot, setPendingShot] = useState<Blob | null>(null);
  const xlsxRef = useRef<HTMLInputElement>(null);
  const shotRef = useRef<HTMLInputElement>(null);

  const readWorkbook = useCallback(async (f: File) => {
    setBusy('Reading the workbook…'); setError(''); setSheets(null);
    try {
      const r = await parseWorkbook(f);
      if (r.sheets.length === 0) {
        setError('No truck sheets found in that file. Is it the dispatch load sheet?');
      } else {
        setSheets(r.sheets);
        setSkipped(r.skipped);
        // Everything ticked: a workbook is the day's whole fleet, and importing
        // all of it costs nothing — you pick which BTR to WORK afterwards.
        setChosen(new Set(r.sheets.map((s) => s.btr)));
      }
    } catch {
      setError('Could not read that file. It must be the .xlsx dispatch export.');
    } finally {
      setBusy('');
      if (xlsxRef.current) xlsxRef.current.value = '';
    }
  }, []);

  const readShot = useCallback(async (cropped: Blob) => {
    setPendingShot(null);
    setBusy('Reading names…'); setError(''); setCrew(null);
    try {
      const { default: Tesseract } = await import('tesseract.js');
      const r = await Tesseract.recognize(cropped, 'eng', {
        logger: (m: { status: string; progress: number }) => {
          if (m.status === 'recognizing text') setBusy(`Reading names… ${Math.round(m.progress * 100)}%`);
        },
        workerPath: '/tesseract/worker.min.js',
        corePath: '/tesseract/',
        langPath: '/tesseract/',
        gzip: true,
      } as Parameters<typeof Tesseract.recognize>[2]);

      type TL = { text: string };
      const lines: TL[] = (r.data as unknown as { lines?: TL[] }).lines
        ?? r.data.text.split('\n').map((t) => ({ text: t }));
      const found = parseCrewLines(lines.map((l) => l.text));
      if (found.length === 0) {
        setError('No names found. Crop tighter around the name list, or add them by hand.');
      }
      setCrew(found);
    } catch {
      setError('Could not read that screenshot. Add the crew by hand instead.');
    } finally {
      setBusy('');
    }
  }, []);

  const commitSheets = async () => {
    if (!sheets) return;
    setBusy('Saving…');
    await onImportSheets(sheets.filter((s) => chosen.has(s.btr)));
    setBusy('');
    onClose();
  };

  const commitCrew = async () => {
    if (!crew) return;
    setBusy('Saving…');
    await onImportCrew(crew.filter((c) => c.include).map((c) => c.name.trim()).filter(Boolean));
    setBusy('');
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-3">
      <div className="mt-6 w-full max-w-lg rounded-xl border border-border bg-card p-4 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Import for {date}</h2>
            <p className="text-[11px] text-muted-foreground">
              Everything is reviewed before it is saved.
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 hover:bg-muted" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-3 flex gap-1 rounded-lg bg-muted p-1">
          {([['sheet', 'Load sheet'], ['crew', 'Crew']] as const).map(([k, label]) => (
            <button
              key={k} type="button" onClick={() => { setTab(k); setError(''); }}
              className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium ${
                tab === k ? 'bg-card shadow-sm' : 'text-muted-foreground'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {error && (
          <p className="mt-3 flex items-start gap-1 text-[11px] text-danger">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{error}
          </p>
        )}

        {busy && (
          <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />{busy}
          </p>
        )}

        {/* ── Load sheet ─────────────────────────────────────────────── */}
        {tab === 'sheet' && !busy && (
          <div className="mt-3 space-y-3">
            {!sheets ? (
              <>
                <button
                  type="button" onClick={() => xlsxRef.current?.click()}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border px-3 py-6 text-sm text-muted-foreground hover:border-primary/60 hover:bg-muted"
                >
                  <FileSpreadsheet className="h-5 w-5" /> Choose the .xlsx load sheet
                </button>
                <p className="text-[11px] text-muted-foreground">
                  One workbook holds the whole fleet. Every BTR is imported, and
                  you pick which one you are working afterwards.
                </p>
              </>
            ) : (
              <>
                <p className="text-[11px] text-muted-foreground">
                  {sheets.length} truck{sheets.length === 1 ? '' : 's'} found
                  {skipped.length > 0 && ` · ${skipped.length} sheet(s) skipped`}
                </p>
                <div className="max-h-64 space-y-1 overflow-y-auto">
                  {sheets.map((s) => {
                    const pkgs = s.stops.reduce((n, x) => n + (x.package_count ?? 0), 0);
                    const ovs = s.stops.reduce((n, x) => n + (x.ov_count ?? 0), 0);
                    return (
                      <label key={s.btr} className="flex cursor-pointer items-start gap-2 rounded-lg border border-border p-2.5 text-xs hover:bg-muted">
                        <input
                          type="checkbox" checked={chosen.has(s.btr)}
                          onChange={(e) => setChosen((c) => {
                            const n = new Set(c);
                            if (e.target.checked) n.add(s.btr); else n.delete(s.btr);
                            return n;
                          })}
                          className="mt-0.5"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="font-semibold">{s.btr}</span>
                          <span className="ml-2 text-muted-foreground">
                            {s.stops.length} stops · {s.bags.length} bags · {pkgs} pkg · {ovs} OV
                          </span>
                          {/* A sheet disagreeing with itself is surfaced, never
                              silently corrected. */}
                          {s.warnings.map((w) => (
                            <span key={w} className="mt-0.5 block text-warning">{w}</span>
                          ))}
                        </span>
                      </label>
                    );
                  })}
                </div>
                <div className="flex gap-2">
                  <button
                    type="button" onClick={() => void commitSheets()} disabled={chosen.size === 0}
                    className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40"
                  >
                    <Check className="h-4 w-4" /> Import {chosen.size} truck{chosen.size === 1 ? '' : 's'}
                  </button>
                  <button type="button" onClick={() => setSheets(null)} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">
                    Back
                  </button>
                </div>
              </>
            )}
            <input
              ref={xlsxRef} type="file" className="hidden"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void readWorkbook(f); }}
            />
          </div>
        )}

        {/* ── Crew ───────────────────────────────────────────────────── */}
        {tab === 'crew' && !busy && (
          <div className="mt-3 space-y-3">
            {!crew ? (
              <>
                <button
                  type="button" onClick={() => shotRef.current?.click()}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border px-3 py-6 text-sm text-muted-foreground hover:border-primary/60 hover:bg-muted"
                >
                  <Camera className="h-5 w-5" /> Screenshot of the assignment card
                </button>
                <p className="text-[11px] text-muted-foreground">
                  You will crop to the name list, then confirm each name. Drivers
                  are found and left unticked, since they walk no routes.
                </p>
              </>
            ) : (
              <>
                <p className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <Users className="h-3 w-3" />
                  {crew.length} name{crew.length === 1 ? '' : 's'} found ·{' '}
                  {crew.filter((c) => c.include).length} will be added
                </p>
                <div className="max-h-64 space-y-1 overflow-y-auto">
                  {crew.map((c, i) => (
                    <div key={i} className="flex items-center gap-2 rounded-lg border border-border p-2">
                      <input
                        type="checkbox" checked={c.include}
                        onChange={(e) => setCrew((cs) => cs!.map((x, j) => j === i ? { ...x, include: e.target.checked } : x))}
                        className="shrink-0"
                      />
                      <input
                        value={c.name}
                        onChange={(e) => setCrew((cs) => cs!.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                        className="min-w-0 flex-1 rounded border border-border bg-surface px-2 py-1 text-sm"
                      />
                      {c.role && (
                        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
                          c.role === 'driver' ? 'bg-warning/15 text-warning' : 'bg-muted text-muted-foreground'
                        }`}>
                          {c.role}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <button
                    type="button" onClick={() => void commitCrew()}
                    disabled={crew.every((c) => !c.include)}
                    className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40"
                  >
                    <Check className="h-4 w-4" /> Add {crew.filter((c) => c.include).length} to crew
                  </button>
                  <button type="button" onClick={() => setCrew(null)} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">
                    Back
                  </button>
                </div>
              </>
            )}
            <input
              ref={shotRef} type="file" accept="image/*" className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) setPendingShot(f);
                if (shotRef.current) shotRef.current.value = '';
              }}
            />
          </div>
        )}
      </div>

      {pendingShot && (
        <CropDialog
          file={pendingShot}
          onCancel={() => setPendingShot(null)}
          onCrop={(b) => void readShot(b)}
        />
      )}
    </div>
  );
}
