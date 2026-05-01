import React, { useState, useEffect, useCallback } from 'react';
import { MapPin, CheckCircle2, Clock, Truck, RefreshCw, Send } from 'lucide-react';
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
// Driver view — submit / update my anchor point for today
// ---------------------------------------------------------------------------

interface TruckOption { id: string; name: string }

function DriverView() {
  const [trucks, setTrucks] = useState<TruckOption[]>([]);
  const [existing, setExisting] = useState<AnchorPoint | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [truckId, setTruckId] = useState('');
  const [location, setLocation] = useState('');
  const [eta, setEta] = useState('');
  const [notes, setNotes] = useState('');

  const today = getLocalYMD();

  useEffect(() => {
    setLoading(true);
    Promise.allSettled([
      axiosClient.get('/anchor-points/driver/today'),
      axiosClient.get<{ id: string; name: string; is_active: boolean }[]>('/trucks'),
    ]).then(([apRes, trucksRes]) => {
      if (apRes.status === 'fulfilled' && apRes.value.data) {
        const ap: AnchorPoint = apRes.value.data;
        setExisting(ap);
        setTruckId(ap.truck_id);
        setLocation(ap.location);
        setEta(ap.eta ?? '');
        setNotes(ap.notes ?? '');
      }
      if (trucksRes.status === 'fulfilled') {
        setTrucks(trucksRes.value.data.filter(t => t.is_active));
      }
      if (apRes.status === 'rejected' && trucksRes.status === 'rejected') {
        setError('Failed to load anchor point data.');
      }
    }).finally(() => setLoading(false));
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
        eta: eta.trim() || null,
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

  const isConfirmed = !!existing?.confirmed_at;

  return (
    <div className="max-w-lg space-y-6">
      <ErrorBanner message={error} />

      {/* Status card — shown after a record exists */}
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
            <p className="text-xs">Submitted at {formatTime(existing.submitted_at)}</p>
          </div>
          {isConfirmed && (
            <p className="text-xs text-success font-medium">
              Confirmed by dispatch at {formatTime(existing.confirmed_at!)}
            </p>
          )}
        </div>
      )}

      {/* Form — hidden after dispatch confirms */}
      {!isConfirmed && (
        <form onSubmit={handleSubmit} className="card-elevated space-y-4">
          <p className="text-sm font-semibold text-foreground">
            {existing ? 'Update Anchor Point' : 'Submit Anchor Point'}
          </p>

          {success && !submitting && (
            <div className="flex items-center gap-2 text-sm text-success font-medium">
              <CheckCircle2 className="w-4 h-4" />
              {existing ? 'Updated successfully.' : 'Submitted — dispatch has been notified.'}
            </div>
          )}

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Truck
            </label>
            <select
              value={truckId}
              onChange={e => setTruckId(e.target.value)}
              required
              disabled={!!existing}
              className="input w-full disabled:opacity-50"
            >
              <option value="">Select truck…</option>
              {trucks.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            {existing && (
              <p className="text-xs text-muted-foreground">Truck cannot be changed after initial submission.</p>
            )}
          </div>

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

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              ETA at Location
            </label>
            <input
              type="text"
              value={eta}
              onChange={e => setEta(e.target.value)}
              placeholder="e.g. 4:30 PM"
              className="input w-full"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Notes (optional)
            </label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Any additional context for dispatch…"
              rows={3}
              className="input w-full resize-none"
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !truckId || !location.trim()}
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
