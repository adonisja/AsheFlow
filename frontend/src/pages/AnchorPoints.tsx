import React, { useState, useEffect, useCallback } from 'react';
import { MapPin, CheckCircle2, Clock, Truck, RefreshCw, Send, History } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import type { AnchorPoint } from '../api/types';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function StatusBadge({ confirmed }: { confirmed: boolean }) {
  if (confirmed) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-success/15 text-success">
        <CheckCircle2 className="w-3 h-3" /> Confirmed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-warning/15 text-warning">
      <Clock className="w-3 h-3" /> Pending
    </span>
  );
}

// ---------------------------------------------------------------------------
// ETA time slider — 15-minute increments from 12:00 PM to 11:45 PM
// ---------------------------------------------------------------------------

// Build slots: 12:00 PM … 11:45 PM (48 slots). Drivers are EOD so AM times
// aren't useful. Slot 0 = 12:00 PM.
const ETA_SLOTS: string[] = (() => {
  const slots: string[] = [];
  for (let h = 12; h < 24; h++) {
    for (let m = 0; m < 60; m += 15) {
      const hour12 = h > 12 ? h - 12 : h;
      const ampm = 'PM';
      slots.push(`${hour12}:${String(m).padStart(2, '0')} ${ampm}`);
    }
  }
  return slots;
})();

const DEFAULT_ETA_INDEX = 8; // 2:00 PM

function etaToIndex(eta: string): number {
  const idx = ETA_SLOTS.indexOf(eta);
  return idx >= 0 ? idx : DEFAULT_ETA_INDEX;
}

function EtaSlider({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const index = etaToIndex(value);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{ETA_SLOTS[0]}</span>
        <span className="text-base font-bold text-foreground tabular-nums">{value || ETA_SLOTS[DEFAULT_ETA_INDEX]}</span>
        <span className="text-xs text-muted-foreground">{ETA_SLOTS[ETA_SLOTS.length - 1]}</span>
      </div>
      <input
        type="range"
        min={0}
        max={ETA_SLOTS.length - 1}
        step={1}
        value={index}
        onChange={e => onChange(ETA_SLOTS[Number(e.target.value)])}
        className="w-full accent-primary cursor-pointer"
      />
      <p className="text-xs text-muted-foreground text-center">Slide to set ETA · 15-minute steps</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Driver view — submit / update my anchor point for today
// ---------------------------------------------------------------------------

function DriverView() {
  const [truckId, setTruckId]       = useState<string | null>(null);
  const [truckName, setTruckName]   = useState<string | null>(null);
  const [history, setHistory]       = useState<AnchorPoint[]>([]);
  const [existing, setExisting]     = useState<AnchorPoint | null>(null);
  const [loading, setLoading]       = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const [success, setSuccess]       = useState(false);

  const [location, setLocation] = useState('');
  const [eta, setEta]           = useState(ETA_SLOTS[DEFAULT_ETA_INDEX]);
  const [notes, setNotes]       = useState('');
  const [etaEnabled, setEtaEnabled] = useState(false);

  const today = getLocalYMD();

  useEffect(() => {
    setLoading(true);

    // Step 1: get today's truck assignment
    axiosClient.get('/employees/me')
      .then(meRes => {
        const employeeId: string = meRes.data.id;
        return axiosClient.get(`/field-ops/crew/${employeeId}`);
      })
      .then(crewRes => {
        const tid: string | null = crewRes.data.truck_id ?? null;
        const tname: string | null = crewRes.data.truck_name ?? null;
        setTruckId(tid);
        setTruckName(tname);

        // Step 2: load existing AP + truck history in parallel
        return Promise.allSettled([
          axiosClient.get('/anchor-points/driver/today'),
          tid ? axiosClient.get<AnchorPoint[]>(`/anchor-points/truck/${tid}`, { params: { limit: 5 } }) : Promise.resolve({ data: [] }),
        ]);
      })
      .then(([apRes, histRes]) => {
        if (apRes.status === 'fulfilled' && apRes.value.data) {
          const ap: AnchorPoint = apRes.value.data;
          setExisting(ap);
          setLocation(ap.location);
          if (ap.eta) {
            setEta(ap.eta);
            setEtaEnabled(true);
          }
          setNotes(ap.notes ?? '');
        }
        if (histRes.status === 'fulfilled') {
          // Exclude today's record from history suggestions
          const past = (histRes.value.data as AnchorPoint[]).filter(r => r.date !== today);
          setHistory(past.slice(0, 5));
        }
      })
      .catch(() => setError('Could not load your truck assignment for today. Make sure you have been dispatched.'))
      .finally(() => setLoading(false));
  }, [today]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!truckId || !location.trim()) return;
    setSubmitting(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await axiosClient.post<AnchorPoint>('/anchor-points/', {
        truck_id: truckId,
        date: today,
        location: location.trim(),
        eta: etaEnabled ? eta : null,
        notes: notes.trim() || null,
      });
      setExisting(res.data);
      setSuccess(true);
    } catch {
      setError('Failed to submit anchor point. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Not dispatched today
  if (!truckId) {
    return (
      <div className="max-w-lg">
        <ErrorBanner message={error} />
        {!error && (
          <div className="card text-center py-12">
            <Truck className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
            <p className="text-sm font-medium text-foreground">No truck assignment found for today.</p>
            <p className="text-xs text-muted-foreground mt-1">Anchor points can only be submitted once you have been dispatched.</p>
          </div>
        )}
      </div>
    );
  }

  const isConfirmed = !!existing?.confirmed_at;

  return (
    <div className="max-w-lg space-y-6">
      <ErrorBanner message={error} />

      {/* Truck badge */}
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-primary/8 border border-primary/20 w-fit">
        <Truck className="w-4 h-4 text-primary" />
        <span className="text-sm font-semibold text-primary">{truckName ?? 'Your Truck'}</span>
      </div>

      {/* Today's submission status card */}
      {existing && (
        <div className="card-elevated space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-foreground">Today's Submission</p>
            <StatusBadge confirmed={isConfirmed} />
          </div>
          <div className="space-y-1 text-sm text-muted-foreground">
            <p><span className="font-medium text-foreground">Location:</span> {existing.location}</p>
            {existing.eta && <p><span className="font-medium text-foreground">ETA:</span> {existing.eta}</p>}
            {existing.notes && <p><span className="font-medium text-foreground">Notes:</span> {existing.notes}</p>}
            <p className="text-xs">Submitted {formatTime(existing.submitted_at)}</p>
          </div>
          {isConfirmed && (
            <p className="text-xs text-success font-medium">
              Confirmed by dispatch at {formatTime(existing.confirmed_at!)}
            </p>
          )}
        </div>
      )}

      {/* Form — hidden once dispatch confirms */}
      {!isConfirmed && (
        <form onSubmit={handleSubmit} className="card-elevated space-y-5">
          <p className="text-sm font-semibold text-foreground">
            {existing ? 'Update Anchor Point' : 'Submit Anchor Point'}
          </p>

          {success && !submitting && (
            <div className="flex items-center gap-2 text-sm text-success font-medium">
              <CheckCircle2 className="w-4 h-4" />
              {existing ? 'Updated — dispatch notified.' : 'Submitted — dispatch has been notified.'}
            </div>
          )}

          {/* Recent locations quick-fill */}
          {history.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                <History className="w-3.5 h-3.5" /> Recent Locations
              </p>
              <div className="flex flex-col gap-1.5">
                {history.map(h => (
                  <button
                    key={h.id}
                    type="button"
                    onClick={() => setLocation(h.location)}
                    className={`text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                      location === h.location
                        ? 'border-primary bg-primary/8 text-primary font-medium'
                        : 'border-border bg-surface text-foreground hover:border-primary/50 hover:bg-accent/40'
                    }`}
                  >
                    <span className="block truncate">{h.location}</span>
                    <span className="text-xs text-muted-foreground">{h.date}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Location input */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Parking Location <span className="text-danger">*</span>
            </label>
            <input
              type="text"
              value={location}
              onChange={e => setLocation(e.target.value)}
              placeholder="e.g. 143-17 Guy Brewer Blvd, Lot B"
              required
              className="input w-full"
            />
          </div>

          {/* ETA slider */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                ETA at Location
              </label>
              <button
                type="button"
                onClick={() => setEtaEnabled(v => !v)}
                className={`text-xs px-2 py-0.5 rounded-full font-medium transition-colors ${
                  etaEnabled
                    ? 'bg-primary/15 text-primary'
                    : 'bg-accent text-muted-foreground hover:text-foreground'
                }`}
              >
                {etaEnabled ? 'On' : 'Skip'}
              </button>
            </div>
            {etaEnabled && <EtaSlider value={eta} onChange={setEta} />}
            {!etaEnabled && (
              <p className="text-xs text-muted-foreground">Toggle on to set an estimated arrival time.</p>
            )}
          </div>

          {/* Notes */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Notes (optional)
            </label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Any additional context for dispatch…"
              rows={2}
              className="input w-full resize-none"
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !location.trim()}
            className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {submitting ? (
              <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            {submitting ? 'Submitting…' : existing ? 'Update' : 'Submit'}
          </button>
        </form>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dispatch view — confirm anchor points for a given date
// ---------------------------------------------------------------------------

interface AnchorPointWithNames extends AnchorPoint {
  truck_name?: string;
  driver_name?: string;
}

function DispatchView() {
  const [date, setDate] = useState(getLocalYMD());
  const [records, setRecords] = useState<AnchorPointWithNames[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      const empMap = Object.fromEntries(empsRes.data.map(e => [e.id, e.name]));

      setRecords(apRes.data.map(ap => ({
        ...ap,
        truck_name: truckMap[ap.truck_id] ?? ap.truck_id,
        driver_name: empMap[ap.driver_id] ?? ap.driver_id,
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

  const pending = records.filter(r => !r.confirmed_at);
  const confirmed = records.filter(r => !!r.confirmed_at);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="date"
          value={date}
          onChange={e => setDate(e.target.value)}
          className="input"
        />
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

      {!loading && pending.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground">
            Pending Confirmation ({pending.length})
          </p>
          {pending.map(ap => (
            <div key={ap.id} className="card-elevated flex items-start justify-between gap-4 flex-wrap">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Truck className="w-4 h-4 text-muted-foreground" />
                  <p className="font-semibold text-foreground text-sm">{ap.truck_name}</p>
                  <StatusBadge confirmed={false} />
                </div>
                <p className="text-sm text-muted-foreground">Driver: {ap.driver_name}</p>
                <p className="text-sm">
                  <span className="font-medium text-foreground">Location:</span>{' '}
                  <span className="text-muted-foreground">{ap.location}</span>
                </p>
                {ap.eta && (
                  <p className="text-sm">
                    <span className="font-medium text-foreground">ETA:</span>{' '}
                    <span className="text-muted-foreground">{ap.eta}</span>
                  </p>
                )}
                {ap.notes && (
                  <p className="text-sm">
                    <span className="font-medium text-foreground">Notes:</span>{' '}
                    <span className="text-muted-foreground">{ap.notes}</span>
                  </p>
                )}
                <p className="text-xs text-muted-foreground">Submitted {formatTime(ap.submitted_at)}</p>
              </div>
              <button
                onClick={() => confirm(ap.id)}
                disabled={confirming === ap.id}
                className="btn-primary flex items-center gap-2 shrink-0 disabled:opacity-50"
              >
                {confirming === ap.id ? (
                  <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                ) : (
                  <CheckCircle2 className="w-4 h-4" />
                )}
                Confirm
              </button>
            </div>
          ))}
        </div>
      )}

      {!loading && confirmed.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground">
            Confirmed ({confirmed.length})
          </p>
          {confirmed.map(ap => (
            <div key={ap.id} className="card flex items-start justify-between gap-4 flex-wrap opacity-75">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Truck className="w-4 h-4 text-muted-foreground" />
                  <p className="font-semibold text-foreground text-sm">{ap.truck_name}</p>
                  <StatusBadge confirmed={true} />
                </div>
                <p className="text-sm text-muted-foreground">Driver: {ap.driver_name}</p>
                <p className="text-sm">
                  <span className="font-medium text-foreground">Location:</span>{' '}
                  <span className="text-muted-foreground">{ap.location}</span>
                </p>
                {ap.eta && (
                  <p className="text-sm text-muted-foreground">ETA: {ap.eta}</p>
                )}
                <p className="text-xs text-muted-foreground">
                  Confirmed {formatTime(ap.confirmed_at!)}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page root — branches on role
// ---------------------------------------------------------------------------

export default function AnchorPoints() {
  const { groups } = useAuth();
  const isDriver = groups.includes('driver');
  const isDispatch = groups.some(g => ['dispatch', 'management', 'admin'].includes(g));

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        eyebrow="Field Operations"
        title="Anchor Points"
        description={
          isDriver
            ? "Submit your truck's end-of-day parking location and ETA. Dispatch will confirm once received."
            : "Review and confirm EOD anchor point submissions from drivers."
        }
      />
      {isDriver && <DriverView />}
      {isDispatch && !isDriver && <DispatchView />}
      {!isDriver && !isDispatch && (
        <div className="card text-center py-12">
          <MapPin className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
          <p className="text-sm text-muted-foreground">Anchor points are for drivers and dispatch only.</p>
        </div>
      )}
    </div>
  );
}
