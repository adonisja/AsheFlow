import { useEffect, useState, useCallback, useRef } from 'react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import StatCard from '../components/ui/StatCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import ZoneDensityMap from '../components/ZoneDensityMap';
import type { ZonePolygon, Centroid } from '../components/ZoneDensityMap';
import {
  Package, Users, AlertTriangle, CheckCircle2, RefreshCw,
  ChevronDown, ChevronUp, Send, UserCheck, Shuffle,
  MapPin, Route, Layers, Zap, CircleAlert, Loader2,
  ArrowRightLeft, Upload, X, FileText,
} from 'lucide-react';
import { getLocalYMD } from '../utils/date';
import type {
  CommitSortResponse, RouteResponse, WaveAssignmentEntry,
  ArrivalConfirmResponse, MisroutedPackageOut,
  WavePoolResponse, ProposedAssignmentEntry, WaveDistributionProposal,
  SortRunResponse, SortRunAccepted, SortRunStatusResponse, BagResultOut, BagOverride,
} from '../api/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TruckAssignment {
  id: string;
  truck_id: string;
  truck_name: string;
  status: string;
  route_date: string;
}

interface Employee {
  id: string;
  name: string;
  role: string;
}

type SortPhase = 'idle' | 'committed' | 'distributed' | 'arrived';

interface TruckSortState {
  ta: TruckAssignment;
  phase: SortPhase;
  routes: RouteResponse[];
  unassigned_misroutes: MisroutedPackageOut[];
  packages_sorted: number;
  packages_dropped: number;
  dropped_tbas: string[];
  rebalanceResult: ArrivalConfirmResponse | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function EffortBadge({ effort }: { effort: string }) {
  const cls =
    effort === 'heavy'
      ? 'bg-danger/10 text-danger'
      : effort === 'easy'
      ? 'bg-success/10 text-success'
      : 'bg-primary/10 text-primary';
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {effort}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Wave pool panel — live second-wave state, polled every 30 s
// ---------------------------------------------------------------------------

function WavePoolPanel({
  taId,
  routeDate,
  walkers,
  onSecondWavePropose,
}: {
  taId: string;
  routeDate: string;
  walkers: { id: string; name: string; role: string }[];
  onSecondWavePropose: (taId: string, proposal: ProposedAssignmentEntry[]) => void;
}) {
  const [pool, setPool]         = useState<WavePoolResponse | null>(null);
  const [loading, setLoading]   = useState(true);
  const [proposing, setProposing] = useState(false);
  const [propError, setPropError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchPool = useCallback(async () => {
    try {
      const { data } = await axiosClient.get<WavePoolResponse>(
        `/walker-routes/${taId}/wave-pool`,
        { params: { route_date: routeDate } },
      );
      setPool(data);
    } catch {
      // silent — pool is advisory
    } finally {
      setLoading(false);
    }
  }, [taId, routeDate]);

  useEffect(() => {
    fetchPool();
    intervalRef.current = setInterval(fetchPool, 30_000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [fetchPool]);

  async function handleAutoPropose() {
    setProposing(true);
    setPropError(null);
    try {
      const res = await axiosClient.post<WaveDistributionProposal>(
        '/walker-routes/wave-distribution',
        {
          truck_assignment_id: taId,
          route_date: routeDate,
          auto_assign: true,
          assignments: [],
          trainer_id: null,
          trainee_id: null,
          trainee_phase: null,
        },
      );
      onSecondWavePropose(taId, res.data.proposed_assignments);
      if (res.data.conflicts.length > 0) {
        setPropError(`Conflicts: ${res.data.conflicts.join('; ')}`);
      }
    } catch (e: any) {
      setPropError(e?.response?.data?.detail ?? 'Auto-propose failed.');
    } finally {
      setProposing(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading wave pool…
      </div>
    );
  }

  if (!pool) return null;

  const { returned_walkers, unassigned_routes, wave_summary } = pool;
  const waveKeys = Object.keys(wave_summary.waves).sort();

  return (
    <div className="space-y-4 pt-2">
      {/* Wave progress summary */}
      {waveKeys.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Wave progress</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {waveKeys.map(wk => {
              const counts = wave_summary.waves[wk];
              const done = counts.completed;
              const total = counts.assigned + counts.in_progress + counts.completed + counts.unassigned;
              const pct = total > 0 ? Math.round((done / total) * 100) : 0;
              return (
                <div key={wk} className="p-2 rounded-lg bg-accent/50 space-y-1">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase">Wave {wk}</p>
                  <div className="h-1 bg-border rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${pct === 100 ? 'bg-success' : 'bg-primary'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    {done}/{total} complete · {counts.in_progress} active
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Returned walkers */}
      {returned_walkers.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
              <ArrowRightLeft className="w-3.5 h-3.5" /> Returned walkers
            </p>
            <span className="text-xs text-success font-medium">{returned_walkers.length} available</span>
          </div>
          <div className="space-y-1">
            {returned_walkers.map(w => (
              <div key={w.employee_id} className="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg bg-success/5 border border-success/20">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs font-medium text-foreground truncate">{w.employee_name}</span>
                  {w.injury_status && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-warning/10 text-warning font-medium shrink-0">
                      {w.injury_status}
                    </span>
                  )}
                </div>
                <span className="text-[10px] text-muted-foreground shrink-0">
                  {w.completed_routes.map(r => `#${r.route_number}`).join(', ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unassigned pool */}
      {unassigned_routes.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-warning" /> Unassigned pool
            <span className="text-warning font-medium">({unassigned_routes.length})</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {unassigned_routes
              .slice()
              .sort((a, b) => a.route_number - b.route_number)
              .map(r => (
                <div key={r.route_id} className="flex items-center gap-1 px-2 py-1 rounded-lg border border-border bg-accent/40 text-xs">
                  <span className="font-semibold text-foreground">#{r.route_number}</span>
                  <EffortBadge effort={r.effort_class} />
                  <span className="text-muted-foreground">{r.package_count}p</span>
                </div>
              ))}
          </div>

          {/* Auto-propose button */}
          {returned_walkers.length > 0 && (
            <div className="space-y-1.5">
              <button
                onClick={handleAutoPropose}
                disabled={proposing}
                className="btn-primary flex items-center gap-1.5 text-sm"
              >
                {proposing
                  ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Proposing…</>
                  : <><Shuffle className="w-3.5 h-3.5" /> Auto-propose second wave</>}
              </button>
              {propError && (
                <p className="text-xs text-warning flex items-start gap-1">
                  <CircleAlert className="w-3.5 h-3.5 shrink-0 mt-0.5" />{propError}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {unassigned_routes.length === 0 && returned_walkers.length === 0 && (
        <p className="text-xs text-muted-foreground py-1">No walkers returned yet — pool is empty.</p>
      )}

      <button
        onClick={() => { setLoading(true); fetchPool(); }}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <RefreshCw className="w-3 h-3" /> Refresh pool
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Proposal review panel — trainer confirms or edits auto-proposed assignments
// ---------------------------------------------------------------------------

function ProposalReviewPanel({
  taId,
  routeDate,
  proposal,
  walkers,
  onConfirm,
  onDiscard,
}: {
  taId: string;
  routeDate: string;
  proposal: ProposedAssignmentEntry[];
  walkers: { id: string; name: string; role: string }[];
  onConfirm: (taId: string, assignments: WaveAssignmentEntry[]) => Promise<void>;
  onDiscard: () => void;
}) {
  const [overrides, setOverrides] = useState<Record<number, string>>(() =>
    Object.fromEntries(proposal.map(p => [p.route_number, p.employee_id]))
  );
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setConfirming(true);
    setError(null);
    try {
      const assignments: WaveAssignmentEntry[] = Object.entries(overrides)
        .filter(([, eid]) => eid)
        .map(([rn, eid]) => ({ route_number: Number(rn), employee_id: eid }));
      await onConfirm(taId, assignments);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Confirm failed.');
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-3 p-3 bg-info/5 border border-info/20 rounded-xl">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-info uppercase tracking-widest">Review proposed assignments</p>
        <button onClick={onDiscard} className="text-xs text-muted-foreground hover:text-foreground">Discard</button>
      </div>
      <p className="text-xs text-muted-foreground">Edit any assignment before confirming. Auto-proposed rows are highlighted.</p>

      <div className="space-y-1.5">
        {proposal.map(p => (
          <div key={p.route_number} className={`flex items-center gap-2 p-2 rounded-lg border ${p.auto_proposed ? 'bg-info/5 border-info/20' : 'bg-background border-border'}`}>
            <span className="text-xs font-semibold text-foreground w-8 shrink-0">#{p.route_number}</span>
            <EffortBadge effort={p.effort_class} />
            <select
              value={overrides[p.route_number] ?? ''}
              onChange={e => setOverrides(prev => ({ ...prev, [p.route_number]: e.target.value }))}
              className="flex-1 text-xs border border-border rounded-lg px-2 py-1 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
            >
              <option value="">Unassign…</option>
              {walkers.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
            {p.auto_proposed && (
              <span className="text-[10px] text-info shrink-0">auto</span>
            )}
          </div>
        ))}
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      <button
        onClick={handleConfirm}
        disabled={confirming}
        className="btn-primary w-full flex items-center justify-center gap-1.5 text-sm"
      >
        {confirming
          ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Sending…</>
          : <><Send className="w-3.5 h-3.5" /> Confirm wave assignments</>}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Route card (minimal, for sort panel)
// ---------------------------------------------------------------------------

function RouteCard({
  route,
  assignedName,
  onAssign,
  walkers,
}: {
  route: RouteResponse;
  assignedName: string | null;
  onAssign: (routeNumber: number, employeeId: string) => void;
  walkers: Employee[];
}) {
  const [expanded, setExpanded] = useState(false);
  const slotPct = Math.min(100, Math.round((route.slot_cost / route.capacity_limit) * 100));
  const barColor = slotPct >= 90 ? 'bg-danger' : slotPct >= 70 ? 'bg-warning' : 'bg-success';

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2.5">
        <span className="text-sm font-semibold text-foreground w-7 shrink-0">#{route.route_number}</span>
        <EffortBadge effort={route.effort_class} />
        <span className="text-xs text-muted-foreground">{route.package_count} pkgs</span>
        <span className="text-xs text-muted-foreground">{route.tote_ids.length} totes</span>

        <div className="flex-1 min-w-0 mx-1">
          <div className="h-1.5 bg-accent rounded-full overflow-hidden">
            <div className={`h-full rounded-full ${barColor}`} style={{ width: `${slotPct}%` }} />
          </div>
        </div>
        <span className="text-xs text-muted-foreground w-10 text-right shrink-0">{route.slot_cost}/{route.capacity_limit}</span>

        {route.misrouted_packages.length > 0 && (
          <AlertTriangle className="w-3.5 h-3.5 text-warning shrink-0" />
        )}

        <button onClick={() => setExpanded(o => !o)} className="text-muted-foreground hover:text-foreground ml-1 shrink-0">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {/* Assign dropdown */}
      <div className="px-3 pb-2.5 flex items-center gap-2">
        <UserCheck className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        <select
          value={route.assigned_to ?? ''}
          onChange={e => { if (e.target.value) onAssign(route.route_number, e.target.value); }}
          className="flex-1 text-xs border border-border rounded-lg px-2 py-1 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
        >
          <option value="">Assign walker…</option>
          {walkers.map(w => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </select>
        {assignedName && (
          <span className="text-xs font-medium text-foreground shrink-0 max-w-[100px] truncate">{assignedName}</span>
        )}
      </div>

      {expanded && (
        <div className="border-t border-border px-3 py-2.5 space-y-2 bg-surface/40">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">Blocks</p>
            <div className="flex flex-wrap gap-1">
              {route.block_keys.map(k => (
                <span key={k} className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-accent rounded text-[11px] text-foreground font-mono">
                  <MapPin className="w-2.5 h-2.5 text-muted-foreground" />{k}
                </span>
              ))}
            </div>
          </div>
          {route.misrouted_packages.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-warning font-semibold mb-1">Misroutes</p>
              {route.misrouted_packages.map(m => (
                <div key={m.tba_number} className="text-xs text-muted-foreground font-mono">
                  {m.tba_number} → {m.destination_block_key ?? 'unknown'}
                </div>
              ))}
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
  onReady: () => void;
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
          onReady();
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
    phase === 'idle'      ? "Upload the Amazon manifest CSV for today's sort." :
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
          <p className="text-sm font-semibold text-foreground">Upload Production Manifest</p>
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
            <div className="space-y-2">
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
              <p className="text-xs text-muted-foreground">Use the truck panels below to commit routes.</p>
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
// Manifest sort panel — POST /sort/run, tier-1 review, override, resubmit
// ---------------------------------------------------------------------------

type SortRunPhase = 'idle' | 'running' | 'tier1_failed' | 'done';

const _SORT_POLL_INTERVAL = 3_000;   // 3 s between status checks

function ManifestSortPanel({
  today,
  trucks,           // TruckAssignment[] for name lookup
  onZonesCreated,   // called after zones are persisted so truck panels can enable
}: {
  today: string;
  trucks: { truck_id: string; truck_name: string }[];
  onZonesCreated: () => void;
}) {
  const [phase, setPhase]               = useState<SortRunPhase>('idle');
  const [result, setResult]             = useState<SortRunResponse | null>(null);
  const [error, setError]               = useState<string | null>(null);
  const [expanded, setExpanded]         = useState(false);
  const [running, setRunning]           = useState(false);
  // override map: bag_id → truck_id (dispatch confirmed or manually chosen)
  const [overrideMap, setOverrideMap]   = useState<Record<string, string>>({});
  const pollRef                         = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => () => stopPoll(), []);

  const truckById = Object.fromEntries(trucks.map(t => [t.truck_id, t.truck_name]));

  const classificationColor = (c: string) =>
    c === 'misaligned' ? 'text-danger'
    : c === 'uncertain' ? 'text-warning'
    : c === 'stray'     ? 'text-warning/70'
    : 'text-success';

  const classificationBg = (c: string) =>
    c === 'misaligned' ? 'bg-danger/5 border-danger/20'
    : c === 'uncertain' ? 'bg-warning/5 border-warning/20'
    : 'bg-accent/40 border-border';

  function handleStatusPayload(data: SortRunStatusResponse) {
    if (data.status === 'done') {
      const synth: SortRunResponse = {
        sort_date:     data.sort_date!,
        package_count: data.package_count!,
        outlier_count: data.outlier_count!,
        cluster_count: data.cluster_count!,
        tier1_passed:  data.tier1_passed!,
        was_forced:    data.was_forced!,
        zones_created: data.zones_created!,
        assignments:   data.assignments,
        flagged_bags:  [],
      };
      setResult(synth);
      setPhase('done');
      setExpanded(false);
      setRunning(false);
      onZonesCreated();
    } else if (data.status === 'tier1_failed') {
      const synth: SortRunResponse = {
        sort_date:     today,
        package_count: 0,
        outlier_count: 0,
        cluster_count: 0,
        tier1_passed:  false,
        was_forced:    false,
        zones_created: 0,
        assignments:   [],
        flagged_bags:  data.flagged_bags,
      };
      const suggestions: Record<string, string> = {};
      for (const bag of data.flagged_bags) {
        if (bag.suggested_truck_id) suggestions[bag.bag_id] = bag.suggested_truck_id;
      }
      setResult(synth);
      setOverrideMap(suggestions);
      setPhase('tier1_failed');
      setExpanded(true);
      setRunning(false);
    } else if (data.status === 'error') {
      setError(data.detail ?? 'Sort failed.');
      setPhase('idle');
      setRunning(false);
    }
    // status === 'running' → keep polling
  }

  async function runSort(force: boolean, overrides: BagOverride[]) {
    setRunning(true);
    setError(null);
    stopPoll();
    try {
      const { data: accepted } = await axiosClient.post<SortRunAccepted>('/sort/run', {
        sort_date: today,
        force,
        overrides,
      });
      const taskId = accepted.task_id;

      // Poll status until terminal
      pollRef.current = setInterval(async () => {
        try {
          const { data } = await axiosClient.get<SortRunStatusResponse>(
            `/sort/run/status/${taskId}`,
            { params: { sort_date: today } },
          );
          if (data.status !== 'running') {
            stopPoll();
            handleStatusPayload(data);
          }
        } catch {
          // transient network hiccup — keep polling
        }
      }, _SORT_POLL_INTERVAL);
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
    runSort(false, []);
  }

  function handleConfirmOverrides() {
    const overrides: BagOverride[] = Object.entries(overrideMap)
      .filter(([, truck_id]) => truck_id)
      .map(([bag_id, truck_id]) => ({ bag_id, truck_id }));
    runSort(true, overrides);
  }

  const borderClass =
    phase === 'done'         ? 'border-success/40 bg-success/5'
    : phase === 'tier1_failed' ? 'border-warning/40 bg-warning/5'
    : phase === 'running'    ? 'border-primary/40 bg-primary/5'
    : error                  ? 'border-danger/40 bg-danger/5'
    : 'border-border bg-surface-muted/30';

  const headerSubtext =
    phase === 'idle'         ? 'Run DBSCAN zone sort and verify bag placements.'
    : phase === 'running'    ? 'Clustering packages and assigning truck zones…'
    : phase === 'tier1_failed' ? `${result?.flagged_bags.length ?? 0} bag(s) flagged — review and confirm below.`
    : phase === 'done'       ? `Zones created: ${result?.zones_created ?? 0} · ${result?.package_count.toLocaleString()} packages sorted.`
    : (error ?? 'Sort failed.');

  return (
    <div className={`rounded-2xl border overflow-hidden transition-colors ${borderClass}`}>
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-black/5 transition-colors text-left"
        onClick={() => setExpanded(v => !v)}
      >
        {phase === 'running'
          ? <Loader2 className="w-5 h-5 text-primary animate-spin shrink-0" />
          : phase === 'tier1_failed'
          ? <AlertTriangle className="w-5 h-5 text-warning shrink-0" />
          : phase === 'done'
          ? <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
          : error
          ? <AlertTriangle className="w-5 h-5 text-danger shrink-0" />
          : <Layers className="w-5 h-5 text-muted-foreground shrink-0" />}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">Zone Sort</p>
          <p className={`text-xs truncate ${
            phase === 'tier1_failed' ? 'text-warning'
            : phase === 'done' ? 'text-success'
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
            <button
              onClick={handleInitialRun}
              disabled={running}
              className="btn-primary flex items-center gap-2 text-sm"
            >
              <Zap className="w-4 h-4" /> Run Zone Sort
            </button>
          )}

          {/* Running */}
          {phase === 'running' && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
              Clustering and assigning zones…
            </div>
          )}

          {/* Done — summary */}
          {phase === 'done' && result && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {result.assignments.map(a => (
                  <div key={a.truck_id} className="p-2 rounded-lg bg-accent/50 space-y-0.5">
                    <p className="text-[10px] text-muted-foreground uppercase font-semibold truncate">{a.truck_name}</p>
                    <p className="text-xs font-semibold text-foreground">{a.package_count.toLocaleString()} pkgs</p>
                    <p className="text-[10px] text-muted-foreground capitalize">{a.match_type}</p>
                  </div>
                ))}
              </div>
              {result.outlier_count > 0 && (
                <p className="text-xs text-warning flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  {result.outlier_count} packages are DBSCAN outliers — no zone assigned.
                </p>
              )}
              <button
                onClick={() => { setPhase('idle'); setResult(null); setError(null); setOverrideMap({}); }}
                className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
              >
                Re-run sort
              </button>
            </div>
          )}

          {/* Tier-1 failed — per-bag review with override selects */}
          {phase === 'tier1_failed' && result && (
            <div className="space-y-4">
              <p className="text-xs text-muted-foreground">
                The bags below contain packages that DBSCAN assigned to a different truck
                than the majority of the bag. Confirm the suggested truck or select a different
                one, then click <strong>Confirm &amp; Force Sort</strong>.
              </p>

              <div className="space-y-2">
                {result.flagged_bags.map(bag => (
                  <div
                    key={bag.bag_id}
                    className={`p-3 rounded-xl border space-y-2 ${classificationBg(bag.classification)}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="space-y-0.5 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold font-mono text-foreground">{bag.bag_id}</span>
                          <span className={`text-[10px] font-semibold uppercase ${classificationColor(bag.classification)}`}>
                            {bag.classification}
                          </span>
                        </div>
                        <p className="text-[10px] text-muted-foreground">
                          {bag.outside_packages}/{bag.total_packages} packages on wrong truck
                          {bag.inferred_truck_id && ` · currently on ${truckById[bag.inferred_truck_id] ?? bag.inferred_truck_id}`}
                        </p>
                      </div>
                      {bag.unresolvable && (
                        <span className="text-[10px] text-danger font-semibold shrink-0">Unresolvable</span>
                      )}
                    </div>

                    {!bag.unresolvable && (
                      <div className="flex items-center gap-2">
                        <label className="text-[10px] text-muted-foreground shrink-0">Move to:</label>
                        <select
                          value={overrideMap[bag.bag_id] ?? ''}
                          onChange={e => setOverrideMap(prev => ({ ...prev, [bag.bag_id]: e.target.value }))}
                          className="flex-1 text-xs border border-border rounded-lg px-2 py-1 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                        >
                          <option value="">Leave as-is…</option>
                          {trucks.map(t => (
                            <option key={t.truck_id} value={t.truck_id}>
                              {t.truck_name}
                              {t.truck_id === bag.suggested_truck_id ? ' (suggested)' : ''}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                    {bag.outlier_tbas.length > 0 && (
                      <p className="text-[10px] text-muted-foreground">
                        {bag.outlier_tbas.length} TBA(s) are DBSCAN outliers — no truck can be suggested.
                      </p>
                    )}
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={handleConfirmOverrides}
                  disabled={running}
                  className="btn-primary flex items-center gap-2 text-sm flex-1 justify-center"
                >
                  {running
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Applying…</>
                    : <><Send className="w-4 h-4" /> Confirm &amp; Force Sort</>}
                </button>
                <button
                  onClick={() => { setPhase('idle'); setResult(null); setOverrideMap({}); }}
                  className="btn-ghost text-sm px-3"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Truck sort panel
// ---------------------------------------------------------------------------

function TruckSortPanel({
  state,
  walkers,
  trainers,
  routeDate,
  zoneExists,
  onCommit,
  onDistribute,
  onArrivalConfirm,
  onRefresh,
}: {
  state: TruckSortState;
  walkers: Employee[];
  trainers: Employee[];
  routeDate: string;
  zoneExists: boolean;
  onCommit: (taId: string) => Promise<void>;
  onDistribute: (taId: string, assignments: WaveAssignmentEntry[], trainerId: string, traineeId?: string, traineePhase?: number) => Promise<void>;
  onArrivalConfirm: (taId: string, trainerId: string, traineeId: string) => Promise<void>;
  onRefresh: (taId: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [commitLoading, setCommitLoading] = useState(false);
  const [distributeLoading, setDistributeLoading] = useState(false);
  const [arrivalLoading, setArrivalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Wave assignment map: route_number → employee_id
  const [waveMap, setWaveMap] = useState<Record<number, string>>({});

  // First-wave auto-propose state
  const [firstWaveProposal, setFirstWaveProposal] = useState<ProposedAssignmentEntry[] | null>(null);
  const [firstWaveProposing, setFirstWaveProposing] = useState(false);

  // Second-wave auto-propose state
  const [secondWaveProposal, setSecondWaveProposal] = useState<ProposedAssignmentEntry[] | null>(null);
  const [selectedTrainerId, setSelectedTrainerId] = useState('');
  const [selectedTraineeId, setSelectedTraineeId] = useState('');
  const [traineePhase, setTraineePhase] = useState<number>(1);

  // Arrival confirm fields
  const [arrivalTrainerId, setArrivalTrainerId] = useState('');
  const [arrivalTraineeId, setArrivalTraineeId] = useState('');

  // Sync waveMap when routes change
  useEffect(() => {
    setWaveMap(prev => {
      const next = { ...prev };
      state.routes.forEach(r => {
        if (r.assigned_to && !next[r.route_number]) next[r.route_number] = r.assigned_to;
      });
      return next;
    });
  }, [state.routes]);

  const handleCommit = async () => {
    setError(null);
    setCommitLoading(true);
    try { await onCommit(state.ta.id); }
    catch (e: any) { setError(e?.response?.data?.detail ?? 'Commit failed.'); }
    finally { setCommitLoading(false); }
  };

  const handleFirstWaveAutoPropose = async () => {
    setError(null);
    setFirstWaveProposing(true);
    try {
      const { data } = await axiosClient.post<WaveDistributionProposal>(
        '/walker-routes/wave-distribution',
        { truck_assignment_id: state.ta.id, route_date: routeDate, auto_assign: true },
      );
      setFirstWaveProposal(data.proposed_assignments);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Auto-propose failed.');
    } finally {
      setFirstWaveProposing(false);
    }
  };

  const handleFirstWaveProposalConfirm = (proposed: ProposedAssignmentEntry[]) => {
    setWaveMap(prev => {
      const next = { ...prev };
      proposed.forEach(p => { next[p.route_number] = p.employee_id; });
      return next;
    });
    setFirstWaveProposal(null);
  };

  const handleDistribute = async () => {
    setError(null);
    const assignments = Object.entries(waveMap)
      .filter(([, eid]) => eid)
      .map(([rn, eid]) => ({ route_number: Number(rn), employee_id: eid }));
    if (assignments.length === 0) { setError('Assign at least one route before distributing.'); return; }
    if (!selectedTrainerId) { setError('Select a trainer.'); return; }
    setDistributeLoading(true);
    try {
      await onDistribute(
        state.ta.id,
        assignments,
        selectedTrainerId,
        selectedTraineeId || undefined,
        selectedTraineeId ? traineePhase : undefined,
      );
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Wave distribution failed.');
    } finally {
      setDistributeLoading(false);
    }
  };

  const handleArrival = async () => {
    setError(null);
    if (!arrivalTrainerId || !arrivalTraineeId) { setError('Select trainer and trainee.'); return; }
    setArrivalLoading(true);
    try { await onArrivalConfirm(state.ta.id, arrivalTrainerId, arrivalTraineeId); }
    catch (e: any) { setError(e?.response?.data?.detail ?? 'Arrival confirmation failed.'); }
    finally { setArrivalLoading(false); }
  };

  const phaseComplete = state.phase === 'arrived';
  const pkgCount = state.routes.reduce((s, r) => s + r.tba_numbers.length, 0);

  return (
    <div className="card-elevated">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 p-4 hover:bg-accent/20 transition-colors rounded-xl text-left"
      >
        <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-primary/10 shrink-0">
          <Layers className="w-4.5 h-4.5 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">{state.ta.truck_name}</p>
          <p className="text-xs text-muted-foreground">
            {state.phase === 'idle' && 'Not committed'}
            {state.phase === 'committed' && `${state.routes.length} routes · ${pkgCount} pkgs — awaiting distribution`}
            {state.phase === 'distributed' && `${state.routes.length} routes assigned — awaiting arrival confirm`}
            {state.phase === 'arrived' && `${state.routes.length} routes · rebalance complete`}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {phaseComplete
            ? <CheckCircle2 className="w-4 h-4 text-success" />
            : state.phase !== 'idle'
            ? <span className="w-2 h-2 rounded-full bg-warning animate-pulse" />
            : null}
          {open ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
        </div>
      </button>

      {open && (
        <div className="border-t border-border px-4 pb-4 pt-3 space-y-5">
          {error && (
            <div className="p-3 bg-danger/5 border border-danger/20 rounded-xl text-sm text-danger">{error}</div>
          )}

          {/* ── Step 1: Commit ── */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Step 1 — Commit sort
              </p>
              {state.phase !== 'idle' && <CheckCircle2 className="w-4 h-4 text-success" />}
            </div>
            {state.phase === 'idle' ? (
              zoneExists ? (
                <button
                  onClick={handleCommit}
                  disabled={commitLoading}
                  className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
                >
                  {commitLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  {commitLoading ? 'Committing sort…' : 'Commit Sort'}
                </button>
              ) : (
                <div className="flex items-center gap-2 p-3 rounded-xl bg-accent/40 border border-border text-xs text-muted-foreground">
                  <Layers className="w-3.5 h-3.5 shrink-0" />
                  Run Zone Sort above to assign packages to this truck before committing.
                </div>
              )
            ) : (
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">
                  {state.routes.length} routes committed · {pkgCount} packages
                </div>
                {state.packages_dropped > 0 && (
                  <div className="flex items-center gap-1.5 text-xs text-warning">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    {state.packages_dropped} package{state.packages_dropped === 1 ? '' : 's'} dropped — TBAs not found in enriched manifest. Check notifications.
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Step 2: Assign routes ── */}
          {state.phase !== 'idle' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  Step 2 — Assign routes to staff
                </p>
                {state.phase !== 'committed' && <CheckCircle2 className="w-4 h-4 text-success" />}
              </div>

              {/* Routes */}
              <div className="space-y-2">
                {state.routes
                  .slice()
                  .sort((a, b) => a.route_number - b.route_number)
                  .map(r => (
                    <RouteCard
                      key={r.id}
                      route={r}
                      assignedName={
                        waveMap[r.route_number]
                          ? (walkers.find(w => w.id === waveMap[r.route_number])?.name ?? null)
                          : null
                      }
                      onAssign={(rn, eid) => setWaveMap(prev => ({ ...prev, [rn]: eid }))}
                      walkers={walkers}
                    />
                  ))}
              </div>

              {/* Trainer / trainee */}
              {state.phase === 'committed' && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Trainer</label>
                    <select
                      value={selectedTrainerId}
                      onChange={e => setSelectedTrainerId(e.target.value)}
                      className="w-full text-xs border border-border rounded-lg px-2 py-1.5 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                    >
                      <option value="">Select trainer…</option>
                      {trainers.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Trainee (optional)</label>
                    <select
                      value={selectedTraineeId}
                      onChange={e => setSelectedTraineeId(e.target.value)}
                      className="w-full text-xs border border-border rounded-lg px-2 py-1.5 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                    >
                      <option value="">No trainee</option>
                      {walkers.filter(w => w.role === 'trainee').map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                    </select>
                  </div>
                  {selectedTraineeId && (
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">Trainee phase</label>
                      <select
                        value={traineePhase}
                        onChange={e => setTraineePhase(Number(e.target.value))}
                        className="w-full text-xs border border-border rounded-lg px-2 py-1.5 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                      >
                        {[1, 2, 3, 4, 5].map(p => <option key={p} value={p}>Phase {p}</option>)}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {state.phase === 'committed' && firstWaveProposal && (
                <div className="space-y-2 p-3 bg-info/5 border border-info/20 rounded-xl">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-info uppercase tracking-widest">Auto-proposed assignments</p>
                    <button onClick={() => setFirstWaveProposal(null)} className="text-xs text-muted-foreground hover:text-foreground">Discard</button>
                  </div>
                  <p className="text-xs text-muted-foreground">Review and accept — assignments are applied to the route cards above.</p>
                  <div className="space-y-1">
                    {firstWaveProposal.map(p => (
                      <div key={p.route_number} className="flex items-center gap-2 text-xs">
                        <span className="font-semibold text-foreground w-8">#{p.route_number}</span>
                        <EffortBadge effort={p.effort_class} />
                        <span className="text-foreground">{p.employee_name}</span>
                        {p.auto_proposed && <span className="text-info text-[10px]">auto</span>}
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() => handleFirstWaveProposalConfirm(firstWaveProposal)}
                    className="btn-primary w-full text-sm"
                  >
                    Accept proposals
                  </button>
                </div>
              )}

              {state.phase === 'committed' && (
                <div className="flex gap-2">
                  <button
                    onClick={handleFirstWaveAutoPropose}
                    disabled={firstWaveProposing || !!firstWaveProposal}
                    className="btn-secondary flex items-center justify-center gap-2 text-sm flex-1"
                  >
                    {firstWaveProposing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                    {firstWaveProposing ? 'Proposing…' : 'Auto-propose'}
                  </button>
                  <button
                    onClick={handleDistribute}
                    disabled={distributeLoading}
                    className="btn-primary flex items-center justify-center gap-2 text-sm flex-1"
                  >
                    {distributeLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Shuffle className="w-4 h-4" />}
                    {distributeLoading ? 'Distributing…' : 'Send Wave'}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ── Step 3: Arrival confirm ── */}
          {state.phase === 'distributed' && (
            <div className="space-y-3">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Step 3 — Arrival confirmation
              </p>
              <p className="text-xs text-muted-foreground">
                Confirm trainer and trainee are both physically present at the anchor point to trigger the 1.5× rebalance.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Trainer present</label>
                  <select
                    value={arrivalTrainerId}
                    onChange={e => setArrivalTrainerId(e.target.value)}
                    className="w-full text-xs border border-border rounded-lg px-2 py-1.5 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                  >
                    <option value="">Select trainer…</option>
                    {trainers.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Trainee present</label>
                  <select
                    value={arrivalTraineeId}
                    onChange={e => setArrivalTraineeId(e.target.value)}
                    className="w-full text-xs border border-border rounded-lg px-2 py-1.5 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                  >
                    <option value="">Select trainee…</option>
                    {walkers.filter(w => w.role === 'trainee').map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </div>
              </div>
              <button
                onClick={handleArrival}
                disabled={arrivalLoading}
                className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
              >
                {arrivalLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <UserCheck className="w-4 h-4" />}
                {arrivalLoading ? 'Confirming…' : 'Confirm Arrival & Rebalance'}
              </button>
            </div>
          )}

          {/* ── Arrival rebalance result ── */}
          {state.rebalanceResult && !state.rebalanceResult.sort_not_yet_committed && (
            <div className="space-y-1.5 p-3 bg-success/5 border border-success/20 rounded-xl">
              <p className="text-xs font-semibold uppercase tracking-widest text-success flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5" /> Rebalance complete — capacity {state.rebalanceResult.paired_capacity_limit} half-slots
              </p>
              {state.rebalanceResult.absorbed_route_numbers.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Absorbed routes: {state.rebalanceResult.absorbed_route_numbers.map(n => `#${n}`).join(', ')}
                </p>
              )}
              {state.rebalanceResult.trimmed_route_numbers.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Trimmed routes: {state.rebalanceResult.trimmed_route_numbers.map(n => `#${n}`).join(', ')}
                </p>
              )}
            </div>
          )}
          {state.rebalanceResult?.sort_not_yet_committed && (
            <div className="p-3 bg-info/5 border border-info/20 rounded-xl">
              <p className="text-xs text-muted-foreground">
                Arrival recorded — paired capacity will apply when sort is committed.
              </p>
            </div>
          )}

          {/* ── Unassigned misroutes ── */}
          {state.unassigned_misroutes.length > 0 && (
            <div className="p-3 bg-warning/5 border border-warning/20 rounded-xl">
              <p className="text-xs font-semibold text-warning mb-2 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                {state.unassigned_misroutes.length} unresolved misroutes
              </p>
              {state.unassigned_misroutes.map(m => (
                <div key={m.tba_number} className="text-xs text-muted-foreground font-mono">{m.tba_number}</div>
              ))}
            </div>
          )}

          {/* ── Second-wave pool (visible once routes are distributed) ── */}
          {(state.phase === 'distributed' || state.phase === 'arrived') && (
            <div className="space-y-3 border-t border-border pt-4">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Second-wave pool
              </p>

              {/* Proposal review — shown after auto-propose */}
              {secondWaveProposal ? (
                <ProposalReviewPanel
                  taId={state.ta.id}
                  routeDate={routeDate}
                  proposal={secondWaveProposal}
                  walkers={walkers}
                  onConfirm={async (taId, assignments) => {
                    await onDistribute(taId, assignments, '', undefined, undefined);
                    setSecondWaveProposal(null);
                    await onRefresh(taId);
                  }}
                  onDiscard={() => setSecondWaveProposal(null)}
                />
              ) : (
                <WavePoolPanel
                  taId={state.ta.id}
                  routeDate={routeDate}
                  walkers={walkers}
                  onSecondWavePropose={(_taId, proposed) => setSecondWaveProposal(proposed)}
                />
              )}
            </div>
          )}

          <button
            onClick={() => onRefresh(state.ta.id)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SortPage() {
  const today = getLocalYMD();
  const [assignments, setAssignments] = useState<TruckAssignment[]>([]);
  const [truckStates, setTruckStates] = useState<TruckSortState[]>([]);
  const [walkers, setWalkers] = useState<Employee[]>([]);
  const [trainers, setTrainers] = useState<Employee[]>([]);
  const [zones, setZones] = useState<ZonePolygon[]>([]);
  const [centroids, setCentroids] = useState<Centroid[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // truck_id set that have an active TruckZone for today — populated after zone sort runs
  const [zonedTruckIds, setZonedTruckIds] = useState<Set<string>>(new Set());

  const buildInitialState = (ta: TruckAssignment, routes: RouteResponse[], resp?: CommitSortResponse): TruckSortState => {
    const phase: SortPhase =
      routes.length === 0 ? 'idle'
      : routes.some(r => r.status !== 'unassigned') ? 'distributed'
      : 'committed';
    return {
      ta,
      phase,
      routes,
      unassigned_misroutes: resp?.unassigned_misroutes ?? [],
      packages_sorted: resp?.packages_sorted ?? routes.reduce((s, r) => s + r.tba_numbers.length, 0),
      packages_dropped: resp?.packages_dropped ?? 0,
      dropped_tbas: resp?.dropped_tbas ?? [],
      rebalanceResult: null,
    };
  };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taRes, empRes, zoneRes, centroidRes] = await Promise.allSettled([
        axiosClient.get<TruckAssignment[]>('/assignments/', { params: { date: today } }),
        axiosClient.get<Employee[]>('/employees/', { params: { is_active: true } }),
        axiosClient.get<{ zones: ZonePolygon[] }>(`/sort/${today}`),
        axiosClient.get<{ centroids: Centroid[] }>(`/sort/${today}/centroids`),
      ]);
      // Unpack settled results — zones/centroids fail silently if sort hasn't run yet
      if (zoneRes.status === 'fulfilled') {
        const fetchedZones = zoneRes.value.data.zones ?? [];
        setZones(fetchedZones);
        setZonedTruckIds(new Set(fetchedZones.map((z: ZonePolygon) => z.truck_id)));
      }
      if (centroidRes.status === 'fulfilled') setCentroids(centroidRes.value.data.centroids ?? []);
      if (taRes.status === 'rejected') throw taRes.reason;
      if (empRes.status === 'rejected') throw empRes.reason;
      // Re-assign for downstream use
      const taResVal = taRes.value;
      const empResVal = empRes.value;
      const tas = taResVal.data;
      const emps = empResVal.data;
      setAssignments(tas);
      setWalkers(emps.filter(e => ['walker', 'trainee', 'trainer'].includes(e.role)));
      setTrainers(emps.filter(e => e.role === 'trainer'));

      const states = await Promise.all(tas.map(async ta => {
        try {
          const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/${ta.id}/routes`);
          return buildInitialState(ta, r.data);
        } catch {
          return buildInitialState(ta, []);
        }
      }));
      setTruckStates(states);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to load data.');
    } finally {
      setLoading(false);
    }
  }, [today]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const updateState = (taId: string, patch: Partial<TruckSortState>) => {
    setTruckStates(prev => prev.map(s => s.ta.id === taId ? { ...s, ...patch } : s));
  };

  const handleCommit = async (taId: string) => {
    const res = await axiosClient.post<CommitSortResponse>('/walker-routes/commit-sort', {
      truck_assignment_id: taId,
      route_date: today,
      ovs: [],
    });
    updateState(taId, {
      phase: 'committed',
      routes: res.data.routes,
      unassigned_misroutes: res.data.unassigned_misroutes,
      packages_sorted: res.data.packages_sorted,
      packages_dropped: res.data.packages_dropped,
      dropped_tbas: res.data.dropped_tbas,
    });
    // Refresh centroids after commit — route_sort persists new centroids
    axiosClient.get<{ centroids: Centroid[] }>(`/sort/${today}/centroids`)
      .then(r => setCentroids(r.data.centroids ?? []))
      .catch(() => {});
  };

  const handleDistribute = async (
    taId: string,
    assignments: WaveAssignmentEntry[],
    trainerId: string,
    traineeId?: string,
    traineePhase?: number,
  ) => {
    await axiosClient.post('/walker-routes/wave-distribution', {
      truck_assignment_id: taId,
      route_date: today,
      assignments,
      trainer_id: trainerId,
      trainee_id: traineeId ?? null,
      trainee_phase: traineePhase ?? null,
    });
    const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/${taId}/routes`);
    updateState(taId, { phase: 'distributed', routes: r.data });
  };

  const handleArrivalConfirm = async (taId: string, trainerId: string, traineeId: string) => {
    const res = await axiosClient.post<ArrivalConfirmResponse>('/walker-routes/arrival-confirm', {
      truck_assignment_id: taId,
      route_date: today,
      trainer_id: trainerId,
      trainee_id: traineeId,
    });
    const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/${taId}/routes`);
    updateState(taId, {
      phase: 'arrived',
      routes: r.data,
      rebalanceResult: res.data,
    });
  };

  const handleRefresh = async (taId: string) => {
    const ta = assignments.find(a => a.id === taId);
    if (!ta) return;
    try {
      const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/${taId}/routes`);
      updateState(taId, buildInitialState(ta, r.data));
    } catch { /* ignore */ }
  };

  // Aggregate stats
  const totalRoutes = truckStates.reduce((s, st) => s + st.routes.length, 0);
  const totalPkgs = truckStates.reduce((s, st) => s + st.packages_sorted, 0);
  const unassignedRoutes = truckStates.reduce((s, st) => s + st.routes.filter(r => r.status === 'unassigned').length, 0);
  const misrouteCount = truckStates.reduce((s, st) => s + st.routes.reduce((rs, r) => rs + r.misrouted_packages.length, 0) + st.unassigned_misroutes.length, 0);

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        eyebrow="Station Operations"
        title="Station Sort"
        description={`Upload manifest, assign packages to truck zones, and commit routes for ${new Date(today + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
        actions={
          <button onClick={fetchAll} className="btn-ghost flex items-center gap-1.5 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh all
          </button>
        }
      />

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Routes" value={loading ? '—' : totalRoutes} icon={Route} tone="primary" delay={0} />
        <StatCard label="Packages" value={loading ? '—' : totalPkgs} icon={Package} tone="info" delay={0.05} />
        <StatCard label="Unassigned" value={loading ? '—' : unassignedRoutes} icon={Users} tone={unassignedRoutes > 0 ? 'warning' : 'success'} delay={0.1} />
        <StatCard label="Misroutes" value={loading ? '—' : misrouteCount} icon={AlertTriangle} tone={misrouteCount > 0 ? 'warning' : 'success'} delay={0.15} />
      </div>

      {error && (
        <div className="p-4 bg-danger/5 border border-danger/20 rounded-xl text-sm text-danger">{error}</div>
      )}

      {/* Manifest upload */}
      <ManifestUploadPanel today={today} onReady={fetchAll} />

      {/* Zone sort — only shown when manifest is ready (manifest panel handles its own state) */}
      {assignments.length > 0 && (
        <ManifestSortPanel
          today={today}
          trucks={assignments.map(a => ({ truck_id: a.truck_id, truck_name: a.truck_name }))}
          onZonesCreated={() => {
            // Re-fetch zones so zonedTruckIds updates and map refreshes
            Promise.allSettled([
              axiosClient.get<{ zones: ZonePolygon[] }>(`/sort/${today}`),
              axiosClient.get<{ centroids: Centroid[] }>(`/sort/${today}/centroids`),
            ]).then(([zoneRes, centroidRes]) => {
              if (zoneRes.status === 'fulfilled') {
                const fetchedZones = zoneRes.value.data.zones ?? [];
                setZones(fetchedZones);
                setZonedTruckIds(new Set(fetchedZones.map((z: ZonePolygon) => z.truck_id)));
              }
              if (centroidRes.status === 'fulfilled') {
                setCentroids(centroidRes.value.data.centroids ?? []);
              }
            });
          }}
        />
      )}

      {/* Zone density map — only render when truck assignments exist for today */}
      {assignments.length > 0 && (
        <ZoneDensityMap zones={zones} centroids={centroids} className="h-80" />
      )}

      {/* Truck panels */}
      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map(i => <SkeletonCard key={i} />)}
        </div>
      ) : truckStates.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-muted-foreground">No truck assignments found for today.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {truckStates.map(state => (
            <TruckSortPanel
              key={state.ta.id}
              state={state}
              walkers={walkers}
              trainers={trainers}
              routeDate={today}
              zoneExists={zonedTruckIds.has(state.ta.truck_id)}
              onCommit={handleCommit}
              onDistribute={handleDistribute}
              onArrivalConfirm={handleArrivalConfirm}
              onRefresh={handleRefresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}
