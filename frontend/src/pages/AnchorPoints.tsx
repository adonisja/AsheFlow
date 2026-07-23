import { errorText } from '../utils/errorText';
import React, { useState, useEffect, useCallback } from 'react';
import { MapPin, CheckCircle2, Clock, Truck, RefreshCw, Send, History, Navigation, Plus } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import type { AnchorPoint, LocationHint } from '../api/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function StatusBadge({ status }: { status: AnchorPoint['status'] }) {
  if (status === 'arrived') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-success/15 text-success">
        <CheckCircle2 className="w-3 h-3" /> Arrived
      </span>
    );
  }
  if (status === 'relocated') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-accent text-muted-foreground">
        Relocated
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-warning/15 text-warning">
      <Clock className="w-3 h-3" /> Preliminary
    </span>
  );
}

// ---------------------------------------------------------------------------
// ETA slider — 15-minute increments across 24 hours
// ---------------------------------------------------------------------------

const ETA_SLOTS: string[] = (() => {
  const slots: string[] = [];
  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 60; m += 15) {
      const hour12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
      const ampm = h < 12 ? 'AM' : 'PM';
      slots.push(`${hour12}:${String(m).padStart(2, '0')} ${ampm}`);
    }
  }
  return slots;
})();

function defaultEtaIndex(): number {
  const now = new Date();
  const nextMark = Math.ceil((now.getHours() * 60 + now.getMinutes()) / 15) * 15;
  return Math.min(Math.floor(nextMark / 15), ETA_SLOTS.length - 1);
}

function etaToIndex(eta: string): number {
  const idx = ETA_SLOTS.indexOf(eta);
  return idx >= 0 ? idx : defaultEtaIndex();
}

function EtaSlider({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const index = etaToIndex(value);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{ETA_SLOTS[0]}</span>
        <span className="text-base font-bold text-foreground tabular-nums">{value || ETA_SLOTS[defaultEtaIndex()]}</span>
        <span className="text-xs text-muted-foreground">{ETA_SLOTS[ETA_SLOTS.length - 1]}</span>
      </div>
      <input
        type="range" min={0} max={ETA_SLOTS.length - 1} step={1} value={index}
        onChange={e => onChange(ETA_SLOTS[Number(e.target.value)])}
        className="w-full accent-primary cursor-pointer"
      />
      <p className="text-xs text-muted-foreground text-center">Slide to set ETA · 15-minute steps</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AP submission form — used for both initial and relocation submissions
// ---------------------------------------------------------------------------

interface APFormProps {
  hints: LocationHint[];
  onSubmit: (location: string, eta: string | null, notes: string | null) => Promise<void>;
  submitLabel: string;
  submitting: boolean;
  error: string | null;
}

function APForm({ hints, onSubmit, submitLabel, submitting, error }: APFormProps) {
  const [location, setLocation]     = useState('');
  const [eta, setEta]               = useState(() => ETA_SLOTS[defaultEtaIndex()]);
  const [notes, setNotes]           = useState('');
  const [etaEnabled, setEtaEnabled] = useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!location.trim()) return;
    await onSubmit(location.trim(), etaEnabled ? eta : null, notes.trim() || null);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Suggested locations — history or building profile anchors */}
      {hints.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <History className="w-3.5 h-3.5" />
            {hints[0].source === 'building_profile' ? 'Station Anchors' : 'Suggested Locations'}
          </p>
          <div className="flex flex-col gap-1.5">
            {hints.map((h, i) => (
              <button
                key={i} type="button" onClick={() => setLocation(h.label)}
                className={`text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                  location === h.label
                    ? 'border-primary bg-primary/8 text-primary font-medium'
                    : 'border-border bg-surface text-foreground hover:border-primary/50 hover:bg-accent/40'
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate">{h.label}</span>
                  {/* Both scores surfaced so the driver weighs proximity vs. a proven spot */}
                  <span className="flex items-center gap-1 shrink-0">
                    {h.distance_m != null && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-info/10 text-info tabular-nums">
                        ~{h.distance_m < 1000 ? `${h.distance_m} m` : `${(h.distance_m / 1000).toFixed(1)} km`}
                      </span>
                    )}
                    {h.use_count != null && h.use_count > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground tabular-nums">
                        {h.use_count}×
                      </span>
                    )}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground">{h.reason ?? h.sublabel}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Location */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Parking Location <span className="text-danger">*</span>
        </label>
        <input
          type="text" value={location} onChange={e => setLocation(e.target.value)}
          placeholder="e.g. 143-17 Guy Brewer Blvd, Lot B"
          required className="input w-full"
        />
      </div>

      {/* ETA */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">ETA at Location</label>
          <button
            type="button" onClick={() => setEtaEnabled(v => !v)}
            className={`text-xs px-2 py-0.5 rounded-full font-medium transition-colors ${
              etaEnabled ? 'bg-primary/15 text-primary' : 'bg-accent text-muted-foreground hover:text-foreground'
            }`}
          >
            {etaEnabled ? 'On' : 'Skip'}
          </button>
        </div>
        {etaEnabled
          ? <EtaSlider value={eta} onChange={setEta} />
          : <p className="text-xs text-muted-foreground">Toggle on to set an estimated arrival time.</p>
        }
      </div>

      {/* Notes */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Notes (optional)</label>
        <textarea
          value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="Any additional context for dispatch and crew…"
          rows={2} className="input w-full resize-none"
        />
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      <button
        type="submit" disabled={submitting || !location.trim()}
        className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
      >
        {submitting
          ? <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          : <Send className="w-4 h-4" />
        }
        {submitting ? 'Submitting…' : submitLabel}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Driver view
// ---------------------------------------------------------------------------

function DriverView() {
  const [truckId, setTruckId]     = useState<string | null>(null);
  const [truckName, setTruckName] = useState<string | null>(null);
  const [aps, setAps]             = useState<AnchorPoint[]>([]);
  const [hints, setHints]         = useState<LocationHint[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);

  // action state
  const [submitting, setSubmitting]   = useState(false);
  const [arriving, setArriving]       = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showRelocate, setShowRelocate] = useState(false);

  // arrive form — allow optional location change
  const [arriveLocation, setArriveLocation] = useState('');
  const [arriveNotes, setArriveNotes]       = useState('');

  const today = getLocalYMD();

  const loadData = useCallback(() => {
    setLoading(true);
    axiosClient.get('/employees/me')
      .then(meRes => axiosClient.get(`/field-ops/crew/${meRes.data.id}`))
      .then(crewRes => {
        const tid: string | null = crewRes.data.truck_id ?? null;
        const tname: string | null = crewRes.data.truck_name ?? null;
        setTruckId(tid);
        setTruckName(tname);
        return Promise.allSettled([
          axiosClient.get<AnchorPoint[]>('/anchor-points/driver/today'),
          tid ? axiosClient.get<LocationHint[]>(`/anchor-points/truck/${tid}/location-hints`) : Promise.resolve({ data: [] }),
        ]);
      })
      .then(([todayRes, hintsRes]) => {
        if (todayRes.status === 'fulfilled') setAps(todayRes.value.data ?? []);
        if (hintsRes.status === 'fulfilled') setHints(hintsRes.value.data as LocationHint[]);
      })
      .catch(() => setError('Could not load your truck assignment. Make sure you have been dispatched.'))
      .finally(() => setLoading(false));
  }, [today]);

  useEffect(() => { loadData(); }, [loadData]);

  const activeAP = aps.find(ap => ap.status === 'preliminary' || ap.status === 'arrived') ?? null;
  const hasPreliminary = activeAP?.status === 'preliminary';
  const hasArrived     = activeAP?.status === 'arrived';

  const handleSubmitAP = async (location: string, eta: string | null, notes: string | null) => {
    if (!truckId) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await axiosClient.post('/anchor-points/', { truck_id: truckId, date: today, location, eta, notes });
      setShowRelocate(false);
      loadData();
    } catch (e: unknown) {
      setSubmitError(errorText(e, 'Failed to submit anchor point.'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleArrive = async () => {
    if (!activeAP) return;
    setArriving(true);
    setSubmitError(null);
    try {
      await axiosClient.patch(`/anchor-points/${activeAP.id}/arrive`, {
        location: arriveLocation.trim() || undefined,
        notes: arriveNotes.trim() || undefined,
      });
      loadData();
    } catch (e: unknown) {
      setSubmitError(errorText(e, 'Failed to confirm arrival.'));
    } finally {
      setArriving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!truckId) {
    return (
      <div className="w-full">
        <ErrorBanner message={error} />
        {!error && (
          <div className="card text-center py-16 flex flex-col items-center">
            <Truck className="w-10 h-10 text-muted-foreground mb-4 opacity-30" />
            <p className="text-sm font-medium text-foreground">No truck assignment found for today.</p>
            <p className="text-xs text-muted-foreground mt-1">Anchor points can only be submitted once you have been dispatched.</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-lg space-y-6">
      <ErrorBanner message={error} />

      {/* Truck badge */}
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-primary/8 border border-primary/20 w-fit">
        <Truck className="w-4 h-4 text-primary" />
        <span className="text-sm font-semibold text-primary">{truckName ?? 'Your Truck'}</span>
      </div>

      {/* Today's AP timeline */}
      {aps.length > 0 && (
        <div className="card-elevated space-y-3">
          <p className="text-sm font-semibold text-foreground">Today's Anchor Points</p>
          <div className="space-y-2">
            {aps.map((ap, i) => (
              <div
                key={ap.id}
                className={`flex items-start gap-3 p-3 rounded-xl border transition-colors ${
                  ap.status === 'relocated'
                    ? 'border-border bg-accent/20 opacity-60'
                    : 'border-border bg-accent/40'
                }`}
              >
                <div className="flex flex-col items-center pt-1 shrink-0">
                  <div className={`w-2 h-2 rounded-full ${
                    ap.status === 'arrived' ? 'bg-success' : ap.status === 'relocated' ? 'bg-muted-foreground' : 'bg-warning'
                  }`} />
                  {i < aps.length - 1 && <div className="w-px flex-1 bg-border mt-1 min-h-[12px]" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-foreground">AP #{ap.sequence}</span>
                    <StatusBadge status={ap.status} />
                    {ap.confirmed_at && (
                      <span className="text-xs text-success">Dispatch acknowledged</span>
                    )}
                  </div>
                  <p className="text-sm text-foreground mt-0.5 truncate">{ap.location}</p>
                  {ap.eta && <p className="text-xs text-muted-foreground">ETA: {ap.eta}</p>}
                  {ap.notes && <p className="text-xs text-muted-foreground">{ap.notes}</p>}
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Submitted {formatTime(ap.submitted_at)}
                    {ap.arrived_at && ` · Arrived ${formatTime(ap.arrived_at)}`}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Arrive confirmation — shown when there's a preliminary AP */}
      {hasPreliminary && (
        <div className="card-elevated space-y-4">
          <div className="flex items-center gap-2">
            <Navigation className="w-4 h-4 text-success" />
            <p className="text-sm font-semibold text-foreground">Confirm Arrival</p>
          </div>
          <p className="text-xs text-muted-foreground">
            Tap to confirm you've arrived at <strong>{activeAP!.location}</strong>. Optionally update the location if conditions changed.
          </p>
          <div className="space-y-2">
            <input
              type="text" value={arriveLocation} onChange={e => setArriveLocation(e.target.value)}
              placeholder={`${activeAP!.location} (leave blank to keep)`}
              className="input w-full text-sm"
            />
            <input
              type="text" value={arriveNotes} onChange={e => setArriveNotes(e.target.value)}
              placeholder="Notes (optional)"
              className="input w-full text-sm"
            />
          </div>
          {submitError && <p className="text-sm text-danger">{submitError}</p>}
          <button
            onClick={handleArrive} disabled={arriving}
            className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {arriving
              ? <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
              : <CheckCircle2 className="w-4 h-4" />
            }
            {arriving ? 'Confirming…' : 'Arrived at Location'}
          </button>
        </div>
      )}

      {/* Relocate / new AP mid-day */}
      {hasArrived && !showRelocate && (
        <button
          onClick={() => setShowRelocate(true)}
          className="btn-ghost w-full flex items-center justify-center gap-2 border border-dashed border-border hover:border-primary/50 rounded-xl py-3 text-sm text-muted-foreground hover:text-foreground"
        >
          <Plus className="w-4 h-4" /> Set New Anchor Point
        </button>
      )}

      {hasArrived && showRelocate && (
        <div className="card-elevated space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-foreground">New Anchor Point</p>
            <button onClick={() => setShowRelocate(false)} className="text-xs text-muted-foreground hover:text-foreground">Cancel</button>
          </div>
          <p className="text-xs text-muted-foreground">
            Moving to a new area? Set your updated AP — crew and dispatch will be notified. AP #{activeAP!.sequence} will be marked as relocated.
          </p>
          <APForm
            hints={hints}
            onSubmit={handleSubmitAP}
            submitLabel={`Set AP #${activeAP!.sequence + 1}`}
            submitting={submitting}
            error={submitError}
          />
        </div>
      )}

      {/* Initial submission — shown only before any AP exists */}
      {aps.length === 0 && (
        <div className="card-elevated space-y-4">
          <p className="text-sm font-semibold text-foreground">Set Preliminary Anchor Point</p>
          <p className="text-xs text-muted-foreground">
            Set your planned parking location and ETA before leaving the station. Your crew and dispatch will be notified.
          </p>
          <APForm
            hints={hints}
            onSubmit={handleSubmitAP}
            submitLabel="Submit Anchor Point"
            submitting={submitting}
            error={submitError}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dispatch view
// ---------------------------------------------------------------------------

interface AnchorPointWithNames extends AnchorPoint {
  truck_name?: string;
  driver_name?: string;
}

function DispatchView() {
  const [date, setDate]       = useState(getLocalYMD());
  const [records, setRecords] = useState<AnchorPointWithNames[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [apRes, trucksRes, empsRes] = await Promise.all([
        axiosClient.get<AnchorPoint[]>(`/anchor-points/date/${date}`),
        axiosClient.get<{ id: string; name: string }[]>('/trucks'),
        axiosClient.get<{ id: string; name: string }[]>('/employees'),
      ]);
      const truckMap = Object.fromEntries(trucksRes.data.map(t => [t.id, t.name]));
      const empMap   = Object.fromEntries(empsRes.data.map(e => [e.id, e.name]));
      setRecords(apRes.data.map(ap => ({
        ...ap,
        truck_name:  truckMap[ap.truck_id]  ?? ap.truck_id,
        driver_name: empMap[ap.driver_id]   ?? ap.driver_id,
      })));
    } catch {
      setError('Failed to load anchor points.');
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  const confirm = async (apId: string) => {
    setConfirming(apId);
    try {
      const res = await axiosClient.patch<AnchorPoint>(`/anchor-points/${apId}/confirm`);
      setRecords(prev => prev.map(r => r.id === apId ? { ...r, ...res.data } : r));
    } catch {
      setError('Failed to confirm anchor point.');
    } finally {
      setConfirming(null);
    }
  };

  // Group by truck, show active AP per truck prominently
  const byTruck = records.reduce<Record<string, AnchorPointWithNames[]>>((acc, ap) => {
    const key = ap.truck_id;
    if (!acc[key]) acc[key] = [];
    acc[key].push(ap);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <input type="date" value={date} onChange={e => setDate(e.target.value)} className="input" />
        <button onClick={load} className="btn-ghost flex items-center gap-2">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      <ErrorBanner message={error} />

      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {!loading && records.length === 0 && (
        <div className="card text-center py-12">
          <MapPin className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
          <p className="text-sm text-muted-foreground">No anchor points submitted for {date}.</p>
        </div>
      )}

      {!loading && Object.entries(byTruck).map(([truckId, truckAPs]) => {
        const sorted  = [...truckAPs].sort((a, b) => a.sequence - b.sequence);
        const activeAP = sorted.find(ap => ap.status === 'preliminary' || ap.status === 'arrived');
        const truck_name  = sorted[0]?.truck_name;
        const driver_name = sorted[0]?.driver_name;

        return (
          <div key={truckId} className="card-elevated space-y-3">
            {/* Truck header */}
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <Truck className="w-4 h-4 text-muted-foreground" />
                <span className="font-semibold text-foreground text-sm">{truck_name}</span>
                <span className="text-xs text-muted-foreground">· {driver_name}</span>
              </div>
              {activeAP && (
                <StatusBadge status={activeAP.status} />
              )}
            </div>

            {/* AP timeline for this truck */}
            <div className="space-y-2">
              {sorted.map(ap => (
                <div
                  key={ap.id}
                  className={`flex items-start justify-between gap-3 p-3 rounded-xl border ${
                    ap.status === 'relocated'
                      ? 'border-border opacity-50'
                      : 'border-primary/20 bg-primary/4'
                  }`}
                >
                  <div className="space-y-0.5 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-semibold text-muted-foreground">AP #{ap.sequence}</span>
                      <StatusBadge status={ap.status} />
                      {ap.confirmed_at && (
                        <span className="text-xs text-success font-medium">Acknowledged {formatTime(ap.confirmed_at)}</span>
                      )}
                    </div>
                    <p className="text-sm font-medium text-foreground truncate">{ap.location}</p>
                    {ap.eta && <p className="text-xs text-muted-foreground">ETA: {ap.eta}</p>}
                    {ap.notes && <p className="text-xs text-muted-foreground">{ap.notes}</p>}
                    <p className="text-xs text-muted-foreground">
                      Submitted {formatTime(ap.submitted_at)}
                      {ap.arrived_at && ` · Arrived ${formatTime(ap.arrived_at)}`}
                    </p>
                  </div>
                  {!ap.confirmed_at && ap.status !== 'relocated' && (
                    <button
                      onClick={() => confirm(ap.id)}
                      disabled={confirming === ap.id}
                      className="btn-primary shrink-0 flex items-center gap-1.5 text-xs disabled:opacity-50"
                    >
                      {confirming === ap.id
                        ? <div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        : <CheckCircle2 className="w-3 h-3" />
                      }
                      Acknowledge
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page root
// ---------------------------------------------------------------------------

export default function AnchorPoints() {
  const { groups } = useAuth();
  const isDriver   = groups.includes('driver');
  const isDispatch = groups.some(g => ['dispatch', 'management', 'admin'].includes(g));

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        eyebrow="Field Operations"
        title="Anchor Points"
        description={
          isDriver
            ? "Set your planned parking location before leaving the station. Confirm arrival on-site, and update if you relocate mid-day."
            : "Monitor driver anchor point submissions — preliminary locations, arrivals, and mid-day relocations."
        }
      />
      {isDriver   && <DriverView />}
      {isDispatch && !isDriver && <DispatchView />}
      {!isDriver  && !isDispatch && (
        <div className="card text-center py-12">
          <MapPin className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
          <p className="text-sm text-muted-foreground">Anchor points are for drivers and dispatch only.</p>
        </div>
      )}
    </div>
  );
}
