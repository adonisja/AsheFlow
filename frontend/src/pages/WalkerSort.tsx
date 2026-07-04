import React, { useEffect, useState, useCallback, useRef } from 'react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import StatCard from '../components/ui/StatCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import {
  Package, Route, Users, AlertTriangle, CheckCircle2,
  RefreshCw, ChevronDown, ChevronUp, MapPin, Layers, Clock,
  UserCheck, Loader2, ShieldAlert, Send, Zap, CircleAlert,
  ArrowRightLeft, Shuffle,
} from 'lucide-react';
import { getLocalYMD } from '../utils/date';
import ApPullsPanel from '../components/ApPullsPanel';
import type { RostersResponse } from '../api/types';

/** Station-loading facts per truck, derived from /sort/{date}/rosters:
 * feeds the commit soft-gate warning, the rider pre-warning, driver names,
 * and the per-truck load sheet link. */
interface StationTruckInfo {
  driverName: string | null;
  pendingTransfers: number;
  riderCount: number;
}
import { useAuth } from '../contexts/AuthContext';
import { useCan } from '../hooks/useCan';
import type {
  RouteResponse, MisroutedPackageOut,
  CommitSortResponse, WaveAssignmentEntry, ArrivalConfirmResponse,
  WavePoolResponse, ProposedAssignmentEntry, WaveDistributionProposal,
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
  paired_arrival_confirmed?: boolean;
}

interface Employee {
  id: string;
  name: string;
  role: string;
  injury_status?: string | null;
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
    effort === 'heavy'  ? 'bg-danger/10 text-danger'
    : effort === 'easy' ? 'bg-success/10 text-success'
    :                     'bg-primary/10 text-primary';
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {effort}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    unassigned:  'bg-muted text-muted-foreground',
    assigned:    'bg-info/10 text-info',
    in_progress: 'bg-warning/10 text-warning',
    completed:   'bg-success/10 text-success',
  };
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${map[status] ?? 'bg-muted text-muted-foreground'}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Reassign modal
// ---------------------------------------------------------------------------

interface ReassignModalProps {
  route: RouteResponse;
  walkers: Employee[];
  onClose: () => void;
  onReassigned: () => void;
}

function ReassignModal({ route, walkers, onClose, onReassigned }: ReassignModalProps) {
  const [selectedId, setSelectedId] = useState('');
  const [saving, setSaving]         = useState(false);
  const [error, setError]           = useState<string | null>(null);

  const eligible = walkers.filter(w =>
    w.role !== 'trainer' &&
    !(w.injury_status != null && route.effort_class === 'heavy')
  );

  async function submit() {
    if (!selectedId) return;
    setSaving(true);
    setError(null);
    const emp = walkers.find(w => w.id === selectedId);
    try {
      await axiosClient.patch(`/walker-routes/routes/${route.id}/reassign`, {
        new_employee_id: selectedId,
        new_employee_name: emp?.name ?? '',
      });
      onReassigned();
      onClose();
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Reassign failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <UserCheck className="w-4 h-4 text-primary" />
          <h3 className="font-semibold text-foreground">Reassign route #{route.route_number}</h3>
        </div>
        <div className="text-xs text-muted-foreground space-y-0.5">
          <p>Current: <span className="text-foreground font-medium">{route.assigned_to_name ?? 'Unassigned'}</span></p>
          <p>Effort: <EffortBadge effort={route.effort_class} /></p>
          {route.effort_class === 'heavy' && (
            <p className="text-warning flex items-center gap-1">
              <ShieldAlert className="w-3.5 h-3.5" /> Injured/modified-duty walkers excluded
            </p>
          )}
        </div>
        <select
          className="input w-full"
          value={selectedId}
          onChange={e => setSelectedId(e.target.value)}
        >
          <option value="">Select walker…</option>
          {eligible.map(w => (
            <option key={w.id} value={w.id}>{w.name}{w.injury_status ? ` (${w.injury_status})` : ''}</option>
          ))}
        </select>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={!selectedId || saving} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Reassign
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Misroute resolve modal
// ---------------------------------------------------------------------------

interface MisrouteResolveModalProps {
  routeId: string;
  flagId: string;
  tbaNumber: string;
  routes: RouteResponse[];
  suggestedRouteNumber?: number | null;
  onClose: () => void;
  onResolved: () => void;
}

function MisrouteResolveModal({ routeId, flagId, tbaNumber, routes, suggestedRouteNumber, onClose, onResolved }: MisrouteResolveModalProps) {
  // The sort already knows which route covers this package's block - default
  // to it (dispatch can still pick another route or hand back to the truck).
  const suggested = routes.find(r => r.route_number === suggestedRouteNumber);
  const [destRouteId, setDestRouteId] = useState(suggested?.id ?? '');
  const [saving, setSaving]           = useState(false);
  const [error, setError]             = useState<string | null>(null);

  async function submit() {
    if (!destRouteId) return;
    setSaving(true);
    setError(null);
    try {
      await axiosClient.patch(`/walker-routes/routes/${routeId}/misroutes/${flagId}/resolve`, {
        destination_route_id: destRouteId,
      });
      onResolved();
      onClose();
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Resolve failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-warning" />
          <h3 className="font-semibold text-foreground">Resolve misroute</h3>
        </div>
        <p className="text-xs text-muted-foreground font-mono">{tbaNumber}</p>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Package moved to route</label>
          <select
            className="input w-full"
            value={destRouteId}
            onChange={e => setDestRouteId(e.target.value)}
          >
            <option value="">Select destination route…</option>
            {routes.map(r => (
              <option key={r.id} value={r.id}>
                #{r.route_number} — {r.assigned_to_name ?? 'unassigned'} ({r.effort_class}){r.route_number === suggestedRouteNumber ? ' — suggested: covers this block' : ''}
              </option>
            ))}
          </select>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={!destRouteId || saving} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Mark resolved
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RouteCard — unified route card for all phases:
//   committed   → shows walker assignment dropdown (dispatch-time)
//   distributed → shows status badge, reassign trigger, misroute resolve
//   arrived     → same as distributed
// ---------------------------------------------------------------------------

interface RouteCardProps {
  route: RouteResponse;
  phase: SortPhase;
  walkers: Employee[];
  // committed phase
  waveAssignedName?: string | null;
  onAssign?: (routeNumber: number, employeeId: string) => void;
  // distributed/arrived phase
  canReassign?: boolean;
  onReassign?: (route: RouteResponse) => void;
  onResolveMisroute?: (routeId: string, flagId: string, tba: string, suggestedRouteNumber?: number | null) => void;
}

function RouteCard({
  route,
  phase,
  walkers,
  waveAssignedName,
  onAssign,
  canReassign,
  onReassign,
  onResolveMisroute,
}: RouteCardProps) {
  const [open, setOpen] = useState(false);
  const slotPct  = Math.min(100, Math.round((route.slot_cost / route.capacity_limit) * 100));
  const barColor = slotPct >= 90 ? 'bg-danger' : slotPct >= 70 ? 'bg-warning' : 'bg-success';
  const assignee     = walkers.find(w => w.id === route.assigned_to);
  const injuryStatus = assignee?.injury_status ?? null;
  const isOperational = phase === 'distributed' || phase === 'arrived';

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      {/* Header row — shared by all phases */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-accent/40 transition-colors text-left"
      >
        <span className="text-sm font-semibold text-foreground w-8 shrink-0">#{route.route_number}</span>
        <EffortBadge effort={route.effort_class} />
        {isOperational && <StatusBadge status={route.status} />}
        <span className="text-xs text-muted-foreground">{route.package_count} pkgs</span>
        {!isOperational && (
          <span className="text-xs text-muted-foreground">{route.tote_ids.length} totes</span>
        )}
        <div className="flex-1 min-w-0 mx-2">
          <div className="h-1.5 bg-accent rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${slotPct}%` }} />
          </div>
        </div>
        <span className="text-xs text-muted-foreground shrink-0 w-12 text-right">
          {route.slot_cost}/{route.capacity_limit}
        </span>
        {isOperational && route.assigned_to_name && (
          <span className="text-xs text-foreground font-medium shrink-0 max-w-[120px] truncate hidden sm:block">
            {route.assigned_to_name}
          </span>
        )}
        {injuryStatus && (
          <ShieldAlert className="w-3.5 h-3.5 text-warning shrink-0" aria-label={`${assignee?.name}: ${injuryStatus}`} />
        )}
        {route.misrouted_packages.length > 0 && (
          <AlertTriangle className="w-3.5 h-3.5 text-warning shrink-0" />
        )}
        {open ? <ChevronUp className="w-4 h-4 text-muted-foreground shrink-0" /> : <ChevronDown className="w-4 h-4 text-muted-foreground shrink-0" />}
      </button>

      {/* Committed phase: inline assignment dropdown */}
      {phase === 'committed' && onAssign && (
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
          {waveAssignedName && (
            <span className="text-xs font-medium text-foreground shrink-0 max-w-[100px] truncate">{waveAssignedName}</span>
          )}
        </div>
      )}

      {/* Expanded panel */}
      {open && (
        <div className="border-t border-border px-3 py-3 space-y-3 bg-surface/40">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1.5">Blocks</p>
            <div className="flex flex-wrap gap-1">
              {route.block_keys.map(k => (
                <span key={k} className="inline-flex items-center gap-1 px-2 py-0.5 bg-accent rounded text-xs text-foreground font-mono">
                  <MapPin className="w-2.5 h-2.5 text-muted-foreground" />{k}
                </span>
              ))}
            </div>
          </div>

          {/* Operational-phase extras: assignee detail, trainee pairing, injury warning */}
          {isOperational && route.assigned_to_name && (
            <div className="flex items-start gap-3 text-xs text-muted-foreground flex-wrap">
              <span>Assigned: <span className="text-foreground font-medium">{route.assigned_to_name}</span></span>
              {route.paired_trainee_id && (
                <span>Trainee paired (Phase {route.trainee_phase})</span>
              )}
              {injuryStatus && route.effort_class === 'heavy' && (
                <span className="text-warning flex items-center gap-1">
                  <ShieldAlert className="w-3 h-3" /> {assignee?.name} is {injuryStatus} — consider reassigning
                </span>
              )}
            </div>
          )}

          {route.misrouted_packages.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-warning font-semibold mb-1.5 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Misrouted packages
              </p>
              <div className="space-y-1.5">
                {route.misrouted_packages.map(m => (
                  <div key={m.tba_number} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-xs min-w-0">
                      <span className="font-mono text-foreground">{m.tba_number}</span>
                      {m.destination_block_key && (
                        <span className="text-warning">→ {m.destination_block_key}</span>
                      )}
                    </div>
                    {isOperational && canReassign && onResolveMisroute && (
                      <button
                        onClick={() => onResolveMisroute(route.id, m.id ?? '', m.tba_number, m.suggested_route_number)}
                        className="text-xs text-primary hover:text-primary/80 px-2 py-0.5 rounded border border-primary/30 hover:bg-primary/5 transition-colors shrink-0"
                      >
                        Resolve
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {isOperational && canReassign && onReassign && (
            <button
              onClick={() => onReassign(route)}
              className="flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 transition-colors"
            >
              <UserCheck className="w-3.5 h-3.5" /> Reassign route
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wave pool panel
// ---------------------------------------------------------------------------

function WavePoolPanel({
  taId,
  routeDate,
  walkers,
  onSecondWavePropose,
}: {
  taId: string;
  routeDate: string;
  walkers: Employee[];
  onSecondWavePropose: (taId: string, proposal: ProposedAssignmentEntry[]) => void;
}) {
  const [pool, setPool]           = useState<WavePoolResponse | null>(null);
  const [loading, setLoading]     = useState(true);
  const [proposing, setProposing] = useState(false);
  const [propError, setPropError] = useState<string | null>(null);
  const intervalRef               = useRef<ReturnType<typeof setInterval> | null>(null);

  // The wave is settled when nothing is left to distribute: no unassigned
  // routes AND no route still assigned/in-progress. Once settled the pool can't
  // change, so the poll stops (ADR-179 — this loop previously had no stop
  // condition and ran forever).
  const isWaveSettled = useCallback((data: WavePoolResponse): boolean => {
    if (data.unassigned_routes.length > 0) return false;
    return Object.values(data.wave_summary.waves).every(
      w => w.assigned === 0 && w.in_progress === 0 && w.unassigned === 0,
    );
  }, []);

  const fetchPool = useCallback(async () => {
    try {
      const { data } = await axiosClient.get<WavePoolResponse>(
        `/walker-routes/${taId}/wave-pool`,
        { params: { route_date: routeDate } },
      );
      setPool(data);
      if (isWaveSettled(data) && intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    } catch {
      // silent — pool is advisory
    } finally {
      setLoading(false);
    }
  }, [taId, routeDate, isWaveSettled]);

  useEffect(() => {
    fetchPool();
    // Visibility-gated 45s poll (ADR-179: was an ungated 30s loop). A
    // backgrounded tab doesn't poll; focus resumes it.
    const tick = () => { if (document.visibilityState === 'visible') fetchPool(); };
    const start = () => {
      if (!intervalRef.current) intervalRef.current = setInterval(tick, 45_000);
    };
    start();
    const onFocus = () => { fetchPool(); start(); };
    window.addEventListener('focus', onFocus);
    return () => {
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
      window.removeEventListener('focus', onFocus);
    };
  }, [fetchPool]);

  async function handleAutoPropose() {
    setProposing(true);
    setPropError(null);
    try {
      const res = await axiosClient.post<WaveDistributionProposal>(
        '/walker-routes/wave-distribution',
        { truck_assignment_id: taId, route_date: routeDate, auto_assign: true, assignments: [], trainer_id: null, trainee_id: null, trainee_phase: null },
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
      {waveKeys.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Wave progress</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {waveKeys.map(wk => {
              const counts = wave_summary.waves[wk];
              const done  = counts.completed;
              const total = counts.assigned + counts.in_progress + counts.completed + counts.unassigned;
              const pct   = total > 0 ? Math.round((done / total) * 100) : 0;
              return (
                <div key={wk} className="p-2 rounded-lg bg-accent/50 space-y-1">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase">Wave {wk}</p>
                  <div className="h-1 bg-border rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${pct === 100 ? 'bg-success' : 'bg-primary'}`} style={{ width: `${pct}%` }} />
                  </div>
                  <p className="text-[10px] text-muted-foreground">{done}/{total} complete · {counts.in_progress} active</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

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

      {unassigned_routes.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-warning" /> Unassigned pool
            <span className="text-warning font-medium">({unassigned_routes.length})</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {unassigned_routes.slice().sort((a, b) => a.route_number - b.route_number).map(r => (
              <div key={r.route_id} className="flex items-center gap-1 px-2 py-1 rounded-lg border border-border bg-accent/40 text-xs">
                <span className="font-semibold text-foreground">#{r.route_number}</span>
                <EffortBadge effort={r.effort_class} />
                <span className="text-muted-foreground">{r.package_count}p</span>
              </div>
            ))}
          </div>
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
// Proposal review panel
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
  walkers: Employee[];
  onConfirm: (taId: string, assignments: WaveAssignmentEntry[]) => Promise<void>;
  onDiscard: () => void;
}) {
  const [overrides, setOverrides]   = useState<Record<number, string>>(() =>
    Object.fromEntries(proposal.map(p => [p.route_number, p.employee_id]))
  );
  const [confirming, setConfirming] = useState(false);
  const [error, setError]           = useState<string | null>(null);

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
      <p className="text-xs text-muted-foreground">Edit any assignment before confirming.</p>
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
            {p.auto_proposed && <span className="text-[10px] text-info shrink-0">auto</span>}
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
// Truck sort panel — full 3-step commit / wave / arrival workflow
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
  station,
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
  station?: StationTruckInfo;
}) {
  const [open, setOpen]                         = useState(false);
  const [commitLoading, setCommitLoading]       = useState(false);
  const [distributeLoading, setDistributeLoading] = useState(false);
  const [arrivalLoading, setArrivalLoading]     = useState(false);
  const [error, setError]                       = useState<string | null>(null);
  const [waveMap, setWaveMap]                   = useState<Record<number, string>>({});
  const [firstWaveProposal, setFirstWaveProposal] = useState<ProposedAssignmentEntry[] | null>(null);
  const [firstWaveProposing, setFirstWaveProposing] = useState(false);
  const [secondWaveProposal, setSecondWaveProposal] = useState<ProposedAssignmentEntry[] | null>(null);
  const [selectedTrainerId, setSelectedTrainerId] = useState('');
  const [selectedTraineeId, setSelectedTraineeId] = useState('');
  const [traineePhase, setTraineePhase]         = useState<number>(1);
  const [arrivalTrainerId, setArrivalTrainerId] = useState('');
  const [arrivalTraineeId, setArrivalTraineeId] = useState('');
  const [reassignTarget, setReassignTarget]     = useState<RouteResponse | null>(null);
  const [misrouteTarget, setMisrouteTarget]     = useState<{ routeId: string; flagId: string; tba: string; suggestedRouteNumber?: number | null } | null>(null);

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
        state.ta.id, assignments, selectedTrainerId,
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
    <>
      <div className="card-elevated">
        <button
          onClick={() => setOpen(o => !o)}
          className="w-full flex items-center gap-3 p-4 hover:bg-accent/20 transition-colors rounded-xl text-left"
        >
          <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-primary/10 shrink-0">
            <Layers className="w-4.5 h-4.5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-foreground">
              {state.ta.truck_name}
              {station?.driverName && (
                <span className="ml-2 text-xs font-normal text-muted-foreground">{station.driverName}</span>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              {state.phase === 'idle'        && 'Not committed'}
              {state.phase === 'committed'   && `${state.routes.length} routes · ${pkgCount} pkgs — awaiting distribution`}
              {state.phase === 'distributed' && `${state.routes.length} routes assigned — awaiting arrival confirm`}
              {state.phase === 'arrived'     && `${state.routes.length} routes · rebalance complete`}
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
            <div className="flex justify-end -mb-3">
              <a
                href={`/sort/print?date=${routeDate}&truck=${state.ta.truck_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                Print load sheet ↗
              </a>
            </div>
            {error && (
              <div className="p-3 bg-danger/5 border border-danger/20 rounded-xl text-sm text-danger">{error}</div>
            )}

            {/* ── Step 1: Commit ── */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Step 1 — Commit sort</p>
                {state.phase !== 'idle' && <CheckCircle2 className="w-4 h-4 text-success" />}
              </div>
              {state.phase === 'idle' ? (
                zoneExists ? (
                  <div className="space-y-2">
                  {(station?.pendingTransfers ?? 0) > 0 && (
                    <div className="flex items-center gap-2 p-2.5 rounded-xl bg-warning/5 border border-warning/20 text-xs text-warning">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                      {station!.pendingTransfers} pending station transfer{station!.pendingTransfers === 1 ? '' : 's'} touch this
                      truck - committing now builds routes on data that may still change. Not blocked (soft gate).
                    </div>
                  )}
                  {(station?.riderCount ?? 0) > 0 && (
                    <div className="flex items-center gap-2 p-2.5 rounded-xl bg-accent/40 border border-border text-xs text-muted-foreground">
                      <ArrowRightLeft className="w-3.5 h-3.5 shrink-0" />
                      Carries {station!.riderCount} package{station!.riderCount === 1 ? '' : 's'} off their tote's home block -
                      expect that many cross-walker transfers after commit.
                    </div>
                  )}
                  <button
                    onClick={handleCommit}
                    disabled={commitLoading}
                    className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
                  >
                    {commitLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                    {commitLoading ? 'Committing sort…' : 'Commit Sort'}
                  </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 p-3 rounded-xl bg-accent/40 border border-border text-xs text-muted-foreground">
                    <Layers className="w-3.5 h-3.5 shrink-0" />
                    Run Zone Assignment on Station Sort first to assign packages to this truck.
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
                      {state.packages_dropped} package{state.packages_dropped === 1 ? '' : 's'} dropped — TBAs not found in enriched manifest.
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* ── Step 2: Assign routes ── */}
            {state.phase !== 'idle' && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Step 2 — Assign routes to staff</p>
                  {state.phase !== 'committed' && <CheckCircle2 className="w-4 h-4 text-success" />}
                </div>

                {/* Route cards — committed shows assignment dropdown; distributed/arrived shows operational controls */}
                <div className="space-y-2">
                  {state.routes
                    .slice()
                    .sort((a, b) => a.route_number - b.route_number)
                    .map(r => (
                      <RouteCard
                          key={r.id}
                          route={r}
                          phase={state.phase}
                          walkers={walkers}
                          waveAssignedName={waveMap[r.route_number] ? (walkers.find(w => w.id === waveMap[r.route_number])?.name ?? null) : null}
                          onAssign={(rn, eid) => setWaveMap(prev => ({ ...prev, [rn]: eid }))}
                          canReassign={true}
                          onReassign={setReassignTarget}
                          onResolveMisroute={(routeId, flagId, tba, suggestedRouteNumber) => setMisrouteTarget({ routeId, flagId, tba, suggestedRouteNumber })}
                        />
                      ))}
                </div>

                {/* Trainer / trainee selectors (committed phase only) */}
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
                <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Step 3 — Arrival confirmation</p>
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

            {/* ── Rebalance result ── */}
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

            {/* ── Second-wave pool ── */}
            {(state.phase === 'distributed' || state.phase === 'arrived') && (
              <div className="space-y-3 border-t border-border pt-4">
                <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Second-wave pool</p>
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

      {reassignTarget && (
        <ReassignModal
          route={reassignTarget}
          walkers={walkers}
          onClose={() => setReassignTarget(null)}
          onReassigned={() => onRefresh(state.ta.id)}
        />
      )}
      {misrouteTarget && (
        <MisrouteResolveModal
          routeId={misrouteTarget.routeId}
          flagId={misrouteTarget.flagId}
          tbaNumber={misrouteTarget.tba}
          suggestedRouteNumber={misrouteTarget.suggestedRouteNumber}
          routes={state.routes}
          onClose={() => setMisrouteTarget(null)}
          onResolved={() => onRefresh(state.ta.id)}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function WalkerSortMonitor() {
  const today = getLocalYMD();
  const { can } = useCan();

  const [assignments, setAssignments]   = useState<TruckAssignment[]>([]);
  const [truckStates, setTruckStates]   = useState<TruckSortState[]>([]);
  const [walkers, setWalkers]           = useState<Employee[]>([]);
  const [trainers, setTrainers]         = useState<Employee[]>([]);
  const [zonedTruckIds, setZonedTruckIds] = useState<Set<string>>(new Set());
  const [stationInfo, setStationInfo]   = useState<Map<string, StationTruckInfo>>(new Map());
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState<string | null>(null);

  const canReassign = can('reassignRoute');

  const buildInitialState = (ta: TruckAssignment, routes: RouteResponse[], resp?: CommitSortResponse): TruckSortState => {
    const phase: SortPhase =
      routes.length === 0                                  ? 'idle'
      // arrival-confirm is persisted on the assignment — reconstruct the
      // 'arrived' phase after a page refresh instead of losing it
      : ta.paired_arrival_confirmed && routes.some(r => r.status !== 'unassigned') ? 'arrived'
      : routes.some(r => r.status !== 'unassigned')       ? 'distributed'
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

  const assignmentsRef = useRef<TruckAssignment[]>([]);

  // Refetch the dynamic per-day state: station rosters, zone status, and each
  // truck's routes. Reused by both the full load and the periodic tick, so the
  // tick doesn't have to refetch the static assignments+employees lists.
  const fetchDynamic = useCallback(async (tas: TruckAssignment[]) => {
    const [zoneRes, rosterRes] = await Promise.allSettled([
      axiosClient.get<{ zones: { truck_id: string }[] }>(`/sort/${today}`),
      axiosClient.get<RostersResponse>(`/sort/${today}/rosters`),
    ]);
    if (rosterRes.status === 'fulfilled') {
      const info = new Map<string, StationTruckInfo>();
      rosterRes.value.data.rosters.forEach(r => {
        const prev = info.get(r.truck_id);
        const pending = [...r.incoming, ...r.outgoing].filter(t => t.status === 'suggested' || t.status === 'confirmed').length;
        const riders = r.totes.reduce((n, t) => n + (t.rider_count ?? 0), 0);
        info.set(r.truck_id, {
          driverName: r.driver_name ?? prev?.driverName ?? null,
          pendingTransfers: (prev?.pendingTransfers ?? 0) + pending,
          riderCount: (prev?.riderCount ?? 0) + riders,
        });
      });
      setStationInfo(info);
    }
    if (zoneRes.status === 'fulfilled') {
      setZonedTruckIds(new Set((zoneRes.value.data.zones ?? []).map(z => z.truck_id)));
    }
    const states = await Promise.all(tas.map(async ta => {
      try {
        const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/${ta.id}/routes`);
        return buildInitialState(ta, r.data);
      } catch {
        return buildInitialState(ta, []);
      }
    }));
    setTruckStates(states);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today]);

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [taRes, empRes] = await Promise.allSettled([
        axiosClient.get<TruckAssignment[]>('/assignments/', { params: { date: today } }),
        axiosClient.get<{ id: string; role: string; name: string; injury_status?: string | null }[]>('/employees/', { params: { is_active: true } }),
      ]);
      if (taRes.status === 'rejected') throw taRes.reason;
      if (empRes.status === 'rejected') throw empRes.reason;

      const tas  = Array.from(new Map(taRes.value.data.map(a => [a.truck_id, a])).values());
      const emps = empRes.value.data;
      assignmentsRef.current = tas;
      setAssignments(tas);
      setWalkers(emps.filter(e => ['walker', 'trainee', 'trainer'].includes(e.role)));
      setTrainers(emps.filter(e => e.role === 'trainer'));

      await fetchDynamic(tas);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to load data.');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today, fetchDynamic]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Live-ish updates without SSE (ADR-179): the periodic 90s tick refetches only
  // the dynamic state (rosters/zones/routes) against the assignments already in
  // hand — it no longer re-pulls the static assignments+employees lists every
  // tick (those refresh on full load and on window focus). Visibility-gated so a
  // backgrounded tab is silent.
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === 'visible' && assignmentsRef.current.length) {
        fetchDynamic(assignmentsRef.current);
      }
    };
    const interval = setInterval(tick, 90_000);
    const onFocus = () => { fetchAll(true); };
    window.addEventListener('focus', onFocus);
    return () => { clearInterval(interval); window.removeEventListener('focus', onFocus); };
  }, [fetchAll, fetchDynamic]);

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
    updateState(taId, { phase: 'arrived', routes: r.data, rebalanceResult: res.data });
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
  const totalRoutes     = truckStates.reduce((s, st) => s + st.routes.length, 0);
  const totalPkgs       = truckStates.reduce((s, st) => s + st.packages_sorted, 0);
  const assignedRoutes  = truckStates.reduce((s, st) => s + st.routes.filter(r => r.status !== 'unassigned').length, 0);
  const completedRoutes = truckStates.reduce((s, st) => s + st.routes.filter(r => r.status === 'completed').length, 0);
  const misrouteCount   = truckStates.reduce((s, st) =>
    s + st.routes.reduce((rs, r) => rs + r.misrouted_packages.length, 0) + st.unassigned_misroutes.length, 0);

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        eyebrow="Anchor Point Operations"
        title="AP Sort"
        description={`Package sort, route assignment, and walker dispatch for ${new Date(today + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
        actions={
          <button onClick={() => fetchAll()} className="btn-ghost flex items-center gap-1.5 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Total Routes"    value={loading ? '—' : totalRoutes}                          icon={Route}         tone="primary"  delay={0} />
        <StatCard label="Packages Sorted" value={loading ? '—' : totalPkgs}                           icon={Package}       tone="info"     delay={0.05} />
        <StatCard label="Assigned"        value={loading ? '—' : `${assignedRoutes}/${totalRoutes}`}  icon={Users}         tone="success"  delay={0.1} />
        <StatCard label="Misroutes"       value={loading ? '—' : misrouteCount}                       icon={AlertTriangle} tone={misrouteCount > 0 ? 'warning' : 'success'} delay={0.15} />
      </div>

      {/* AP returns — out-of-zone packages walkers hand back to the driver at
          the anchor point (ADR-178). Tote check-off itself lives ONLY on
          Station Sort now (deduplicated); this page keeps just the AP-stage
          actions that physically happen at the anchor point. */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Anchor point returns</p>
        <ApPullsPanel date={today} />
      </div>

      {/* Completion progress */}
      {totalRoutes > 0 && (
        <div className="card p-4 space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground font-medium">Completion progress</span>
            <span className="text-foreground font-semibold">{completedRoutes}/{totalRoutes} routes completed</span>
          </div>
          <div className="h-2 bg-accent rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-success transition-all duration-700"
              style={{ width: `${totalRoutes > 0 ? Math.round((completedRoutes / totalRoutes) * 100) : 0}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="p-4 bg-danger/5 border border-danger/20 rounded-xl text-sm text-danger">{error}</div>
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
              station={stationInfo.get(state.ta.truck_id)}
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
