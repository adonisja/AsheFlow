import { useEffect, useState, useCallback, useRef } from 'react';
import axiosClient from '../api/axiosClient';
import { useNotificationContext } from '../contexts/NotificationContext';
import { useAuth } from '../contexts/AuthContext';
import SectionHeader from '../components/ui/SectionHeader';
import StatCard from '../components/ui/StatCard';
import ZoneDensityMap from '../components/ZoneDensityMap';
import ToteRosterPanel from '../components/ToteRosterPanel';
import RemovalsPanel from '../components/RemovalsPanel';
import type { ZonePolygon, Centroid, AnchorPin, OutlierToteMarker } from '../components/ZoneDensityMap';
import type { CompanyZone, Truck as ApiTruck, OutlierTotesResponse } from '../api/types';
import {
  Package, Truck, CheckCircle2, RefreshCw,
  ChevronDown, ChevronUp, MapPin, Layers, Loader2,
  Upload, X, FileText, ArrowRight, AlertTriangle,
  Route, Zap, Send, Download,
} from 'lucide-react';
import { getLocalYMD } from '../utils/date';

// How each truck's territory seed was resolved (ADR-169 fallback chain)
const ANCHOR_SOURCE_LABELS: Record<string, string> = {
  truck_anchor: 'Truck anchor',
  zone_history: 'Zone history',
  building_profile: 'Profile hint',
  quantile: 'Auto (quantile)',
};
import type {
  SortRunResponse, SortRunAccepted, SortRunStatusResponse,
  ManifestPreviewResponse, ManifestPreviewRow, ManifestPackagePatchResponse,
  SortPreviewResponse,
} from '../api/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TruckAssignment {
  id: string;
  truck_id: string;
  truck_name: string;
  status: string;
  date: string;
}

const GEOCODE_REASON_LABELS: Record<string, string> = {
  geoclient_no_match:  'No match',
  geoclient_error:     'API error',
  missing_address:     'No address',
  block_key_parse:     'Parse failed',
};

function PackageAddressEditor({
  row,
  sortDate,
  onPatched,
}: {
  row: ManifestPreviewRow;
  sortDate: string;
  onPatched: (updated: ManifestPackagePatchResponse) => void;
}) {
  const [editing, setEditing]     = useState(false);
  const [address, setAddress]     = useState('');
  const [saving, setSaving]       = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const reasonLabel = row.geocode_reason
    ? (GEOCODE_REASON_LABELS[row.geocode_reason] ?? row.geocode_reason)
    : null;

  if (!editing) {
    return (
      <div className="flex flex-col gap-0.5">
        {row.raw_address && (
          <span className="text-foreground/80">{row.raw_address}</span>
        )}
        <div className="flex items-center gap-1.5 flex-wrap">
          {reasonLabel && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-warning/15 text-warning font-medium">
              {reasonLabel}
            </span>
          )}
          <button
            onClick={() => { setAddress(row.raw_address ?? ''); setSaveError(null); setEditing(true); }}
            className="text-[10px] text-primary hover:underline"
            title="Correct address"
          >
            Edit
          </button>
        </div>
      </div>
    );
  }

  const handleSave = async () => {
    if (!address.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const { data } = await axiosClient.patch<ManifestPackagePatchResponse>(
        `/sort/manifest/${sortDate}/package/${encodeURIComponent(row.tba)}`,
        { corrected_address: address.trim() },
      );
      onPatched(data);
      setEditing(false);
    } catch (e: any) {
      setSaveError(e?.response?.data?.detail ?? 'Save failed.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-1 py-0.5">
      <div className="flex items-center gap-1">
        <input
          autoFocus
          type="text"
          value={address}
          onChange={e => setAddress(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSave(); if (e.key === 'Escape') setEditing(false); }}
          placeholder={row.raw_address ?? 'e.g. 123 West 34 St'}
          className="input-field text-[11px] h-6 py-0 px-1.5 flex-1 min-w-0"
        />
        <button
          onClick={handleSave}
          disabled={saving || !address.trim()}
          className="text-[10px] text-success font-semibold hover:underline disabled:opacity-40 shrink-0"
        >
          {saving ? '…' : 'Save'}
        </button>
        <button
          onClick={() => setEditing(false)}
          className="text-[10px] text-muted-foreground hover:text-foreground shrink-0"
        >
          ✕
        </button>
      </div>
      {saveError && <p className="text-[10px] text-danger">{saveError}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manifest preview panel — shown after enrichment is ready
// ---------------------------------------------------------------------------

function ManifestPreviewPanel({ sortDate }: { sortDate: string }) {
  const [preview, setPreview]     = useState<ManifestPreviewResponse | null>(null);
  const [loading, setLoading]     = useState(false);
  const [expanded, setExpanded]   = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [page, setPage]           = useState(1);
  const [failedOnly, setFailedOnly] = useState(false);
  // Local overrides so patched rows update without refetching the whole page
  const [patches, setPatches]     = useState<Record<string, ManifestPackagePatchResponse>>({});

  const load = async (p: number, fo: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await axiosClient.get<ManifestPreviewResponse>(
        `/sort/manifest/${sortDate}/preview`,
        { params: { page: p, failed_only: fo } },
      );
      setPreview(data);
      setPage(p);
      setExpanded(true);
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? 'Failed to load preview.';
      setError(typeof detail === 'string' ? detail : 'Failed to load preview.');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleFailedOnly = () => {
    const next = !failedOnly;
    setFailedOnly(next);
    setPage(1);
    load(1, next);
  };

  if (!preview && !error && !loading) {
    return (
      <button
        onClick={() => load(1, false)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <FileText className="w-3.5 h-3.5" /> Preview enriched packages
      </button>
    );
  }

  if (loading && !preview) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading preview…
      </div>
    );
  }

  if (error) return <p className="text-xs text-warning">{error}</p>;
  if (!preview) return null;

  const failPct = preview.total_packages > 0
    ? Math.round((preview.failed_count / preview.total_packages) * 100)
    : 0;

  const resolvedRows = preview.preview_rows.map(row =>
    patches[row.tba] ? { ...row, ...patches[row.tba] } : row
  );

  return (
    <div className="space-y-2">
      {/* Summary row + toggle */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <FileText className="w-3.5 h-3.5" />
          <span>
            {preview.enriched_count.toLocaleString()} enriched
            {preview.failed_count > 0 && (
              <span className="text-warning ml-1">· {preview.failed_count} failed ({failPct}%)</span>
            )}
          </span>
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
        {preview.failed_count > 0 && expanded && (
          <button
            onClick={handleToggleFailedOnly}
            className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors ${
              failedOnly
                ? 'border-warning/60 bg-warning/10 text-warning font-semibold'
                : 'border-border text-muted-foreground hover:text-foreground'
            }`}
          >
            {failedOnly ? 'Show all' : 'Failed only'}
          </button>
        )}
        <button
          onClick={async () => {
            try {
              const res = await axiosClient.get(`/sort/manifest/${sortDate}/download`, { responseType: 'blob' });
              const url = URL.createObjectURL(res.data);
              const a = document.createElement('a');
              a.href = url;
              a.download = `enriched_manifest_${sortDate}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            } catch {
              // silent — backend will 404 if no manifest exists yet
            }
          }}
          className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
        >
          <Download className="w-3 h-3" /> Download CSV
        </button>
        {loading && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
      </div>

      {expanded && (
        <div className="space-y-2">
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border bg-accent/40">
                  <th className="text-left px-2 py-1.5 text-muted-foreground font-semibold">TBA</th>
                  <th className="text-left px-2 py-1.5 text-muted-foreground font-semibold">Address</th>
                  <th className="text-left px-2 py-1.5 text-muted-foreground font-semibold">Block key</th>
                  <th className="text-left px-2 py-1.5 text-muted-foreground font-semibold">Bag</th>
                  <th className="text-center px-2 py-1.5 text-muted-foreground font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {resolvedRows.map((row, i) => (
                  <tr key={i} className={`border-b border-border/50 last:border-0 ${!row.enriched ? 'bg-warning/5' : ''}`}>
                    <td className="px-2 py-1 font-mono text-foreground whitespace-nowrap">{row.tba}</td>
                    <td className="px-2 py-1 text-muted-foreground">
                      {row.enriched
                        ? (
                          <div className="flex flex-col gap-0">
                            <span className="text-foreground/80">{row.normalised_address ?? '—'}</span>
                            {row.raw_address && row.raw_address !== row.normalised_address && (
                              <span className="text-[9px] text-muted-foreground/60">{row.raw_address}</span>
                            )}
                          </div>
                        )
                        : <PackageAddressEditor
                            row={row}
                            sortDate={sortDate}
                            onPatched={updated => setPatches(prev => ({ ...prev, [row.tba]: updated }))}
                          />
                      }
                    </td>
                    <td className="px-2 py-1 font-mono text-foreground whitespace-nowrap">{row.block_key ?? '—'}</td>
                    <td className="px-2 py-1 text-muted-foreground whitespace-nowrap">{row.bag_id ?? '—'}</td>
                    <td className="px-2 py-1 text-center">
                      {row.enriched
                        ? <span className="text-success">✓</span>
                        : <span className="text-warning">✗</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {preview.total_pages > 1 && (
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <button
                disabled={page <= 1 || loading}
                onClick={() => load(page - 1, failedOnly)}
                className="px-2 py-0.5 rounded border border-border hover:bg-accent disabled:opacity-40 transition-colors"
              >
                ‹ Prev
              </button>
              <span className="tabular-nums">
                Page {page} of {preview.total_pages}
                {' '}· {(failedOnly ? preview.failed_count : preview.total_packages).toLocaleString()} packages
              </span>
              <button
                disabled={page >= preview.total_pages || loading}
                onClick={() => load(page + 1, failedOnly)}
                className="px-2 py-0.5 rounded border border-border hover:bg-accent disabled:opacity-40 transition-colors"
              >
                Next ›
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manifest upload panel — production CSV upload + enrichment status polling
// ---------------------------------------------------------------------------

type UploadPhase = 'idle' | 'uploading' | 'enriching' | 'ready' | 'error';

function ManifestUploadPanel({
  today,
  onReady,
}: {
  today: string;
  onReady: (uploadedDate: string) => void;
}) {
  const [phase, setPhase]                       = useState<UploadPhase>('idle');
  const [uploadDate, setUploadDate]             = useState(today);
  const [file, setFile]                         = useState<File | null>(null);
  const [packageCount, setPackageCount]         = useState(0);
  const [failedCount, setFailedCount]           = useState(0);
  const [warnings, setWarnings]                 = useState<string[]>([]);
  const [errorMsg, setErrorMsg]                 = useState<string | null>(null);
  const [expanded, setExpanded]                 = useState(false);
  const [processedCount, setProcessedCount]     = useState<number | null>(null);
  const [totalCount, setTotalCount]             = useState<number | null>(null);
  const enrichStartRef                          = useRef<number | null>(null);
  const fileRef                                 = useRef<HTMLInputElement>(null);
  const pollRef                                 = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => () => stopPoll(), []);

  // On mount, check if a manifest is already in flight from another page/tool.
  useEffect(() => {
    axiosClient.get(`/sort/manifest/${today}/status`).then(({ data }) => {
      if (data.status === 'enriching') {
        setPhase('enriching');
        setExpanded(true);
        enrichStartRef.current = Date.now();
        if (data.packages_processed != null) setProcessedCount(data.packages_processed);
        if (data.packages_total != null) setTotalCount(data.packages_total);
        startPolling(today);
      } else if (data.status === 'ready') {
        setPackageCount(data.package_count);
        setFailedCount(data.failed_count ?? 0);
        setPhase('ready');
        onReady(today);
      } else if (data.status === 'failed') {
        setErrorMsg(data.failed_reason ?? 'Enrichment failed — re-upload or contact your admin.');
        setPhase('error');
        setExpanded(true);
      }
    }).catch(() => {/* no manifest yet — stay idle */});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today]);

  const startPolling = (sortDate: string) => {
    stopPoll();
    if (!enrichStartRef.current) enrichStartRef.current = Date.now();
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await axiosClient.get(`/sort/manifest/${sortDate}/status`);
        if (data.status === 'enriching') {
          if (data.packages_processed != null) setProcessedCount(data.packages_processed);
          if (data.packages_total != null) setTotalCount(data.packages_total);
        } else if (data.status === 'ready') {
          stopPoll();
          setPackageCount(data.package_count);
          setFailedCount(data.failed_count ?? 0);
          setProcessedCount(null);
          setTotalCount(null);
          enrichStartRef.current = null;
          setPhase('ready');
          setExpanded(false);
          onReady(sortDate);
        } else if (data.status === 'failed') {
          stopPoll();
          setErrorMsg(data.failed_reason ?? 'Enrichment failed — re-upload or contact your admin.');
          setPhase('error');
        }
      } catch {
        // transient network hiccup — keep polling
      }
    }, 5_000);
  };

  const handleUpload = async () => {
    if (!file) return;
    setPhase('uploading');
    setErrorMsg(null);
    setWarnings([]);
    setExpanded(true);  // auto-expand so user sees progress
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('sort_date', uploadDate);
      const { data } = await axiosClient.post('/sort/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setPackageCount(data.package_count);
      setWarnings(data.warnings ?? []);
      enrichStartRef.current = Date.now();
      setPhase('enriching');
      startPolling(uploadDate);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'Upload failed.';
      setErrorMsg(typeof detail === 'string' ? detail : JSON.stringify(detail));
      setPhase('error');
    }
  };

  const handleReset = () => {
    stopPoll();
    setPhase('idle');
    setFile(null);
    setErrorMsg(null);
    setWarnings([]);
    setPackageCount(0);
    setFailedCount(0);
    setProcessedCount(null);
    setTotalCount(null);
    enrichStartRef.current = null;
    if (fileRef.current) fileRef.current.value = '';
  };

  // Border colour reflects state
  const borderClass =
    phase === 'error'     ? 'border-danger/40 bg-danger/5' :
    phase === 'ready'     ? 'border-success/40 bg-success/5' :
    phase === 'enriching' ? 'border-primary/40 bg-primary/5' :
                            'border-border bg-surface-muted/30';

  const headerSubtext =
    phase === 'idle'      ? 'Select a manifest file and upload to begin geocoding.' :
    phase === 'uploading' ? 'Uploading and parsing…' :
    phase === 'enriching' ? (
      processedCount != null && totalCount != null && totalCount > 0
        ? `Geocoding — ${Math.round((processedCount / totalCount) * 100)}% (${processedCount.toLocaleString()} / ${totalCount.toLocaleString()})`
        : `Geocoding ${packageCount > 0 ? packageCount.toLocaleString() + ' packages' : '…'}`
    ) :
    phase === 'ready'     ? `${packageCount.toLocaleString()} packages ready${failedCount > 0 ? ` · ${failedCount} failed geocoding` : ''} — run sort below.` :
                            (errorMsg ?? 'Upload failed.');

  return (
    <div className={`rounded-2xl border overflow-hidden transition-colors ${borderClass}`}>
      {/* Header — always visible */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-black/5 transition-colors text-left"
        onClick={() => setExpanded(v => !v)}
      >
        {phase === 'enriching'
          ? <Loader2 className="w-5 h-5 text-primary animate-spin shrink-0" />
          : phase === 'error'
          ? <AlertTriangle className="w-5 h-5 text-danger shrink-0" />
          : phase === 'ready'
          ? <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
          : <Upload className="w-5 h-5 text-muted-foreground shrink-0" />}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">Manifest</p>
          <p className={`text-xs truncate ${phase === 'error' ? 'text-danger' : phase === 'ready' ? 'text-success' : 'text-muted-foreground'}`}>
            {headerSubtext}
          </p>
        </div>
        {expanded
          ? <ChevronUp className="w-4 h-4 text-muted-foreground shrink-0" />
          : <ChevronDown className="w-4 h-4 text-muted-foreground shrink-0" />}
      </button>

      {expanded && (
        <div className="border-t border-border/50 px-4 py-3 space-y-3">

          {/* idle / error — show form */}
          {(phase === 'idle' || phase === 'error') && (
            <div className="space-y-3">
              {errorMsg && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-danger/10 border border-danger/20">
                  <AlertTriangle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-danger">{errorMsg}</p>
                    <button
                      onClick={handleReset}
                      className="mt-1.5 text-xs text-danger/70 hover:text-danger underline underline-offset-2"
                    >
                      Dismiss and start over
                    </button>
                  </div>
                </div>
              )}
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Sort date</label>
                  <input
                    type="date"
                    value={uploadDate}
                    onChange={e => setUploadDate(e.target.value)}
                    className="input-field text-sm h-9 w-40"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Manifest file (CSV / XLSX)</label>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".csv,.xlsx,.xls,.pdf,.jpg,.jpeg,.png"
                    onChange={e => setFile(e.target.files?.[0] ?? null)}
                    className="block text-xs text-muted-foreground file:mr-2 file:py-1 file:px-3 file:rounded-lg file:border file:border-border file:text-xs file:bg-surface file:text-foreground file:cursor-pointer hover:file:bg-accent"
                  />
                </div>
              </div>
              {file && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <FileText className="w-3.5 h-3.5 shrink-0" />
                  {file.name} · {(file.size / 1024).toFixed(0)} KB
                </div>
              )}
              <button
                onClick={handleUpload}
                disabled={!file}
                className="btn-primary flex items-center gap-2 text-sm disabled:opacity-40"
              >
                <Upload className="w-4 h-4" />
                Upload & Start Enrichment
              </button>
            </div>
          )}

          {/* uploading */}
          {phase === 'uploading' && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
              Uploading and parsing manifest…
            </div>
          )}

          {/* enriching */}
          {phase === 'enriching' && (() => {
            const pct = (processedCount != null && totalCount != null && totalCount > 0)
              ? Math.round((processedCount / totalCount) * 100)
              : null;
            const elapsedMs = enrichStartRef.current ? Date.now() - enrichStartRef.current : 0;
            const etaStr = (() => {
              if (pct == null || pct === 0 || elapsedMs < 3000) return null;
              const totalEstMs = (elapsedMs / pct) * 100;
              const remainMs = totalEstMs - elapsedMs;
              if (remainMs <= 0) return null;
              const mins = Math.ceil(remainMs / 60_000);
              return mins <= 1 ? '< 1 min remaining' : `~${mins} min remaining`;
            })();
            return (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>Geocoding in progress</span>
                    <span className="tabular-nums">
                      {processedCount != null && totalCount != null
                        ? `${processedCount.toLocaleString()} / ${totalCount.toLocaleString()} packages`
                        : totalCount != null
                        ? `${totalCount.toLocaleString()} packages`
                        : packageCount > 0
                        ? `${packageCount.toLocaleString()} packages`
                        : 'Starting…'}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-accent overflow-hidden">
                    {pct != null ? (
                      <div
                        className="h-full bg-primary rounded-full transition-all duration-1000 ease-out"
                        style={{ width: `${pct}%` }}
                      />
                    ) : (
                      <div
                        className="h-full w-1/4 bg-primary rounded-full"
                        style={{ animation: 'slide 1.5s ease-in-out infinite' }}
                      />
                    )}
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-primary font-medium">
                      {pct != null ? `${pct}%` : ''}
                    </span>
                    {etaStr && <span className="text-muted-foreground">{etaStr}</span>}
                  </div>
                </div>
                {warnings.length > 0 && warnings.map((w, i) => (
                  <p key={i} className="text-xs text-warning flex items-start gap-1">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />{w}
                  </p>
                ))}
                <button onClick={handleReset} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                  <X className="w-3.5 h-3.5" /> Cancel
                </button>
              </div>
            );
          })()}

          {/* ready */}
          {phase === 'ready' && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm text-success font-medium">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                {packageCount.toLocaleString()} packages enriched and ready.
                {failedCount > 0 && (
                  <span className="text-warning font-normal">({failedCount} failed geocoding — will be dropped from sort.)</span>
                )}
              </div>
              {warnings.length > 0 && warnings.map((w, i) => (
                <p key={i} className="text-xs text-warning flex items-start gap-1">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />{w}
                </p>
              ))}
              <ManifestPreviewPanel sortDate={uploadDate} />
              <button onClick={handleReset} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                <X className="w-3.5 h-3.5" /> Upload a different file
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sort result preview — shown after sort completes
// ---------------------------------------------------------------------------

function SortPreviewPanel({ today, taskId }: { today: string; taskId: string }) {
  const [preview, setPreview]   = useState<SortPreviewResponse | null>(null);
  const [loading, setLoading]   = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [error, setError]       = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    axiosClient
      .get<SortPreviewResponse>(`/sort/run/preview/${taskId}`, { params: { sort_date: today } })
      .then(({ data }) => { if (!cancelled) { setPreview(data); setLoading(false); } })
      .catch((e: any) => {
        if (!cancelled) {
          setError(e?.response?.data?.detail ?? 'Preview unavailable.');
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [taskId, today]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading sort summary…
      </div>
    );
  }

  if (error || !preview) return null;

  return (
    <div className="space-y-2">
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
      >
        <Route className="w-3.5 h-3.5" />
        <span className="font-semibold">Zone breakdown</span>
        <span className="text-muted-foreground ml-1">
          {preview.zones_created} zones · {preview.package_count.toLocaleString()} packages
          {preview.outlier_count > 0 && <span className="text-warning ml-1">· {preview.outlier_count} outliers</span>}
        </span>
        {expanded ? <ChevronUp className="w-3.5 h-3.5 ml-auto" /> : <ChevronDown className="w-3.5 h-3.5 ml-auto" />}
      </button>

      {expanded && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border bg-accent/40">
                <th className="text-left px-2 py-1.5 text-muted-foreground font-semibold">Truck</th>
                <th className="text-right px-2 py-1.5 text-muted-foreground font-semibold">Packages</th>
                <th className="text-left px-2 py-1.5 text-muted-foreground font-semibold">Anchor</th>
                <th className="text-right px-2 py-1.5 text-muted-foreground font-semibold">Workload</th>
                <th className="text-left px-2 py-1.5 text-muted-foreground font-semibold">Flags</th>
              </tr>
            </thead>
            <tbody>
              {preview.assignments.map(a => (
                <tr key={a.truck_id} className="border-b border-border/50 last:border-0">
                  <td className="px-2 py-1 font-semibold text-foreground">
                    {a.truck_name}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums text-foreground">{a.package_count.toLocaleString()}</td>
                  <td className="px-2 py-1 text-muted-foreground">
                    {ANCHOR_SOURCE_LABELS[a.anchor_source ?? ''] ?? '—'}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">
                    {a.workload_score != null ? a.workload_score.toFixed(2) : '—'}
                  </td>
                  <td className="px-2 py-1">
                    <span className="text-success">✓</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.outlier_count > 0 && (
            <p className="text-[10px] text-warning px-2 py-1.5 border-t border-border/50 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 shrink-0" />
              {preview.outlier_count} package{preview.outlier_count !== 1 ? 's' : ''} outside the company zone and require manual placement by dispatch.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Animated step row — shown while the sort task is running
// ---------------------------------------------------------------------------

const STEP_DELAY_MS = 1_800;

function StepRow({ label, index }: { label: string; index: number }) {
  const [visible, setVisible] = useState(index === 0);
  useEffect(() => {
    if (index === 0) return;
    const t = setTimeout(() => setVisible(true), index * STEP_DELAY_MS);
    return () => clearTimeout(t);
  }, [index]);
  if (!visible) return null;
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="w-4 h-4 animate-spin text-primary shrink-0" />
      {label}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manifest sort panel — POST /sort/run, tier-1 review, override, resubmit
// ---------------------------------------------------------------------------

type SortRunPhase = 'idle' | 'running' | 'done';

const _SORT_POLL_INTERVAL = 3_000;   // 3 s between status checks

const _SORT_TASK_KEY = (date: string) => `asheflow.sortTask.${date}`;

function ManifestSortPanel({
  today,
  trucks,
  manifestReady,
  onZonesCreated,
}: {
  today: string;
  trucks: { truck_id: string; truck_name: string }[];
  manifestReady: boolean;
  onZonesCreated: () => void;
}) {
  const { setOnNotification } = useNotificationContext();
  const [phase, setPhase]               = useState<SortRunPhase>('idle');
  const [result, setResult]             = useState<SortRunResponse | null>(null);
  const [error, setError]               = useState<string | null>(null);
  const [expanded, setExpanded]         = useState(false);
  const [running, setRunning]           = useState(false);
  const [doneTaskId, setDoneTaskId]     = useState<string | null>(null);
  const pollRef                         = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => () => stopPoll(), []);

  function handleStatusPayload(data: SortRunStatusResponse) {
    setOnNotification(null); // clear SSE callback on any terminal status
    if (data.status === 'done') {
      const synth: SortRunResponse = {
        sort_date:        data.sort_date!,
        package_count:    data.package_count!,
        outlier_count:    data.outlier_count!,
        cluster_count:    data.cluster_count!,
        zones_created:    data.zones_created!,
        station_removals: data.station_removals ?? 0,
        ap_flags:         data.ap_flags ?? 0,
        unplaced_totes:   data.unplaced_totes ?? 0,
        assignments:      data.assignments,
        volume_alert:     data.volume_alert    ?? false,
        volume_alert_msg: data.volume_alert_msg ?? '',
      };
      setResult(synth);
      setDoneTaskId(data.task_id);
      setPhase('done');
      setExpanded(false);
      setRunning(false);
      onZonesCreated();
    } else if (data.status === 'error') {
      const SENTINEL: Record<string, string> = {
        internal_error:    'Zone assignment failed due to an unexpected error. Retry or check worker logs.',
        worker_unreachable: 'Sort worker did not pick up the task — Celery may be down. Contact your admin.',
      };
      const raw = data.detail ?? '';
      setError(SENTINEL[raw] ?? (raw || 'Sort failed.'));
      setPhase('idle');
      setRunning(false);
    }
    // status === 'running' → keep polling
  }

  // Fetch status for a known task_id once and handle the payload.
  // Used both by SSE callback and by the fallback poller.
  const fetchStatus = useCallback(async (taskId: string) => {
    try {
      const { data } = await axiosClient.get<SortRunStatusResponse>(
        `/sort/run/status/${taskId}`,
        { params: { sort_date: today } },
      );
      if (data.status !== 'running') {
        stopPoll();
        sessionStorage.removeItem(_SORT_TASK_KEY(today));
        handleStatusPayload(data);
      }
    } catch {
      // transient — leave polling running
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today]);

  // On mount: re-attach to any in-progress task stored in sessionStorage.
  // This lets the user navigate away and come back — the task runs on the
  // backend regardless and the SSE stream will fire when it finishes.
  useEffect(() => {
    const stored = sessionStorage.getItem(_SORT_TASK_KEY(today));
    if (!stored) return;
    const { taskId } = JSON.parse(stored) as { taskId: string };
    setPhase('running');
    setRunning(true);
    setExpanded(true);

    // Start fallback poller in case SSE notification arrives late or is missed
    pollRef.current = setInterval(() => fetchStatus(taskId), _SORT_POLL_INTERVAL);

    // Register SSE callback — fires immediately if the task already finished
    // while we were away, or as soon as the worker pushes the notification.
    setOnNotification((type: string) => {
      if (type === 'zone_sort_complete') {
        stopPoll();
        fetchStatus(taskId);
        setOnNotification(null);
      }
    });

    return () => { setOnNotification(null); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runSort() {
    setRunning(true);
    setError(null);
    stopPoll();
    // Evict any stale task ID and SSE callback left by a previous run or
    // page-reload mid-task. Without this, the mount-effect poller targeting the
    // old task ID races with the new SSE callback and the new result is lost.
    sessionStorage.removeItem(_SORT_TASK_KEY(today));
    setOnNotification(null);
    try {
      const { data: accepted } = await axiosClient.post<SortRunAccepted>('/sort/run', {
        sort_date: today,
      });
      const taskId = accepted.task_id;

      // Persist task_id so re-mounting the panel can re-attach
      sessionStorage.setItem(_SORT_TASK_KEY(today), JSON.stringify({ taskId }));

      // Primary: wait for SSE notification (task complete/review) then fetch once
      setOnNotification((type: string) => {
        if (type === 'zone_sort_complete') {
          stopPoll();
          fetchStatus(taskId);
          setOnNotification(null);
        }
      });

      // Fallback poller: catches the result if SSE notification is missed
      // (e.g. notification already read, SSE reconnecting, token refresh gap)
      pollRef.current = setInterval(() => fetchStatus(taskId), _SORT_POLL_INTERVAL);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'Sort failed.';
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      setPhase('idle');
      setRunning(false);
    }
  }

  function handleInitialRun() {
    setPhase('running');
    setExpanded(true);
    runSort();
  }

  const borderClass =
    phase === 'done'         ? 'border-success/40 bg-success/5'
    : phase === 'running'    ? 'border-primary/40 bg-primary/5'
    : error                  ? 'border-danger/40 bg-danger/5'
    : 'border-border bg-surface-muted/30';

  const doneExtras = result
    ? [
        result.station_removals ? `${result.station_removals} station removal${result.station_removals === 1 ? '' : 's'}` : null,
        result.ap_flags ? `${result.ap_flags} AP pull${result.ap_flags === 1 ? '' : 's'}` : null,
        result.unplaced_totes ? `${result.unplaced_totes} unplaced` : null,
      ].filter(Boolean).join(' · ')
    : '';

  const headerSubtext =
    phase === 'idle'         ? (manifestReady ? 'Manifest ready — assign packages to truck zones.' : 'Upload a manifest first to enable zone sort.')
    : phase === 'running'    ? 'Assigning totes to truck zones…'
    : phase === 'done'       ? `Zones created: ${result?.zones_created ?? 0} · ${result?.package_count.toLocaleString()} packages sorted.${doneExtras ? ` · ${doneExtras}` : ''}`
    : (error ?? 'Sort failed.');

  return (
    <div className={`rounded-2xl border overflow-hidden transition-colors ${borderClass}`}>
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-black/5 transition-colors text-left"
        onClick={() => setExpanded(v => !v)}
      >
        {phase === 'running'
          ? <Loader2 className="w-5 h-5 text-primary animate-spin shrink-0" />
          : phase === 'done'
          ? <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
          : error
          ? <AlertTriangle className="w-5 h-5 text-danger shrink-0" />
          : <Layers className="w-5 h-5 text-muted-foreground shrink-0" />}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">Zone Assignment</p>
          <p className={`text-xs truncate ${
            phase === 'done' ? 'text-success'
            : error ? 'text-danger'
            : 'text-muted-foreground'
          }`}>
            {headerSubtext}
          </p>
        </div>
        {expanded
          ? <ChevronUp className="w-4 h-4 text-muted-foreground shrink-0" />
          : <ChevronDown className="w-4 h-4 text-muted-foreground shrink-0" />}
      </button>

      {expanded && (
        <div className="border-t border-border/50 px-4 py-3 space-y-4">

          {/* Error state */}
          {error && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-danger/10 border border-danger/20">
              <AlertTriangle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-danger">{error}</p>
                <button
                  onClick={() => { setError(null); setPhase('idle'); }}
                  className="mt-1.5 text-xs text-danger/70 hover:text-danger underline underline-offset-2"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          {/* Idle — run button */}
          {phase === 'idle' && !error && (
            <div className="space-y-2">
              {!manifestReady && (
                <p className="text-xs text-muted-foreground">
                  Upload and geocode a manifest before running zone assignment.
                </p>
              )}
              <button
                onClick={handleInitialRun}
                disabled={running || !manifestReady}
                className="btn-primary flex items-center gap-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Zap className="w-4 h-4" /> Run Zone Assignment
              </button>
            </div>
          )}

          {/* Running — animated step progression */}
          {phase === 'running' && (
            <div className="space-y-2">
              {[
                'Loading manifest from Redis…',
                'Building totes from bag IDs…',
                'Assigning totes to truck anchors…',
                'Balancing tote counts across trucks…',
                'Flagging out-of-zone freight…',
              ].map((label, i) => (
                <StepRow key={i} label={label} index={i} />
              ))}
            </div>
          )}

          {/* Done — summary */}
          {phase === 'done' && result && (
            <div className="space-y-3">
              {result.volume_alert && (
                <div className="flex items-start gap-2 p-3 bg-warning/5 border border-warning/30 rounded-xl text-xs text-warning">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>{result.volume_alert_msg}</span>
                </div>
              )}
              {doneTaskId && <SortPreviewPanel today={today} taskId={doneTaskId} />}
              <button
                onClick={() => { setPhase('idle'); setResult(null); setError(null); setDoneTaskId(null); }}
                className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
              >
                Re-run sort
              </button>
            </div>
          )}

        </div>
      )}
    </div>
  );
}

/** Flatten truck anchor columns into map pins (primary + optional secondary). */
function toAnchorPins(trucks: ApiTruck[]): AnchorPin[] {
  return trucks.flatMap(t => {
    const pins: AnchorPin[] = [];
    if (t.initial_anchor_lat != null && t.initial_anchor_lng != null) {
      pins.push({ truck_id: t.id, truck_name: t.name, lat: t.initial_anchor_lat, lng: t.initial_anchor_lng, which: 1 });
    }
    if (t.initial_anchor2_lat != null && t.initial_anchor2_lng != null) {
      pins.push({ truck_id: t.id, truck_name: t.name, lat: t.initial_anchor2_lat, lng: t.initial_anchor2_lng, which: 2 });
    }
    return pins;
  });
}

/**
 * Crew-scoped Station Sort (ADR-177 follow-up).
 *
 * Drivers get ONLY their own truck's tote check-off — dispatch reads the
 * registered checks (each check records checked_by). The module unlocks
 * once zone assignment is complete for the day (zones exist); before that
 * there is nothing to load. All roster fetches/mutations are scoped server
 * side to the caller's truck via mode="driver".
 */
function CrewStationView({ today }: { today: string }) {
  // 'loading' | 'ready' (my truck has a roster) | 'no_truck' (crewed nowhere
  // today) | 'not_zoned' (dispatch hasn't run zone assignment yet)
  const [state, setState] = useState<'loading' | 'ready' | 'no_truck' | 'not_zoned'>('loading');

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      axiosClient.get<{ rosters: unknown[]; roster_available: boolean }>(`/sort/${today}/rosters`, { params: { mine: true } }),
      axiosClient.get<{ zones: unknown[] }>(`/sort/${today}`),
    ])
      .then(([mine, all]) => {
        if (cancelled) return;
        if (mine.data.roster_available && mine.data.rosters.length > 0) setState('ready');
        else if ((all.data.zones ?? []).length > 0) setState('no_truck');
        else setState('not_zoned');
      })
      .catch(() => { if (!cancelled) setState('not_zoned'); });
    return () => { cancelled = true; };
  }, [today]);

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        eyebrow="Station Loading"
        title="Tote check-off"
        description={`Check your truck's totes onto the truck as they are staged — ${new Date(today + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
      />
      {state === 'loading' ? (
        <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Checking today's zone assignment…
        </div>
      ) : state === 'ready' ? (
        <ToteRosterPanel date={today} mode="driver" />
      ) : (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-accent/40 border border-border text-sm text-muted-foreground">
          <Layers className="w-4 h-4 shrink-0" />
          {state === 'no_truck'
            ? 'You are not on a truck crew today, so there is nothing to check off.'
            : 'Tote check-off unlocks once dispatch completes the zone assignment.'}
        </div>
      )}
    </div>
  );
}

export default function SortPage() {
  const { groups } = useAuth();
  // Driver-only → scoped check-off view. Drivers check off their own truck's
  // totes; trainers are not involved in station loading. Dispatch/management/
  // admin see the full page.
  const isDriverOnly =
    groups.includes('driver') &&
    !groups.some(g => ['dispatch', 'management', 'admin'].includes(g));
  if (isDriverOnly) return <CrewStationView today={getLocalYMD()} />;

  const today = getLocalYMD();
  const [assignments, setAssignments] = useState<TruckAssignment[]>([]);
  const [zones, setZones] = useState<ZonePolygon[]>([]);
  const [centroids, setCentroids] = useState<Centroid[]>([]);
  const [anchors, setAnchors] = useState<AnchorPin[]>([]);
  const [outlierTotes, setOutlierTotes] = useState<OutlierToteMarker[]>([]);
  const [companyZone, setCompanyZone] = useState<CompanyZone | null>(() => {
    try {
      const raw = localStorage.getItem('asheflow.companyZone.v1');
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [zonedTruckIds, setZonedTruckIds] = useState<Set<string>>(new Set());
  const [activeManifestDate, setActiveManifestDate] = useState<string>(today);
  const [manifestReady, setManifestReady] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taRes, zoneRes, centroidRes, czRes, trucksRes, outlierRes] = await Promise.allSettled([
        axiosClient.get<TruckAssignment[]>('/assignments/', { params: { date: today } }),
        axiosClient.get<{ zones: ZonePolygon[] }>(`/sort/${today}`),
        axiosClient.get<{ centroids: Centroid[] }>(`/sort/${today}/centroids`),
        axiosClient.get<CompanyZone | null>('/sort/company-zone'),
        axiosClient.get<ApiTruck[]>('/trucks/'),
        axiosClient.get<OutlierTotesResponse>(`/sort/${today}/outlier-totes`),
      ]);
      if (trucksRes.status === 'fulfilled') setAnchors(toAnchorPins(trucksRes.value.data ?? []));
      if (outlierRes.status === 'fulfilled') setOutlierTotes(outlierRes.value.data.totes ?? []);
      if (zoneRes.status === 'fulfilled') {
        const fetchedZones = zoneRes.value.data.zones ?? [];
        setZones(fetchedZones);
        setZonedTruckIds(new Set(fetchedZones.map((z: ZonePolygon) => z.truck_id)));
      }
      if (centroidRes.status === 'fulfilled') setCentroids(centroidRes.value.data.centroids ?? []);
      if (czRes.status === 'fulfilled' && czRes.value.data) {
        const cz = czRes.value.data;
        setCompanyZone(prev => {
          if (prev?.id !== cz.id) {
            try { localStorage.setItem('asheflow.companyZone.v1', JSON.stringify(cz)); } catch {}
          }
          return cz;
        });
      }
      if (taRes.status === 'rejected') throw taRes.reason;
      setAssignments(taRes.value.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to load data.');
    } finally {
      setLoading(false);
    }
  }, [today]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const trucksWithZones = assignments.filter(a => zonedTruckIds.has(a.truck_id));

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        eyebrow="Station Operations"
        title="Station Sort"
        description={`Upload manifest, assign packages to truck zones, and hand off to AP Sort for ${new Date(today + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
        actions={
          <button onClick={fetchAll} className="btn-ghost flex items-center gap-1.5 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      {/* Stats — manifest-level metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Trucks assigned"  value={loading ? '—' : assignments.length}       icon={Truck}         tone="primary"  delay={0} />
        <StatCard label="Zones created"    value={loading ? '—' : zonedTruckIds.size}       icon={Package}       tone="info"     delay={0.05} />
        <StatCard label="Ready for AP Sort" value={loading ? '—' : trucksWithZones.length}  icon={CheckCircle2}  tone={trucksWithZones.length > 0 ? 'success' : 'primary'} delay={0.1} />
        <StatCard label="Pending zones"    value={loading ? '—' : Math.max(0, assignments.length - zonedTruckIds.size)} icon={Layers} tone={assignments.length > zonedTruckIds.size ? 'warning' : 'success'} delay={0.15} />
      </div>

      {error && (
        <div className="p-4 bg-danger/5 border border-danger/20 rounded-xl text-sm text-danger">{error}</div>
      )}

      {/* Manifest upload */}
      <ManifestUploadPanel
        today={today}
        onReady={uploadedDate => {
          setActiveManifestDate(uploadedDate);
          setManifestReady(true);
          fetchAll();
        }}
      />

      {/* Zone sort */}
      {assignments.length > 0 && (
        <ManifestSortPanel
          today={activeManifestDate}
          manifestReady={manifestReady}
          trucks={Array.from(
            new Map(assignments.map(a => [a.truck_id, { truck_id: a.truck_id, truck_name: a.truck_name }])).values()
          )}
          onZonesCreated={() => {
            Promise.allSettled([
              axiosClient.get<{ zones: ZonePolygon[] }>(`/sort/${activeManifestDate}`),
              axiosClient.get<{ centroids: Centroid[] }>(`/sort/${activeManifestDate}/centroids`),
              axiosClient.get<OutlierTotesResponse>(`/sort/${activeManifestDate}/outlier-totes`),
            ]).then(([zoneRes, centroidRes, outlierRes]) => {
              if (zoneRes.status === 'fulfilled') {
                const fetchedZones = zoneRes.value.data.zones ?? [];
                setZones(fetchedZones);
                setZonedTruckIds(new Set(fetchedZones.map((z: ZonePolygon) => z.truck_id)));
              }
              if (centroidRes.status === 'fulfilled') {
                setCentroids(centroidRes.value.data.centroids ?? []);
              }
              if (outlierRes.status === 'fulfilled') {
                setOutlierTotes(outlierRes.value.data.totes ?? []);
              }
            });
          }}
        />
      )}

      {/* Zone density map */}
      {(companyZone || assignments.length > 0) && (
        <ZoneDensityMap
          zones={zones}
          centroids={centroids}
          companyZone={companyZone}
          anchors={anchors}
          outlierTotes={outlierTotes}
          className="h-[520px]"
        />
      )}

      {/* Station loading: per-truck tote check-off + transfer resolution (ADR-174) */}
      {zones.length > 0 && (
        <div className="space-y-2">
          <SectionHeader
            eyebrow="Station Loading"
            title="Tote check-off"
            description="Check totes onto their truck as they are staged. Pending transfers need a decision before loading is finalized."
          />
          <ToteRosterPanel date={activeManifestDate} mode="dispatch" />
          <RemovalsPanel date={activeManifestDate} />
        </div>
      )}

      {/* AP Sort handoff callout — shown once zones exist */}
      {trucksWithZones.length > 0 && (
        <div className="flex items-start gap-4 p-4 bg-success/5 border border-success/20 rounded-xl">
          <CheckCircle2 className="w-5 h-5 text-success shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0 space-y-1">
            <p className="text-sm font-semibold text-foreground">
              {trucksWithZones.length} truck{trucksWithZones.length === 1 ? '' : 's'} zoned and ready
            </p>
            <p className="text-xs text-muted-foreground">
              Zone assignment is complete. Head to AP Sort to commit routes, assign walkers, and send waves.
            </p>
          </div>
          <a href="/walker-sort" className="btn-primary flex items-center gap-1.5 text-sm shrink-0">
            AP Sort <ArrowRight className="w-4 h-4" />
          </a>
        </div>
      )}
    </div>
  );
}
