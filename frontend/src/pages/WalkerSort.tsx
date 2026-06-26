import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import StatCard from '../components/ui/StatCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import {
  Package, Route, Users, AlertTriangle, CheckCircle2,
  RefreshCw, ChevronDown, ChevronUp, MapPin, Layers, Clock,
  UserCheck, Loader2, ShieldAlert,
} from 'lucide-react';
import { getLocalYMD } from '../utils/date';
import { useAuth } from '../contexts/AuthContext';
import type { RouteResponse, MisroutedPackageOut } from '../api/types';

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

interface SortStatus {
  truck_assignment_id: string;
  truck_name: string;
  committed: boolean;
  routes: RouteResponse[];
  unassigned_misroutes: MisroutedPackageOut[];
  packages_sorted: number;
  packages_dropped: number;
}

interface Employee {
  id: string;
  name: string;
  role: string;
  injury_status?: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function EffortBadge({ effort }: { effort: string }) {
  const cls =
    effort === 'heavy'   ? 'bg-danger/10 text-danger'
    : effort === 'easy'  ? 'bg-success/10 text-success'
    :                      'bg-primary/10 text-primary';
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {effort}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    unassigned: 'bg-muted text-muted-foreground',
    assigned:   'bg-info/10 text-info',
    in_progress:'bg-warning/10 text-warning',
    completed:  'bg-success/10 text-success',
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eligible = walkers.filter(w =>
    w.role !== 'trainer' &&
    !(w.injury_status !== null && w.injury_status !== undefined && route.effort_class === 'heavy')
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
  onClose: () => void;
  onResolved: () => void;
}

function MisrouteResolveModal({ routeId, flagId, tbaNumber, routes, onClose, onResolved }: MisrouteResolveModalProps) {
  const [destRouteId, setDestRouteId] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
              <option key={r.id} value={r.id}>#{r.route_number} — {r.assigned_to_name ?? 'unassigned'} ({r.effort_class})</option>
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
// Route row — expandable, with reassign + misroute resolve controls
// ---------------------------------------------------------------------------

interface RouteRowProps {
  route: RouteResponse;
  allRoutes: RouteResponse[];
  walkers: Employee[];
  canReassign: boolean;
  onReassign: (route: RouteResponse) => void;
  onResolveMisroute: (routeId: string, flagId: string, tba: string) => void;
}

function RouteRow({ route, allRoutes, walkers, canReassign, onReassign, onResolveMisroute }: RouteRowProps) {
  const [open, setOpen] = useState(false);
  const slotPct = Math.min(100, Math.round((route.slot_cost / route.capacity_limit) * 100));
  const barColor = slotPct >= 90 ? 'bg-danger' : slotPct >= 70 ? 'bg-warning' : 'bg-success';

  const assignee = walkers.find(w => w.id === route.assigned_to);
  const injuryStatus = assignee?.injury_status ?? null;

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-accent/40 transition-colors text-left"
      >
        <span className="text-sm font-semibold text-foreground w-8 shrink-0">#{route.route_number}</span>
        <EffortBadge effort={route.effort_class} />
        <StatusBadge status={route.status} />
        <span className="text-xs text-muted-foreground ml-1">{route.package_count} pkgs</span>

        {/* Capacity bar */}
        <div className="flex-1 min-w-0 mx-2">
          <div className="h-1.5 bg-accent rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${slotPct}%` }} />
          </div>
        </div>
        <span className="text-xs text-muted-foreground shrink-0 w-12 text-right">
          {route.slot_cost}/{route.capacity_limit}
        </span>

        {route.assigned_to_name && (
          <span className="text-xs text-foreground font-medium shrink-0 max-w-[120px] truncate hidden sm:block">
            {route.assigned_to_name}
          </span>
        )}

        {/* Injury badge */}
        {injuryStatus && (
          <ShieldAlert className="w-3.5 h-3.5 text-warning shrink-0" aria-label={`${assignee?.name}: ${injuryStatus}`} />
        )}

        {route.misrouted_packages.length > 0 && (
          <AlertTriangle className="w-3.5 h-3.5 text-warning shrink-0" />
        )}
        {open ? <ChevronUp className="w-4 h-4 text-muted-foreground shrink-0" /> : <ChevronDown className="w-4 h-4 text-muted-foreground shrink-0" />}
      </button>

      {open && (
        <div className="border-t border-border px-4 py-3 space-y-3 bg-surface/40">
          {/* Block keys */}
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

          {/* Assignment info + injury warning */}
          {route.assigned_to_name && (
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

          {/* Misrouted packages with resolve button */}
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
                    {canReassign && (
                      <button
                        onClick={() => onResolveMisroute(route.id, m.tba_number, m.tba_number)}
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

          {/* Reassign button */}
          {canReassign && (
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
// Truck sort card
// ---------------------------------------------------------------------------

function TruckSortCard({
  sortStatus,
  walkers,
  canReassign,
  onRefresh,
}: {
  sortStatus: SortStatus;
  walkers: Employee[];
  canReassign: boolean;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reassignTarget, setReassignTarget] = useState<RouteResponse | null>(null);
  const [misrouteTarget, setMisrouteTarget] = useState<{ routeId: string; flagId: string; tba: string } | null>(null);

  const assignedCount  = sortStatus.routes.filter(r => r.status !== 'unassigned').length;
  const completedCount = sortStatus.routes.filter(r => r.status === 'completed').length;

  return (
    <>
      <div className="card-elevated space-y-0">
        <button
          onClick={() => setOpen(o => !o)}
          className="w-full flex items-center gap-3 p-4 hover:bg-accent/20 transition-colors rounded-xl text-left"
        >
          <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-primary/10 shrink-0">
            <Layers className="w-4.5 h-4.5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-foreground">{sortStatus.truck_name}</p>
            <p className="text-xs text-muted-foreground">
              {sortStatus.routes.length} routes · {sortStatus.packages_sorted} pkgs sorted
              {sortStatus.packages_dropped > 0 && ` · ${sortStatus.packages_dropped} dropped`}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {completedCount === sortStatus.routes.length && sortStatus.routes.length > 0 ? (
              <CheckCircle2 className="w-4 h-4 text-success" />
            ) : assignedCount > 0 ? (
              <Clock className="w-4 h-4 text-info" />
            ) : (
              <span className="text-xs text-muted-foreground">unassigned</span>
            )}
            {open ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
          </div>
        </button>

        {open && (
          <div className="border-t border-border px-4 pb-4 pt-3 space-y-2">
            {sortStatus.routes.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No routes committed yet.</p>
            ) : (
              sortStatus.routes
                .slice()
                .sort((a, b) => a.route_number - b.route_number)
                .map(r => (
                  <RouteRow
                    key={r.id}
                    route={r}
                    allRoutes={sortStatus.routes}
                    walkers={walkers}
                    canReassign={canReassign}
                    onReassign={setReassignTarget}
                    onResolveMisroute={(routeId, flagId, tba) =>
                      setMisrouteTarget({ routeId, flagId, tba })
                    }
                  />
                ))
            )}

            {sortStatus.unassigned_misroutes.length > 0 && (
              <div className="mt-3 p-3 bg-warning/5 border border-warning/20 rounded-xl">
                <p className="text-xs font-semibold text-warning mb-2 flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {sortStatus.unassigned_misroutes.length} unresolved misroutes (no destination found)
                </p>
                {sortStatus.unassigned_misroutes.map(m => (
                  <div key={m.tba_number} className="text-xs text-muted-foreground font-mono">{m.tba_number}</div>
                ))}
              </div>
            )}

            <button
              onClick={e => { e.stopPropagation(); onRefresh(); }}
              className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
          </div>
        )}
      </div>

      {/* Modals — rendered outside the card so z-index is independent */}
      {reassignTarget && (
        <ReassignModal
          route={reassignTarget}
          walkers={walkers}
          onClose={() => setReassignTarget(null)}
          onReassigned={onRefresh}
        />
      )}
      {misrouteTarget && (
        <MisrouteResolveModal
          routeId={misrouteTarget.routeId}
          flagId={misrouteTarget.flagId}
          tbaNumber={misrouteTarget.tba}
          routes={sortStatus.routes}
          onClose={() => setMisrouteTarget(null)}
          onResolved={onRefresh}
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
  const { groups } = useAuth();

  const [assignments, setAssignments] = useState<TruckAssignment[]>([]);
  const [sortStatuses, setSortStatuses] = useState<SortStatus[]>([]);
  const [walkers, setWalkers] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const canReassign = groups.some(r => ['trainer', 'driver', 'dispatch', 'management', 'admin'].includes(r));

  const fetchSortStatus = useCallback(async (ta: TruckAssignment): Promise<SortStatus> => {
    try {
      const res = await axiosClient.get<RouteResponse[]>(`/walker-routes/${ta.id}/routes`);
      return {
        truck_assignment_id: ta.id,
        truck_name: ta.truck_name,
        committed: res.data.length > 0,
        routes: res.data,
        unassigned_misroutes: [],
        packages_sorted: res.data.reduce((s, r) => s + r.tba_numbers.length, 0),
        packages_dropped: 0,
      };
    } catch {
      return {
        truck_assignment_id: ta.id,
        truck_name: ta.truck_name,
        committed: false,
        routes: [],
        unassigned_misroutes: [],
        packages_sorted: 0,
        packages_dropped: 0,
      };
    }
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taRes, empRes] = await Promise.all([
        axiosClient.get<TruckAssignment[]>('/truck-assignments/', { params: { date: today } }),
        axiosClient.get<Employee[]>('/employees/', { params: { is_active: true } }),
      ]);
      const tas  = taRes.data;
      const emps = empRes.data;
      setAssignments(tas);
      setWalkers(emps.filter(e => ['walker', 'trainee', 'trainer', 'driver'].includes(e.role)));
      const statuses = await Promise.all(tas.map(fetchSortStatus));
      setSortStatuses(statuses);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to load sort status.');
    } finally {
      setLoading(false);
    }
  }, [today, fetchSortStatus]);

  const refreshOne = useCallback(async (ta: TruckAssignment) => {
    const updated = await fetchSortStatus(ta);
    setSortStatuses(prev => prev.map(s => s.truck_assignment_id === ta.id ? updated : s));
  }, [fetchSortStatus]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Aggregate stats
  const totalRoutes     = sortStatuses.reduce((s, st) => s + st.routes.length, 0);
  const totalPkgs       = sortStatuses.reduce((s, st) => s + st.packages_sorted, 0);
  const assignedRoutes  = sortStatuses.reduce((s, st) => s + st.routes.filter(r => r.status !== 'unassigned').length, 0);
  const completedRoutes = sortStatuses.reduce((s, st) => s + st.routes.filter(r => r.status === 'completed').length, 0);
  const misrouteCount   = sortStatuses.reduce((s, st) => s + st.routes.reduce((rs, r) => rs + r.misrouted_packages.length, 0) + st.unassigned_misroutes.length, 0);

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        eyebrow="Walker Sort"
        title="Sort Monitor"
        description={`Route assignment status for ${new Date(today + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
        actions={
          <button onClick={fetchAll} className="btn-ghost flex items-center gap-1.5 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Total Routes"    value={loading ? '—' : totalRoutes}                            icon={Route}         tone="primary"  delay={0} />
        <StatCard label="Packages Sorted" value={loading ? '—' : totalPkgs}                             icon={Package}       tone="info"     delay={0.05} />
        <StatCard label="Assigned"        value={loading ? '—' : `${assignedRoutes}/${totalRoutes}`}    icon={Users}         tone="success"  delay={0.1} />
        <StatCard label="Misroutes"       value={loading ? '—' : misrouteCount}                         icon={AlertTriangle} tone={misrouteCount > 0 ? 'warning' : 'success'} delay={0.15} />
      </div>

      {/* Progress bar */}
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

      {/* Truck cards */}
      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map(i => <SkeletonCard key={i} />)}
        </div>
      ) : sortStatuses.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-muted-foreground">No truck assignments found for today.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sortStatuses.map((st, i) => (
            <TruckSortCard
              key={st.truck_assignment_id}
              sortStatus={st}
              walkers={walkers}
              canReassign={canReassign}
              onRefresh={() => refreshOne(assignments[i])}
            />
          ))}
        </div>
      )}
    </div>
  );
}
