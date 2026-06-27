import { useState, useEffect, useCallback } from 'react';
import {
  MapPin, Package, AlertTriangle, PackageX, CheckCircle2,
  Truck, Navigation, ChevronDown, ChevronUp, Building2,
  ArrowRight, Clock, Loader2, Info,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import { useNotificationContext } from '../contexts/NotificationContext';
import type {
  RouteResponse, NextStopSuggestion, DeliveryStopCreate,
  RTSPackageCreate, MissingPackageCreate, ArrivalConfirmResponse,
  BuildingProfileCreate, BuildingType,
} from '../api/types';

const TODAY = new Date().toISOString().split('T')[0];

// ── helpers ───────────────────────────────────────────────────────────────────

function effortBadge(cls: string) {
  const map: Record<string, string> = {
    easy: 'bg-success/10 text-success',
    standard: 'bg-info/10 text-info',
    heavy: 'bg-warning/10 text-warning',
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${map[cls] ?? 'bg-accent text-foreground'}`}>
      {cls}
    </span>
  );
}

const RTS_LABELS: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Package damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Future delivery requested',
  customer_cancelled_order: 'Order cancelled',
};

const BUILDING_TYPE_OPTIONS: { value: BuildingType; label: string }[] = [
  { value: 'receptionist', label: 'Receptionist' },
  { value: 'walkup', label: 'Walk-up' },
  { value: 'elevator', label: 'Elevator' },
  { value: 'biz_freight', label: 'Business – Freight' },
  { value: 'biz_security', label: 'Business – Security' },
  { value: 'biz_loading_dock', label: 'Business – Loading Dock' },
  { value: 'mailroom', label: 'Mailroom' },
  { value: 'doorman', label: 'Doorman' },
  { value: 'biz_front', label: 'Business – Front Desk' },
];

// ── sub-components ────────────────────────────────────────────────────────────

interface StopCardProps {
  stop: NextStopSuggestion;
  onComplete: (tbas: string[], completedAt: string) => Promise<void>;
  onRts: (tba: string) => void;
  onMissing: (tba: string) => void;
  onBuildingProfile: (address: string, blockKey: string) => void;
  isFirst: boolean;
  completing: boolean;
}

function StopCard({ stop, onComplete, onRts, onMissing, onBuildingProfile, isFirst, completing }: StopCardProps) {
  const [expanded, setExpanded] = useState(isFirst);

  return (
    <div className={`card border ${isFirst ? 'border-primary/30 bg-primary/5' : 'border-border'}`}>
      <button
        className="w-full flex items-start justify-between gap-3 text-left"
        onClick={() => setExpanded(v => !v)}
      >
        <div className="flex items-start gap-3 min-w-0">
          <div className={`mt-0.5 flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${isFirst ? 'bg-primary text-primary-foreground' : 'bg-accent text-muted-foreground'}`}>
            {isFirst ? <Navigation className="w-3.5 h-3.5" /> : <MapPin className="w-3 h-3" />}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground truncate">{stop.normalised_address}</p>
            <p className="text-xs text-muted-foreground">{stop.packages_total} pkg{stop.packages_total !== 1 ? 's' : ''} · {stop.block_key}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {stop.signals.length > 0 && (
            <span className="text-xs text-warning font-medium flex items-center gap-1">
              <Clock className="w-3 h-3" />{stop.signals[0].reason.slice(0, 18)}
            </span>
          )}
          {expanded ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
        </div>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          {/* Building profile info */}
          {stop.has_locked_profile && (
            <div className="p-2 rounded-lg bg-accent/40 border border-border space-y-1">
              <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                <Building2 className="w-3.5 h-3.5 text-muted-foreground" />
                {stop.building_type?.replace(/_/g, ' ')}
              </div>
              {stop.operational_note && (
                <p className="text-xs text-muted-foreground">{stop.operational_note}</p>
              )}
              {stop.protocol_reminder && (
                <div className="flex items-start gap-1.5 text-xs text-info">
                  <Info className="w-3 h-3 mt-0.5 shrink-0" />
                  {stop.protocol_reminder}
                </div>
              )}
            </div>
          )}

          {/* Packages grouped by bag */}
          <div className="space-y-2">
            {(stop.bags.length > 0 ? stop.bags : [{ bag_id: 'unknown', tba_numbers: stop.tba_numbers }]).map(bag => (
              <div key={bag.bag_id} className="space-y-1">
                <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
                  Bag {bag.bag_id}
                </p>
                {bag.tba_numbers.map(tba => (
                  <div key={tba} className="flex items-center justify-between gap-2">
                    <span className="text-xs font-mono text-foreground">{tba}</span>
                    <div className="flex gap-1">
                      <button
                        onClick={() => onRts(tba)}
                        className="text-xs text-warning hover:text-warning/80 px-2 py-0.5 rounded border border-warning/30 hover:bg-warning/10 transition-colors"
                      >
                        Can't deliver
                      </button>
                      <button
                        onClick={() => onMissing(tba)}
                        className="text-xs text-destructive hover:text-destructive/80 px-2 py-0.5 rounded border border-destructive/30 hover:bg-destructive/10 transition-colors"
                      >
                        Missing
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* Signal pills */}
          {stop.signals.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {stop.signals.map((s, i) => (
                <span key={i} className="text-xs bg-warning/10 text-warning px-2 py-0.5 rounded-full">
                  {s.reason}
                </span>
              ))}
            </div>
          )}

          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => onComplete(stop.tba_numbers, new Date().toISOString())}
              disabled={completing}
              className="btn-primary flex items-center gap-1.5 text-sm"
            >
              {completing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              Complete stop
            </button>
            <button
              onClick={() => onBuildingProfile(stop.normalised_address, stop.block_key)}
              className="btn-secondary flex items-center gap-1.5 text-sm"
            >
              <Building2 className="w-3.5 h-3.5" />
              Log building
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── RTS modal ─────────────────────────────────────────────────────────────────

interface RtsModalProps {
  tba: string;
  routeId: string;
  onClose: () => void;
  onSubmitted: () => void;
}

function RtsModal({ tba, routeId, onClose, onSubmitted }: RtsModalProps) {
  const [rtsType, setRtsType] = useState<string>('no_access');
  const [explanation, setExplanation] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const body: RTSPackageCreate = {
        route_id: routeId,
        tba_number: tba,
        rts_type: rtsType as RTSPackageCreate['rts_type'],
        rts_explanation: explanation.trim() || rtsType,
      };
      await axiosClient.post('/rts/packages', body);
      onSubmitted();
      onClose();
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Failed to record RTS.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-warning" />
          <h3 className="font-semibold text-foreground">Can't deliver — {tba}</h3>
        </div>
        <div className="space-y-3">
          <select
            className="input w-full"
            value={rtsType}
            onChange={e => setRtsType(e.target.value)}
          >
            {Object.entries(RTS_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
          <textarea
            className="input w-full h-20 resize-none"
            placeholder="Additional notes (optional)"
            value={explanation}
            onChange={e => setExplanation(e.target.value)}
          />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={saving} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Record RTS
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Missing modal ─────────────────────────────────────────────────────────────

interface MissingModalProps {
  tba: string;
  routeId: string;
  onClose: () => void;
  onSubmitted: () => void;
}

function MissingModal({ tba, routeId, onClose, onSubmitted }: MissingModalProps) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const body: MissingPackageCreate = { route_id: routeId, tba_number: tba };
      await axiosClient.post('/rts/missing', body);
      onSubmitted();
      onClose();
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Failed to report missing package.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <PackageX className="w-4 h-4 text-destructive" />
          <h3 className="font-semibold text-foreground">Report missing — {tba}</h3>
        </div>
        <p className="text-sm text-muted-foreground">
          This package was not in the bag/tote. Dispatch will be notified to investigate.
        </p>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={saving} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Confirm missing
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Building profile modal ────────────────────────────────────────────────────

interface BuildingModalProps {
  address: string;
  blockKey?: string;
  onClose: () => void;
}

function BuildingModal({ address, blockKey, onClose }: BuildingModalProps) {
  const [buildingType, setBuildingType] = useState<BuildingType>('walkup');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const body: BuildingProfileCreate = {
        normalised_address: address,
        block_key: blockKey,
        building_type: buildingType,
        raw_note: note.trim() || undefined,
      };
      await axiosClient.post('/building-profiles/', body);
      setDone(true);
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Failed to submit building profile.');
    } finally {
      setSaving(false);
    }
  }

  if (done) {
    return (
      <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
        <div className="card w-full max-w-sm space-y-4 text-center">
          <CheckCircle2 className="w-8 h-8 text-success mx-auto" />
          <p className="font-semibold text-foreground">Building profile submitted</p>
          <p className="text-sm text-muted-foreground">Pending review. Thank you!</p>
          <button onClick={onClose} className="btn-primary w-full">Close</button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <Building2 className="w-4 h-4 text-primary" />
          <h3 className="font-semibold text-foreground">Log building type</h3>
        </div>
        <p className="text-xs text-muted-foreground">TBA: {tba}</p>
        <div className="space-y-3">
          <select
            className="input w-full"
            value={buildingType}
            onChange={e => setBuildingType(e.target.value as BuildingType)}
          >
            {BUILDING_TYPE_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <textarea
            className="input w-full h-20 resize-none"
            placeholder="Notes (e.g. gate code, floor, doorbell)"
            value={note}
            onChange={e => setNote(e.target.value)}
          />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={saving} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MyRoute() {
  const { groups } = useAuth();
  const { employeeId } = useNotificationContext();

  const isTrainee = groups.includes('trainee');
  const isWalker  = groups.includes('walker');

  // Route data
  const [routes, setRoutes] = useState<RouteResponse[]>([]);
  const [loadingRoutes, setLoadingRoutes] = useState(true);
  const [routeError, setRouteError] = useState<string | null>(null);

  // Active route (walker picks the one they're doing right now)
  const [activeRouteId, setActiveRouteId] = useState<string | null>(null);

  // Next-stop suggestion list
  const [suggestions, setSuggestions] = useState<NextStopSuggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  // UI state
  const [statusBusy, setStatusBusy] = useState(false);
  const [completingStop, setCompletingStop] = useState(false);
  const [arrivalBusy, setArrivalBusy] = useState(false);
  const [arrivalResult, setArrivalResult] = useState<ArrivalConfirmResponse | null>(null);
  const [phase4Busy, setPhase4Busy] = useState(false);

  // Modals
  const [rtsModal, setRtsModal]     = useState<{ tba: string; routeId: string } | null>(null);
  const [missingModal, setMissingModal] = useState<{ tba: string; routeId: string } | null>(null);
  const [buildingModal, setBuildingModal] = useState<{ address: string; blockKey: string } | null>(null);

  const [error, setError] = useState<string | null>(null);

  // ── data loading ──────────────────────────────────────────────────────────

  const loadRoutes = useCallback(async () => {
    setLoadingRoutes(true);
    setRouteError(null);
    try {
      const { data } = await axiosClient.get<RouteResponse[]>('/walker-routes/me/routes', {
        params: { route_date: TODAY },
      });
      setRoutes(data);
      // Auto-select first assigned/in_progress route
      const active = data.find(r => r.status === 'in_progress') ?? data.find(r => r.status === 'assigned');
      if (active) setActiveRouteId(active.id);
    } catch (e: any) {
      setRouteError(e.response?.data?.detail ?? 'Could not load your route.');
    } finally {
      setLoadingRoutes(false);
    }
  }, []);

  const loadSuggestions = useCallback(async (routeId: string) => {
    setLoadingSuggestions(true);
    try {
      const { data } = await axiosClient.get<NextStopSuggestion[]>(`/rts/stops/${routeId}/next-suggestion`);
      setSuggestions(data);
    } catch {
      setSuggestions([]);
    } finally {
      setLoadingSuggestions(false);
    }
  }, []);

  useEffect(() => { loadRoutes(); }, [loadRoutes]);

  useEffect(() => {
    if (activeRouteId) {
      loadSuggestions(activeRouteId);
    } else {
      setSuggestions([]);
    }
  }, [activeRouteId, loadSuggestions]);

  const activeRoute = routes.find(r => r.id === activeRouteId) ?? null;

  // ── actions ───────────────────────────────────────────────────────────────

  async function handleStartRoute() {
    if (!activeRouteId) return;
    setStatusBusy(true);
    setError(null);
    try {
      await axiosClient.patch(`/walker-routes/routes/${activeRouteId}/status`, { status: 'in_progress' });
      await loadRoutes();
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Failed to start route.');
    } finally {
      setStatusBusy(false);
    }
  }

  async function handleBackAtTruck() {
    if (!activeRouteId) return;
    setStatusBusy(true);
    setError(null);
    try {
      await axiosClient.post(`/walker-routes/routes/${activeRouteId}/back-at-truck`);
      await loadRoutes();
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Failed to record return.');
    } finally {
      setStatusBusy(false);
    }
  }

  async function handleArrivalConfirm() {
    setArrivalBusy(true);
    setError(null);
    try {
      const { data } = await axiosClient.post<ArrivalConfirmResponse>('/walker-routes/arrival-confirm');
      setArrivalResult(data);
      await loadRoutes();
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Arrival confirm failed.');
    } finally {
      setArrivalBusy(false);
    }
  }

  async function handleCompleteStop(routeId: string, tbas: string[], completedAt: string) {
    setCompletingStop(true);
    setError(null);
    try {
      const body: DeliveryStopCreate = { route_id: routeId, tba_numbers: tbas, completed_at: completedAt };
      await axiosClient.post('/rts/stops', body);
      await loadSuggestions(routeId);
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Failed to record stop.');
    } finally {
      setCompletingStop(false);
    }
  }

  async function handlePhase4OptIn() {
    if (!activeRoute) return;
    setPhase4Busy(true);
    setError(null);
    try {
      await axiosClient.post('/walker-routes/phase4-opt-in', {
        truck_assignment_id: activeRoute.truck_assignment_id,
        route_date: activeRoute.route_date,
        route_number: activeRoute.route_number,
      });
      await loadRoutes();
    } catch (e: any) {
      setError(e.response?.data?.detail ?? 'Phase 4 opt-in failed.');
    } finally {
      setPhase4Busy(false);
    }
  }

  // ── render ────────────────────────────────────────────────────────────────

  if (loadingRoutes) {
    return (
      <div className="flex h-60 items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  if (routeError) {
    return (
      <div className="card text-center space-y-2">
        <AlertTriangle className="w-8 h-8 text-warning mx-auto" />
        <p className="font-semibold text-foreground">No route found</p>
        <p className="text-sm text-muted-foreground">{routeError}</p>
        <button onClick={loadRoutes} className="btn-secondary text-sm">Retry</button>
      </div>
    );
  }

  if (routes.length === 0) {
    return (
      <div className="card text-center space-y-2">
        <Package className="w-8 h-8 text-muted-foreground mx-auto" />
        <p className="font-semibold text-foreground">No route assigned today</p>
        <p className="text-sm text-muted-foreground">Check back after sort is committed.</p>
      </div>
    );
  }

  const pairedRoute = routes.find(r => r.assigned_to !== employeeId && r.paired_trainee_id === employeeId);
  const myRoutes    = routes.filter(r => r.assigned_to === employeeId);
  const displayRoutes = myRoutes.length > 0 ? myRoutes : routes;

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header */}
      <div>
        <h1 className="page-title">My Route</h1>
        <p className="text-subtle mt-1">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</p>
      </div>

      {/* Trainee arrival confirm banner */}
      {isTrainee && pairedRoute && !arrivalResult && (
        <div className="card border border-info/30 bg-info/5 space-y-3">
          <div className="flex items-start gap-3">
            <Truck className="w-5 h-5 text-info mt-0.5 flex-shrink-0" />
            <div>
              <p className="font-semibold text-foreground">Confirm your arrival</p>
              <p className="text-sm text-muted-foreground">
                You're paired with trainer on route #{pairedRoute.route_number}. Tap below once you're at the truck — this triggers the sort rebalance.
              </p>
            </div>
          </div>
          <button
            onClick={handleArrivalConfirm}
            disabled={arrivalBusy}
            className="btn-primary flex items-center gap-1.5 text-sm"
          >
            {arrivalBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
            I've arrived at the truck
          </button>
        </div>
      )}

      {/* Arrival confirm result */}
      {arrivalResult && (
        <div className="card border border-success/30 bg-success/5 space-y-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-success" />
            <p className="font-semibold text-foreground text-sm">Arrival confirmed</p>
          </div>
          <div className="text-xs text-muted-foreground space-y-1">
            {arrivalResult.sort_not_yet_committed ? (
              <p>Sort not yet committed — capacity will be set when routes are finalized.</p>
            ) : (
              <>
                <p>Paired capacity: {arrivalResult.paired_capacity_limit} slots</p>
                {arrivalResult.absorbed_route_numbers.length > 0 && (
                  <p>Absorbed routes: #{arrivalResult.absorbed_route_numbers.join(', #')}</p>
                )}
                {arrivalResult.trimmed_route_numbers.length > 0 && (
                  <p>Trimmed routes: #{arrivalResult.trimmed_route_numbers.join(', #')}</p>
                )}
                {arrivalResult.absorbed_route_numbers.length === 0 && arrivalResult.trimmed_route_numbers.length === 0 && (
                  <p>No absorption needed — route is within paired capacity.</p>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Route selector (if multiple routes) */}
      {displayRoutes.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {displayRoutes.map(r => (
            <button
              key={r.id}
              onClick={() => setActiveRouteId(r.id)}
              className={`text-sm px-3 py-1.5 rounded-lg border font-medium transition-colors ${
                activeRouteId === r.id
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'bg-background text-foreground border-border hover:bg-accent'
              }`}
            >
              Route #{r.route_number}
            </button>
          ))}
        </div>
      )}

      {/* Active route summary card */}
      {activeRoute && (
        <div className="card space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="section-title">Route #{activeRoute.route_number}</h2>
                {effortBadge(activeRoute.effort_class)}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {activeRoute.package_count} packages · {activeRoute.slot_cost}/{activeRoute.capacity_limit} slots
                {activeRoute.assigned_to_name && ` · ${activeRoute.assigned_to_name}`}
              </p>
            </div>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${
              activeRoute.status === 'in_progress' ? 'bg-success/10 text-success' :
              activeRoute.status === 'completed'   ? 'bg-muted text-muted-foreground' :
              'bg-accent text-foreground'
            }`}>
              {activeRoute.status.replace('_', ' ')}
            </span>
          </div>

          {/* Route lifecycle buttons */}
          <div className="flex gap-2 flex-wrap">
            {activeRoute.status === 'assigned' && (
              <button
                onClick={handleStartRoute}
                disabled={statusBusy}
                className="btn-primary flex items-center gap-1.5 text-sm"
              >
                {statusBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />}
                Start route
              </button>
            )}
            {activeRoute.status === 'in_progress' && (
              <button
                onClick={handleBackAtTruck}
                disabled={statusBusy}
                className="btn-secondary flex items-center gap-1.5 text-sm"
              >
                {statusBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Truck className="w-3.5 h-3.5" />}
                Back at truck
              </button>
            )}
            {/* Phase 4 opt-in */}
            {isTrainee && activeRoute.trainee_phase === 4 && !activeRoute.phase4_solo_opted_in &&
              activeRoute.status !== 'completed' && (
              <button
                onClick={handlePhase4OptIn}
                disabled={phase4Busy}
                className="btn-secondary flex items-center gap-1.5 text-sm text-info border-info/30"
              >
                {phase4Busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                Solo opt-in (Phase 4)
              </button>
            )}
            {isTrainee && activeRoute.phase4_solo_opted_in && (
              <span className="text-xs text-success font-medium flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Solo delivery opted in
              </span>
            )}
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      )}

      {/* Paired trainer route info (trainee) */}
      {pairedRoute && isTrainee && (
        <div className="card border border-border space-y-1">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Trainer route (shadowed)</p>
          <p className="text-sm text-foreground">
            Route #{pairedRoute.route_number} · {pairedRoute.package_count} packages ·{' '}
            <span className="text-muted-foreground">{pairedRoute.assigned_to_name}</span>
          </p>
          {pairedRoute.status && (
            <span className={`text-xs font-medium capitalize ${pairedRoute.status === 'in_progress' ? 'text-success' : 'text-muted-foreground'}`}>
              {pairedRoute.status.replace('_', ' ')}
            </span>
          )}
        </div>
      )}

      {/* Stop list */}
      {activeRoute && activeRoute.status === 'in_progress' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="section-title">Stops</h3>
            {loadingSuggestions && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
          </div>

          {!loadingSuggestions && suggestions.length === 0 && (
            <div className="card text-center py-8 space-y-2">
              <CheckCircle2 className="w-8 h-8 text-success mx-auto" />
              <p className="font-semibold text-foreground">All stops complete</p>
              <p className="text-sm text-muted-foreground">Tap "Back at truck" when you return.</p>
            </div>
          )}

          {suggestions.map((stop, idx) => (
            <StopCard
              key={`${stop.normalised_address}-${idx}`}
              stop={stop}
              isFirst={idx === 0}
              completing={completingStop}
              onComplete={(tbas, completedAt) => handleCompleteStop(activeRoute.id, tbas, completedAt)}
              onRts={tba => setRtsModal({ tba, routeId: activeRoute.id })}
              onMissing={tba => setMissingModal({ tba, routeId: activeRoute.id })}
              onBuildingProfile={(address, blockKey) => setBuildingModal({ address, blockKey })}
            />
          ))}
        </div>
      )}

      {/* Modals */}
      {rtsModal && (
        <RtsModal
          tba={rtsModal.tba}
          routeId={rtsModal.routeId}
          onClose={() => setRtsModal(null)}
          onSubmitted={() => activeRouteId && loadSuggestions(activeRouteId)}
        />
      )}
      {missingModal && (
        <MissingModal
          tba={missingModal.tba}
          routeId={missingModal.routeId}
          onClose={() => setMissingModal(null)}
          onSubmitted={() => activeRouteId && loadSuggestions(activeRouteId)}
        />
      )}
      {buildingModal && (
        <BuildingModal
          address={buildingModal.address}
          blockKey={buildingModal.blockKey}
          onClose={() => setBuildingModal(null)}
        />
      )}
    </div>
  );
}
