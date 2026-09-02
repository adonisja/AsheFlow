import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pin, Plus, Trash2, X, AlertTriangle, RotateCcw, Truck as TruckIcon, CalendarDays } from 'lucide-react';

import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import ErrorBanner from '../components/ui/ErrorBanner';
import type { CrewPin, Employee, Truck, TruckPin, Weekday } from '../api/types';

/** Crew pins (ADR-357).
 *
 *  A pin is a CONSTRAINT, not a preference. Preferences top out around 88% for
 *  one person, so five people each winning their own weighted draw is well under
 *  1% — "this crew always rides together" cannot be expressed as a weight. The
 *  driver is the anchor: members are seated on whichever truck the driver gets,
 *  before any other assignment pass runs.
 *
 *  The screen has to carry that distinction, because "pinned" and "preferred"
 *  look identical in a list. Hence the explicit anchor labelling and the
 *  inactive-reason callout rather than a bare disabled state. */
export default function CrewPins() {
  const [pins, setPins] = useState<CrewPin[]>([]);
  const [truckPins, setTruckPins] = useState<TruckPin[]>([]);
  const [trucks, setTrucks] = useState<Truck[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pinRes, truckPinRes, empRes, truckRes] = await Promise.all([
        axiosClient.get<CrewPin[]>('/crew-pins'),
        axiosClient.get<TruckPin[]>('/truck-pins'),
        axiosClient.get<Employee[]>('/employees/'),
        axiosClient.get<Truck[]>('/trucks/'),
      ]);
      setPins(pinRes.data);
      setTruckPins(truckPinRes.data);
      setEmployees(empRes.data.filter(e => e.is_active));
      setTrucks(truckRes.data);
      setError(null);
    } catch (err: unknown) {
      setError(errorText(err, 'Could not load pins.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  /* Everyone already on the CREW axis. The server refuses these with a 409
     (ADR-358 D2); disabling them here means the dispatcher sees WHY before they
     click, rather than after. */
  const crewPinnedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of pins) {
      if (!p.is_active) continue;
      ids.add(p.driver_id);
      for (const m of p.members) ids.add(m.employee_id);
    }
    return ids;
  }, [pins]);

  const drivers = useMemo(
    () => employees.filter(e => e.role === 'driver').sort((a, b) => a.name.localeCompare(b.name)),
    [employees],
  );

  const setActive = async (pin: CrewPin, is_active: boolean) => {
    try {
      await axiosClient.patch(`/crew-pins/${pin.id}`, { is_active });
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not update the crew pin.'));
    }
  };

  const removeTruckPin = async (pin: TruckPin) => {
    try {
      await axiosClient.delete(`/truck-pins/${pin.id}`);
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not delete the truck pin.'));
    }
  };

  const remove = async (pin: CrewPin) => {
    try {
      await axiosClient.delete(`/crew-pins/${pin.id}`);
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not delete the crew pin.'));
    }
  };

  return (
    <div className="space-y-6">
      {/* ErrorBanner scrolls itself into view (ADR-339) — no per-page ref needed. */}
      <ErrorBanner message={error} />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Pin className="w-5 h-5" /> Crew Pins
          </h2>
          <p className="text-sm text-muted-foreground max-w-2xl mt-1">
            A pinned crew rides together every day the driver is dispatched. Unlike a
            favourite, which only makes a truck more likely, a pin is applied before
            assignment — the members are placed on the driver's truck directly.
          </p>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90"
        >
          <Plus className="w-4 h-4" /> New crew
        </button>
      </div>

      {creating && (
        <CrewPinForm
          drivers={drivers}
          employees={employees}
          onCancel={() => setCreating(false)}
          onSaved={async () => { setCreating(false); await load(); }}
          onError={setError}
        />
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : pins.length === 0 ? (
        <div className="border border-border rounded-xl p-8 text-center">
          <Pin className="w-8 h-8 mx-auto text-muted-foreground/40" />
          <p className="mt-3 text-sm text-muted-foreground">
            No crew pins yet. Pin a crew that works well together and they will be
            assigned to the same truck automatically.
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {pins.map(pin => (
            <PinCard
              key={pin.id}
              pin={pin}
              onToggle={setActive}
              onDelete={remove}
            />
          ))}
        </div>
      )}

      {/* Both pin axes live on one surface deliberately. They are two halves of
          one idea, and the rule that a person can hold only one of them is far
          easier to understand when both are visible than when the second is a
          409 from a screen you cannot see. */}
      <TruckPinSection
        truckPins={truckPins}
        trucks={trucks}
        employees={employees}
        crewPinnedIds={crewPinnedIds}
        onDelete={removeTruckPin}
        onSaved={load}
        onError={setError}
      />
    </div>
  );
}

function PinCard({
  pin, onToggle, onDelete,
}: {
  pin: CrewPin;
  onToggle: (p: CrewPin, active: boolean) => void;
  onDelete: (p: CrewPin) => void;
}) {
  return (
    <div className={`border rounded-xl p-4 ${pin.is_active ? 'border-border' : 'border-border/50 bg-muted/30'}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold">{pin.name}</h3>
            {!pin.is_active && (
              <span className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground border border-border rounded px-1.5 py-0.5">
                Inactive
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            Anchored to <span className="font-medium text-foreground">{pin.driver_name ?? 'a driver'}</span>
            {' '}— the crew follows whichever truck they are assigned.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onToggle(pin, !pin.is_active)}
            className="inline-flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg border border-border hover:bg-accent"
          >
            {pin.is_active ? <><X className="w-3.5 h-3.5" /> Deactivate</> : <><RotateCcw className="w-3.5 h-3.5" /> Reactivate</>}
          </button>
          <button
            onClick={() => onDelete(pin)}
            aria-label={`Delete ${pin.name}`}
            className="p-1.5 rounded-lg border border-border text-danger hover:bg-danger/10"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* The reason matters more than the state. A pin that silently stopped
          applying is the failure this screen exists to prevent. */}
      {!pin.is_active && pin.inactive_reason && (
        <div className="mt-3 flex items-start gap-2 text-sm rounded-lg border border-warning/40 bg-warning/10 p-2.5">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-warning" />
          <span>{pin.inactive_reason}</span>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-1.5">
        {pin.members.length === 0 ? (
          <span className="text-sm text-muted-foreground">No members yet.</span>
        ) : (
          pin.members.map(m => (
            <span key={m.employee_id} className="text-xs bg-accent rounded-lg px-2 py-1">
              {m.name ?? 'Unknown'}
              {m.role && <span className="text-muted-foreground uppercase ml-1.5 text-[10px]">{m.role}</span>}
            </span>
          ))
        )}
      </div>
    </div>
  );
}

function CrewPinForm({
  drivers, employees, onCancel, onSaved, onError,
}: {
  drivers: Employee[];
  employees: Employee[];
  onCancel: () => void;
  onSaved: () => void;
  onError: (m: string) => void;
}) {
  const [name, setName] = useState('');
  const [driverId, setDriverId] = useState('');
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // The anchor cannot also be a member — the server strips it, but offering it
  // invites the question "did that work?".
  const candidates = useMemo(
    () => employees
      .filter(e => e.id !== driverId && e.role !== 'driver')
      .sort((a, b) => a.role.localeCompare(b.role) || a.name.localeCompare(b.name)),
    [employees, driverId],
  );

  const submit = async () => {
    setSaving(true);
    try {
      await axiosClient.post('/crew-pins', {
        name: name.trim(),
        driver_id: driverId,
        member_ids: memberIds,
      });
      onSaved();
    } catch (err: unknown) {
      onError(errorText(err, 'Could not create the crew pin.'));
    } finally {
      setSaving(false);
    }
  };

  const toggle = (id: string) =>
    setMemberIds(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]));

  return (
    <div className="border border-border rounded-xl p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="block mb-1 font-medium">Crew name</span>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            maxLength={80}
            placeholder="A Team"
            className="w-full rounded-lg border border-border bg-background px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="block mb-1 font-medium">Driver (anchor)</span>
          <select
            value={driverId}
            onChange={e => setDriverId(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2"
          >
            <option value="">Select a driver…</option>
            {drivers.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
      </div>

      <div>
        <p className="text-sm font-medium mb-1.5">Crew members</p>
        <div className="flex flex-wrap gap-1.5 max-h-56 overflow-y-auto">
          {candidates.map(e => {
            const on = memberIds.includes(e.id);
            return (
              <button
                key={e.id}
                type="button"
                onClick={() => toggle(e.id)}
                aria-pressed={on}
                className={`text-xs rounded-lg px-2 py-1 border transition-colors ${
                  on ? 'bg-primary text-primary-foreground border-primary' : 'border-border hover:bg-accent'
                }`}
              >
                {e.name}
                <span className={`uppercase ml-1.5 text-[10px] ${on ? 'opacity-80' : 'text-muted-foreground'}`}>
                  {e.role}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={submit}
          disabled={saving || !name.trim() || !driverId}
          className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Create crew pin'}
        </button>
        <button onClick={onCancel} className="px-3 py-2 rounded-lg border border-border text-sm">
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Truck pins (ADR-358) ─────────────────────────────────────────────────────

const WEEKDAYS: Weekday[] = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
];

function TruckPinSection({
  truckPins, trucks, employees, crewPinnedIds, onDelete, onSaved, onError,
}: {
  truckPins: TruckPin[];
  trucks: Truck[];
  employees: Employee[];
  crewPinnedIds: Set<string>;
  onDelete: (p: TruckPin) => void;
  onSaved: () => Promise<void> | void;
  onError: (m: string) => void;
}) {
  const [adding, setAdding] = useState(false);

  /* One row per person per day, so a person with a Tuesday and a Thursday pin is
     two rows. Grouped for display because "Marcus: Truck 4 on Tue, Thu" is the
     fact a dispatcher holds in their head — the rows are storage, not meaning. */
  const grouped = useMemo(() => {
    const by = new Map<string, { pins: TruckPin[]; name: string; role: string; truck: string }>();
    for (const p of truckPins) {
      const key = `${p.employee_id}|${p.truck_id}`;
      const hit = by.get(key);
      if (hit) hit.pins.push(p);
      else by.set(key, {
        pins: [p],
        name: p.employee_name ?? 'Unknown',
        role: p.employee_role ?? '',
        truck: p.truck_name ?? 'Unknown truck',
      });
    }
    return [...by.values()];
  }, [truckPins]);

  return (
    <section className="space-y-4 pt-2">
      <div className="flex items-start justify-between gap-4 flex-wrap border-t border-border pt-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <TruckIcon className="w-5 h-5" /> Truck Pins
          </h2>
          <p className="text-sm text-muted-foreground max-w-2xl mt-1">
            For crew who work a specific truck on specific days. A crew pin follows
            a driver; a truck pin holds someone to the truck itself. A person can
            have one or the other, not both.
          </p>
        </div>
        <button
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90"
        >
          <Plus className="w-4 h-4" /> Pin to truck
        </button>
      </div>

      {adding && (
        <TruckPinForm
          trucks={trucks}
          employees={employees}
          crewPinnedIds={crewPinnedIds}
          onCancel={() => setAdding(false)}
          onSaved={async () => { setAdding(false); await onSaved(); }}
          onError={onError}
        />
      )}

      {grouped.length === 0 ? (
        <div className="border border-border rounded-xl p-8 text-center">
          <CalendarDays className="w-8 h-8 mx-auto text-muted-foreground/40" />
          <p className="mt-3 text-sm text-muted-foreground">
            No truck pins yet.
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {grouped.map(g => (
            <div key={`${g.name}-${g.truck}`} className="border border-border rounded-xl p-4">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h3 className="font-semibold">
                    {g.name}
                    {g.role && <span className="text-muted-foreground uppercase ml-2 text-[10px]">{g.role}</span>}
                  </h3>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    Held to <span className="font-medium text-foreground">{g.truck}</span>
                  </p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {g.pins
                  .slice()
                  .sort((a, b) => WEEKDAYS.indexOf(a.day_of_week) - WEEKDAYS.indexOf(b.day_of_week))
                  .map(p => (
                    <span key={p.id} className="inline-flex items-center gap-1.5 text-xs bg-accent rounded-lg px-2 py-1">
                      {p.day_of_week}
                      <button
                        onClick={() => onDelete(p)}
                        aria-label={`Remove ${g.name} from ${g.truck} on ${p.day_of_week}`}
                        className="text-muted-foreground hover:text-danger"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function TruckPinForm({
  trucks, employees, crewPinnedIds, onCancel, onSaved, onError,
}: {
  trucks: Truck[];
  employees: Employee[];
  crewPinnedIds: Set<string>;
  onCancel: () => void;
  onSaved: () => void;
  onError: (m: string) => void;
}) {
  const [employeeId, setEmployeeId] = useState('');
  const [truckId, setTruckId] = useState('');
  const [days, setDays] = useState<Weekday[]>([]);
  const [saving, setSaving] = useState(false);

  const sorted = useMemo(
    () => employees.slice().sort((a, b) => a.role.localeCompare(b.role) || a.name.localeCompare(b.name)),
    [employees],
  );

  const submit = async () => {
    setSaving(true);
    try {
      await axiosClient.post('/truck-pins', {
        employee_id: employeeId,
        truck_id: truckId,
        days,
      });
      onSaved();
    } catch (err: unknown) {
      onError(errorText(err, 'Could not create the truck pin.'));
    } finally {
      setSaving(false);
    }
  };

  const toggleDay = (d: Weekday) =>
    setDays(prev => (prev.includes(d) ? prev.filter(x => x !== d) : [...prev, d]));

  return (
    <div className="border border-border rounded-xl p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="block mb-1 font-medium">Employee</span>
          <select
            value={employeeId}
            onChange={e => setEmployeeId(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2"
          >
            <option value="">Select someone…</option>
            {sorted.map(e => (
              // Disabled rather than hidden: the server returns 409 for these
              // (ADR-358 D2), and a missing name reads as a bug while a disabled
              // one with a reason reads as a rule.
              <option key={e.id} value={e.id} disabled={crewPinnedIds.has(e.id)}>
                {e.name} ({e.role}){crewPinnedIds.has(e.id) ? ' — in a crew pin' : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block mb-1 font-medium">Truck</span>
          <select
            value={truckId}
            onChange={e => setTruckId(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2"
          >
            <option value="">Select a truck…</option>
            {trucks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
      </div>

      <div>
        <p className="text-sm font-medium mb-1.5">Days</p>
        <div className="flex flex-wrap gap-1.5">
          {WEEKDAYS.map(d => {
            const on = days.includes(d);
            return (
              <button
                key={d}
                type="button"
                onClick={() => toggleDay(d)}
                aria-pressed={on}
                className={`text-xs rounded-lg px-2.5 py-1.5 border transition-colors ${
                  on ? 'bg-primary text-primary-foreground border-primary' : 'border-border hover:bg-accent'
                }`}
              >
                {d.slice(0, 3)}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={submit}
          disabled={saving || !employeeId || !truckId || days.length === 0}
          className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Pin to truck'}
        </button>
        <button onClick={onCancel} className="px-3 py-2 rounded-lg border border-border text-sm">
          Cancel
        </button>
      </div>
    </div>
  );
}
