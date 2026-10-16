import { errorText } from '../utils/errorText';
import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MapPin, CheckCircle2, Clock, Truck, RefreshCw, Send, History, Navigation, Plus, AlertTriangle, ExternalLink, ChevronDown } from 'lucide-react';
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
            Moving to a new area? Set your updated AP. Crew and dispatch will be notified. AP #{activeAP!.sequence} will be marked as relocated.
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

// ADR-522 D1: one truck state, derived in one place. The truck's CURRENT anchor
// point is its newest non-relocated one; earlier ones are history.
type TruckState = 'late' | 'en_route' | 'at_ap' | 'departed';

interface TruckBoard {
  truckId: string;
  truckName: string;
  driverName: string;
  current: AnchorPointWithNames;
  history: AnchorPointWithNames[];   // relocated, newest first
  state: TruckState;
  needsAck: boolean;
}

const STATE_META: Record<TruckState, { label: string; tone: string; rank: number }> = {
  late:     { label: 'Late',            tone: 'danger',  rank: 0 },
  en_route: { label: 'En route',        tone: 'info',    rank: 2 },
  at_ap:    { label: 'At anchor point', tone: 'success', rank: 3 },
  departed: { label: 'Departed',        tone: 'muted',   rank: 4 },
};

// Tone -> classes. Literal strings so Tailwind's scanner keeps them.
const TONE: Record<string, { chip: string; band: string; dot: string }> = {
  danger:  { chip: 'bg-danger/10 text-danger',   band: 'bg-danger/5 border-danger/20',   dot: 'bg-danger' },
  warning: { chip: 'bg-warning/10 text-warning', band: 'bg-warning/5 border-warning/20', dot: 'bg-warning' },
  success: { chip: 'bg-success/10 text-success', band: 'bg-success/5 border-success/20', dot: 'bg-success' },
  info:    { chip: 'bg-info/10 text-info',       band: 'bg-info/5 border-info/20',       dot: 'bg-info' },
  muted:   { chip: 'bg-muted text-muted-foreground', band: 'bg-muted/40 border-border',  dot: 'bg-muted-foreground' },
};

function stateOf(ap: AnchorPoint): TruckState {
  if (ap.actual_departed_at) return 'departed';
  if (ap.status === 'arrived') return 'at_ap';
  return ap.is_running_late ? 'late' : 'en_route';
}

function buildBoards(records: AnchorPointWithNames[]): TruckBoard[] {
  const byTruck = new Map<string, AnchorPointWithNames[]>();
  for (const ap of records) byTruck.set(ap.truck_id, [...(byTruck.get(ap.truck_id) ?? []), ap]);
  const boards: TruckBoard[] = [];
  for (const [truckId, aps] of byTruck) {
    const newestFirst = [...aps].sort((a, b) => b.sequence - a.sequence);
    const current = newestFirst.find(ap => ap.status !== 'relocated') ?? newestFirst[0];
    boards.push({
      truckId,
      truckName: current.truck_name ?? truckId,
      driverName: current.driver_name ?? '',
      current,
      history: newestFirst.filter(ap => ap.id !== current.id),
      state: stateOf(current),
      needsAck: aps.some(ap => ap.status !== 'relocated' && !ap.confirmed_at),
    });
  }
  // ADR-522 D3: late first, then anything awaiting acknowledgment, then by state.
  const rank = (b: TruckBoard) => b.state === 'late' ? 0 : b.needsAck ? 1 : STATE_META[b.state].rank;
  return boards.sort((x, y) => rank(x) - rank(y) || x.truckName.localeCompare(y.truckName));
}

/** Minutes past an "h:mm AM" ETA on the AP's day, in the viewer's timezone.
 *  The server flags lateness in the COMPANY timezone (ADR-112); a dispatcher
 *  is normally in it, and this only words the chip, it never decides "late". */
function minutesOver(ap: AnchorPoint, now: Date = new Date()): number | null {
  const m = ap.eta?.match(/^(\d{1,2}):(\d{2})\s*([AP]M)$/i);
  if (!m) return null;
  const [y, mo, d] = ap.date.split('-').map(Number);
  const h = (Number(m[1]) % 12) + (m[3].toUpperCase() === 'PM' ? 12 : 0);
  const mins = Math.floor((now.getTime() - new Date(y, mo - 1, d, h, Number(m[2])).getTime()) / 60000);
  return mins > 0 ? mins : null;
}

function overText(mins: number): string {
  return mins < 60 ? `${mins} min over` : `${Math.floor(mins / 60)} h ${mins % 60} min over`;
}

/** Why the truck is in its state, in a few words. */
function stateReason(b: TruckBoard): string | null {
  const ap = b.current;
  if (b.state === 'late') {
    const over = minutesOver(ap);
    return [ap.eta && `ETA ${ap.eta}`, over != null ? overText(over) : null].filter(Boolean).join(' · ') || null;
  }
  if (b.state === 'en_route') return ap.eta ? `ETA ${ap.eta}` : null;
  if (b.state === 'at_ap' && ap.arrived_at) return `since ${formatTime(ap.arrived_at)}`;
  if (b.state === 'departed' && ap.actual_departed_at) return `at ${formatTime(ap.actual_departed_at)}`;
  return null;
}

type Filter = TruckState | 'ack' | null;

function SummaryStrip({ boards, filter, onFilter }: {
  boards: TruckBoard[]; filter: Filter; onFilter: (f: Filter) => void;
}) {
  const items: { key: Exclude<Filter, null>; label: string; tone: string; count: number }[] = [
    { key: 'late',     label: 'Late',              tone: 'danger',  count: boards.filter(b => b.state === 'late').length },
    { key: 'ack',      label: 'To acknowledge',    tone: 'warning', count: boards.filter(b => b.needsAck).length },
    { key: 'en_route', label: 'En route',          tone: 'info',    count: boards.filter(b => b.state === 'en_route').length },
    { key: 'at_ap',    label: 'At anchor point',   tone: 'success', count: boards.filter(b => b.state === 'at_ap').length },
    { key: 'departed', label: 'Departed',          tone: 'muted',   count: boards.filter(b => b.state === 'departed').length },
  ];
  const num: Record<string, string> = {
    danger: 'text-danger', info: 'text-info', warning: 'text-warning', success: 'text-success', muted: 'text-foreground',
  };
  return (
    <div className="grid grid-cols-5 gap-1.5 sm:gap-2" role="group" aria-label="Filter trucks by state">
      {items.map(it => {
        const active = filter === it.key;
        return (
          <button key={it.key} type="button" aria-pressed={active}
            onClick={() => onFilter(active ? null : it.key)}
            className={`text-left rounded-xl border px-2 py-2 sm:px-3 sm:py-2.5 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
              active ? 'border-primary bg-primary/5' : 'border-border bg-card hover:bg-accent'
            } ${it.count === 0 && !active ? 'opacity-60' : ''}`}>
            <span className={`block text-xl sm:text-2xl font-semibold tabular-nums ${it.count > 0 ? num[it.tone] : 'text-muted-foreground'}`}>
              {it.count}
            </span>
            <span className="block text-[11px] sm:text-xs leading-tight text-muted-foreground">{it.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Submitted -> ETA -> Arrived -> Departed, each with its time or a dash. */
function StepRow({ ap, late }: { ap: AnchorPoint; late: boolean }) {
  const steps: { label: string; value: string | null; done: boolean; warn?: boolean }[] = [
    { label: 'Submitted', value: formatTime(ap.submitted_at), done: true },
    { label: 'ETA',       value: ap.eta, done: !!ap.arrived_at, warn: late },
    { label: 'Arrived',   value: ap.arrived_at ? formatTime(ap.arrived_at) : null, done: !!ap.arrived_at },
    {
      label: 'Departed',
      value: ap.actual_departed_at ? formatTime(ap.actual_departed_at)
        : ap.expected_departure_at ? `planned ${formatTime(ap.expected_departure_at)}` : null,
      done: !!ap.actual_departed_at,
    },
  ];
  return (
    <ol className="grid grid-cols-4">
      {steps.map((st, i) => (
        <li key={st.label} className="relative pr-2">
          {/* connector to the next step */}
          {i < steps.length - 1 && (
            <span aria-hidden className={`absolute left-3 right-0 top-[5px] h-px ${steps[i + 1].done ? 'bg-primary/50' : 'bg-border'}`} />
          )}
          <span aria-hidden className={`relative block w-[11px] h-[11px] rounded-full border-2 ${
            st.warn ? 'border-danger bg-danger/20' : st.done ? 'border-primary bg-primary' : 'border-border bg-card'
          }`} />
          <span className="mt-1.5 block text-[11px] uppercase tracking-wide text-muted-foreground">{st.label}</span>
          <span className={`block text-sm tabular-nums ${st.warn ? 'text-danger font-medium' : st.value ? 'text-foreground' : 'text-muted-foreground'}`}>
            {st.value ?? '—'}
          </span>
        </li>
      ))}
    </ol>
  );
}

function mapsHref(ap: AnchorPoint): string {
  const q = ap.lat != null && ap.lng != null ? `${ap.lat},${ap.lng}` : ap.location;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
}

function TruckCard({ board, focused, confirming, onConfirm }: {
  board: TruckBoard; focused: boolean; confirming: string | null; onConfirm: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const meta = STATE_META[board.state];
  const tone = TONE[meta.tone];
  const ap = board.current;
  const reason = stateReason(board);
  const unacked = [ap, ...board.history].filter(x => x.status !== 'relocated' && !x.confirmed_at);

  return (
    <article id={`truck-${board.truckId}`} aria-label={`${board.truckName}, ${meta.label}`}
      className={`card !p-0 overflow-hidden ${focused ? 'outline outline-2 outline-offset-2 outline-primary' : ''}`}>
      {/* Header band: who, and the one state that matters, with its reason */}
      <header className={`flex items-center justify-between gap-3 flex-wrap px-5 py-3 border-b ${tone.band}`}>
        <div className="flex items-center gap-3 min-w-0">
          <span className="grid place-items-center w-9 h-9 rounded-xl bg-card border border-border shrink-0">
            <Truck className="w-4 h-4 text-foreground" />
          </span>
          <div className="min-w-0">
            <h3 className="font-semibold text-foreground leading-tight truncate">{board.truckName}</h3>
            <p className="text-xs text-muted-foreground truncate">{board.driverName}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${tone.chip}`}>
            {board.state === 'late' ? <AlertTriangle className="w-3.5 h-3.5" />
              : board.state === 'at_ap' ? <CheckCircle2 className="w-3.5 h-3.5" />
              : board.state === 'departed' ? <Navigation className="w-3.5 h-3.5" />
              : <Clock className="w-3.5 h-3.5" />}
            {meta.label}
            {reason && <span className="font-normal opacity-80">· {reason}</span>}
          </span>
          {unacked.length > 0 && (
            <button onClick={() => onConfirm(unacked[0].id)} disabled={confirming === unacked[0].id}
              className="btn-primary !px-3 !py-1.5 text-xs disabled:opacity-50">
              {confirming === unacked[0].id
                ? <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                : <CheckCircle2 className="w-3.5 h-3.5" />}
              Acknowledge
            </button>
          )}
        </div>
      </header>

      <div className="px-5 py-4 space-y-4">
        {/* Where the truck is (or is going) */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
              Anchor point #{ap.sequence}{board.history.length > 0 ? ' · current' : ''}
            </p>
            <p className="text-lg font-semibold text-foreground leading-snug">{ap.location}</p>
            {ap.notes && <p className="text-sm text-muted-foreground">{ap.notes}</p>}
          </div>
          <a href={mapsHref(ap)} target="_blank" rel="noopener noreferrer"
            className="btn-ghost !px-2.5 !py-1.5 text-xs shrink-0">
            <MapPin className="w-3.5 h-3.5" /> Maps <ExternalLink className="w-3 h-3" />
          </a>
        </div>

        <StepRow ap={ap} late={board.state === 'late'} />

        {/* Who has seen it */}
        <div className="flex items-center justify-between gap-3 flex-wrap pt-3 border-t border-border text-xs">
          {ap.confirmed_at ? (
            <span className="inline-flex items-center gap-1.5 text-success">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Acknowledged {formatTime(ap.confirmed_at)}{ap.confirmed_by_name ? ` by ${ap.confirmed_by_name}` : ''}
            </span>
          ) : (
            <span className="text-muted-foreground">Not acknowledged yet</span>
          )}
          {board.history.length > 0 && (
            <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <History className="w-3.5 h-3.5" />
              Moved {board.history.length} {board.history.length === 1 ? 'time' : 'times'}
              <ChevronDown className={`w-3.5 h-3.5 transition-transform motion-reduce:transition-none ${open ? 'rotate-180' : ''}`} />
            </button>
          )}
        </div>

        {open && board.history.length > 0 && (
          <ol className="space-y-2 border-l border-border pl-4">
            {board.history.map(h => (
              <li key={h.id} className="relative text-xs">
                <span aria-hidden className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-border" />
                <span className="text-muted-foreground">#{h.sequence} · submitted {formatTime(h.submitted_at)}
                  {h.arrived_at && ` · arrived ${formatTime(h.arrived_at)}`}</span>
                <p className="text-foreground line-through decoration-muted-foreground/50">{h.location}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </article>
  );
}

function DispatchView() {
  // ADR-519: a notification opens this page at its truck and day
  // (`?id=<truck>&date=<YYYY-MM-DD>`).
  const [params] = useSearchParams();
  const focusTruck = params.get('id');
  const [date, setDate]       = useState(params.get('date') || getLocalYMD());
  const [records, setRecords] = useState<AnchorPointWithNames[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [filter, setFilter]   = useState<Filter>(null);

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
        // The date read leaves confirmed_by_name empty; the roster is already here.
        confirmed_by_name: ap.confirmed_by_name ?? (ap.confirmed_by ? empMap[ap.confirmed_by] ?? null : null),
      })));
    } catch {
      setError('Failed to load anchor points.');
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  // Bring the linked truck into view once its card exists.
  useEffect(() => {
    if (!focusTruck || loading) return;
    document.getElementById(`truck-${focusTruck}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusTruck, loading, records]);
  const focusMissing = !!focusTruck && !loading && records.length > 0 && !records.some(r => r.truck_id === focusTruck);

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

  const boards = buildBoards(records);
  const shown = boards.filter(b =>
    filter === null ? true : filter === 'ack' ? b.needsAck : b.state === filter);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <input type="date" value={date} onChange={e => { setDate(e.target.value); setFilter(null); }} className="input" />
        {focusMissing && <span className="text-xs text-muted-foreground">That truck has no anchor point on this day.</span>}
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

      {!loading && boards.length > 0 && (
        <>
          <SummaryStrip boards={boards} filter={filter} onFilter={setFilter} />
          {shown.length === 0 && (
            <p className="text-sm text-muted-foreground">No trucks in this group.{' '}
              <button className="underline" onClick={() => setFilter(null)}>Show all</button>
            </p>
          )}
          <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {shown.map(b => (
              <TruckCard key={b.truckId} board={b} focused={b.truckId === focusTruck}
                confirming={confirming} onConfirm={confirm} />
            ))}
          </div>
        </>
      )}
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
            : "Monitor driver anchor point submissions: preliminary locations, arrivals, and mid-day relocations."
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
