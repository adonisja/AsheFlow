import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import StatCard from '../components/ui/StatCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import ZoneDensityMap from '../components/ZoneDensityMap';
import type { ZonePolygon, Centroid } from '../components/ZoneDensityMap';
import {
  Package, Users, AlertTriangle, CheckCircle2, RefreshCw,
  ChevronDown, ChevronUp, Send, UserCheck, Shuffle,
  MapPin, Route, Layers,
} from 'lucide-react';
import { getLocalYMD } from '../utils/date';
import type {
  CommitSortResponse, RouteResponse, WaveAssignmentEntry,
  ArrivalConfirmResponse, RebalanceOffer, MisroutedPackageOut,
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

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    unassigned: 'bg-muted text-muted-foreground',
    assigned: 'bg-info/10 text-info',
    in_progress: 'bg-warning/10 text-warning',
    completed: 'bg-success/10 text-success',
  };
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${map[status] ?? 'bg-muted text-muted-foreground'}`}>
      {status.replace('_', ' ')}
    </span>
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
// Truck sort panel
// ---------------------------------------------------------------------------

function TruckSortPanel({
  state,
  walkers,
  trainers,
  onCommit,
  onDistribute,
  onArrivalConfirm,
  onAcceptHeavy,
  onRefresh,
}: {
  state: TruckSortState;
  walkers: Employee[];
  trainers: Employee[];
  onCommit: (taId: string) => Promise<void>;
  onDistribute: (taId: string, assignments: WaveAssignmentEntry[], trainerId: string, traineeId?: string, traineePhase?: number) => Promise<void>;
  onArrivalConfirm: (taId: string, trainerId: string, traineeId: string) => Promise<void>;
  onAcceptHeavy: (taId: string, routeNumber: number) => Promise<void>;
  onRefresh: (taId: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [commitLoading, setCommitLoading] = useState(false);
  const [distributeLoading, setDistributeLoading] = useState(false);
  const [arrivalLoading, setArrivalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Wave assignment map: route_number → employee_id
  const [waveMap, setWaveMap] = useState<Record<number, string>>({});
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
              <button
                onClick={handleCommit}
                disabled={commitLoading}
                className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
              >
                {commitLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                {commitLoading ? 'Running sort…' : 'Run & Commit Sort'}
              </button>
            ) : (
              <div className="text-xs text-muted-foreground">
                {state.routes.length} routes committed · {pkgCount} packages
                {state.packages_dropped > 0 && ` · ${state.packages_dropped} packages dropped`}
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

              {state.phase === 'committed' && (
                <button
                  onClick={handleDistribute}
                  disabled={distributeLoading}
                  className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
                >
                  {distributeLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Shuffle className="w-4 h-4" />}
                  {distributeLoading ? 'Distributing…' : 'Send Wave Distribution'}
                </button>
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

          {/* ── Heavy rebalance offers ── */}
          {state.rebalanceResult && state.rebalanceResult.heavy_offers.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-widest text-warning flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" /> Heavy rebalance offers
              </p>
              {state.rebalanceResult.heavy_offers.map(offer => (
                <div key={offer.route_number} className="p-3 bg-warning/5 border border-warning/20 rounded-xl space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold text-foreground">Route #{offer.route_number}</p>
                    <span className="text-xs text-muted-foreground">
                      {offer.current_slot_cost}/{offer.paired_capacity_limit} half-slots after
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    +{offer.absorbable_package_count} packages from {offer.absorbable_tote_ids.length} totes
                  </p>
                  <button
                    onClick={() => onAcceptHeavy(state.ta.id, offer.route_number)}
                    className="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold bg-warning text-warning-foreground hover:brightness-105 transition-all press"
                  >
                    Accept rebalance
                  </button>
                </div>
              ))}
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
        axiosClient.get<TruckAssignment[]>('/truck-assignments/', { params: { date: today } }),
        axiosClient.get<Employee[]>('/employees/', { params: { is_active: true } }),
        axiosClient.get<{ zones: ZonePolygon[] }>(`/sort/${today}`),
        axiosClient.get<{ centroids: Centroid[] }>(`/sort/${today}/centroids`),
      ]);
      // Unpack settled results — zones/centroids fail silently if sort hasn't run yet
      if (zoneRes.status === 'fulfilled') setZones(zoneRes.value.data.zones ?? []);
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
          const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/assignment/${ta.id}`);
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
    const res = await axiosClient.post<CommitSortResponse>('/walker-routes/commit', {
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
    await axiosClient.post('/walker-routes/distribute', {
      truck_assignment_id: taId,
      route_date: today,
      assignments,
      trainer_id: trainerId,
      trainee_id: traineeId ?? null,
      trainee_phase: traineePhase ?? null,
    });
    const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/assignment/${taId}`);
    updateState(taId, { phase: 'distributed', routes: r.data });
  };

  const handleArrivalConfirm = async (taId: string, trainerId: string, traineeId: string) => {
    const res = await axiosClient.post<ArrivalConfirmResponse>('/walker-routes/arrival-confirm', {
      truck_assignment_id: taId,
      route_date: today,
      trainer_id: trainerId,
      trainee_id: traineeId,
    });
    const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/assignment/${taId}`);
    updateState(taId, {
      phase: 'arrived',
      routes: r.data,
      rebalanceResult: res.data,
    });
  };

  const handleAcceptHeavy = async (taId: string, routeNumber: number) => {
    const ta = truckStates.find(s => s.ta.id === taId);
    if (!ta) return;
    await axiosClient.post('/walker-routes/arrival-confirm/accept-heavy', {
      route_number: routeNumber,
      truck_assignment_id: taId,
      route_date: today,
    });
    const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/assignment/${taId}`);
    setTruckStates(prev => prev.map(s => {
      if (s.ta.id !== taId) return s;
      const updatedOffers = s.rebalanceResult
        ? { ...s.rebalanceResult, heavy_offers: s.rebalanceResult.heavy_offers.filter(o => o.route_number !== routeNumber) }
        : null;
      return { ...s, routes: r.data, rebalanceResult: updatedOffers };
    }));
  };

  const handleRefresh = async (taId: string) => {
    const ta = assignments.find(a => a.id === taId);
    if (!ta) return;
    try {
      const r = await axiosClient.get<RouteResponse[]>(`/walker-routes/assignment/${taId}`);
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
        eyebrow="Walker Operations"
        title="Route Sort"
        description={`Commit and distribute walker routes for ${new Date(today + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
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

      {/* Zone density map */}
      <ZoneDensityMap zones={zones} centroids={centroids} className="h-80" />

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
              onCommit={handleCommit}
              onDistribute={handleDistribute}
              onArrivalConfirm={handleArrivalConfirm}
              onAcceptHeavy={handleAcceptHeavy}
              onRefresh={handleRefresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}
