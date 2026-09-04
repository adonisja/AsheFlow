import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Pin, Plus, Trash2, X, AlertTriangle, RotateCcw, Truck as TruckIcon, CalendarDays, Warehouse, HelpCircle, UserMinus, Pencil, ArrowRightLeft } from 'lucide-react';

import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import ErrorBanner from '../components/ui/ErrorBanner';
import SelectMenu, { type SelectOption } from '../components/ui/SelectMenu';
import SettingsHelpDrawer from '../components/ui/SettingsHelpDrawer';
import type { CrewPin, CrewPinUpdatePayload, Employee, Separation, Truck, TruckPin,
  TruckPinRetruckPayload, Weekday } from '../api/types';

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
/* Roles that can actually be on a truck — the same six AssignmentMember.role
   accepts. dispatch, management, admin and field_supervisor are excluded
   because they cannot hold a crew slot at all, so offering them is offering a
   choice the assignment model will never honour.
   Ordered by how a dispatcher reads a crew, not alphabetically. */
/* Trainees are excluded from BOTH pin axes. A trainee rides with the trainer
   they are paired to (ADR-210 moves them together), so pinning one independently
   fights the pairing rather than expressing a preference. */
const CREW_ROLE_ORDER = ['captain', 'trainer', 'walker'] as const;
const CREW_ROLES = new Set<string>(CREW_ROLE_ORDER);

/** Field crew only, grouped and ordered by role. */
function crewCandidates(employees: Employee[], exclude?: (e: Employee) => boolean) {
  return employees
    .filter(e => CREW_ROLES.has(e.role) && !(exclude?.(e) ?? false))
    .sort((a, b) =>
      CREW_ROLE_ORDER.indexOf(a.role as typeof CREW_ROLE_ORDER[number]) -
      CREW_ROLE_ORDER.indexOf(b.role as typeof CREW_ROLE_ORDER[number]) ||
      a.name.localeCompare(b.name));
}

const SELECT_CLASS =
  'w-full border border-input rounded-xl px-3 py-2 text-sm bg-background ' +
  'focus:ring-1 focus:ring-primary focus:border-primary outline-none';

/* Shared surface treatment. The app's visual language is restrained —
   shadow-sm, no gradients — so this stays inside it: the modernisation is
   hierarchy and rhythm, not decoration borrowed from a different aesthetic. */
const CARD =
  'rounded-xl border border-border bg-card p-4 shadow-sm transition-colors hover:border-border/80';

/** A person chip. Role is a separate muted span so the eye can scan names. */
function PersonChip({ name, role, tone = 'default' }: {
  name: string; role?: string | null; tone?: 'default' | 'lead';
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs rounded-lg pl-2 pr-2 py-1 border ${
        tone === 'lead'
          ? 'border-primary/30 bg-primary/10'
          : 'border-border bg-accent/40'
      }`}
    >
      <span className="font-medium">{name}</span>
      {role && (
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {role.replace('_', ' ')}
        </span>
      )}
    </span>
  );
}

/** Section heading, one level below the page and above the cards.
 *
 *  The explanation lives behind the help pin rather than in a paragraph under
 *  the title. Three lines of prose above every section pushes the actual content
 *  down the page and is read once, on the first visit. The drawer holds more
 *  detail than a blurb can and is there when someone needs it. */
function SectionHeader({ icon, title, helpKey, onHelp, action }: {
  icon: ReactNode;
  title: string;
  helpKey: string;
  onHelp: (k: string) => void;
  action: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 flex-wrap">
      <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
        <span className="grid place-items-center w-7 h-7 rounded-lg bg-accent text-muted-foreground">
          {icon}
        </span>
        {title}
        <button
          type="button"
          onClick={() => onHelp(helpKey)}
          aria-label={`What are ${title.toLowerCase()}?`}
          className="text-muted-foreground/60 hover:text-primary transition-colors"
        >
          <HelpCircle className="w-4 h-4" />
        </button>
      </h2>
      {action}
    </div>
  );
}

/** Empty state — dashed, so it reads as a slot rather than a broken card. */
function EmptyState({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-accent/20 p-8 text-center">
      <div className="grid place-items-center w-10 h-10 rounded-xl bg-card mx-auto text-muted-foreground/60">
        {icon}
      </div>
      <p className="mt-3 text-sm text-muted-foreground max-w-sm mx-auto">{children}</p>
    </div>
  );
}

export default function CrewPins() {
  const [pins, setPins] = useState<CrewPin[]>([]);
  const [truckPins, setTruckPins] = useState<TruckPin[]>([]);
  const [separations, setSeparations] = useState<Separation[]>([]);
  const [trucks, setTrucks] = useState<Truck[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [helpKey, setHelpKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pinRes, truckPinRes, sepRes, empRes, truckRes] = await Promise.all([
        axiosClient.get<CrewPin[]>('/crew-pins'),
        axiosClient.get<TruckPin[]>('/truck-pins'),
        axiosClient.get<Separation[]>('/separations/'),
        axiosClient.get<Employee[]>('/employees/'),
        axiosClient.get<Truck[]>('/trucks/'),
      ]);
      setPins(pinRes.data);
      setTruckPins(truckPinRes.data);
      setSeparations(sepRes.data);
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

  /* Edit, not delete-and-recreate (ADR-373 D1). Recreating a pin to rename it
     loses its id, and the id is what the audit trail and every "since when"
     question hangs off. PATCH keeps the pin the same pin. */
  const editPin = async (pin: CrewPin, patch: CrewPinUpdatePayload) => {
    try {
      await axiosClient.patch(`/crew-pins/${pin.id}`, patch);
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not save the crew pin.'));
      throw err;   // the card stays in edit mode so the typing is not lost
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

  /* Keyed by employee, not by pin (ADR-373 D3). "Move Jerome to Truck 4" means
     every day he is pinned; doing it row by row can half-succeed and leave him
     pinned to two trucks on different days. */
  const retruck = async (employeeId: string, truckId: string) => {
    try {
      const body: TruckPinRetruckPayload = { truck_id: truckId };
      await axiosClient.patch(`/truck-pins/employee/${employeeId}`, body);
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not move the truck pin.'));
      throw err;
    }
  };

  /* Adding a day needs no new endpoint (ADR-373 D2): POST already creates one
     row per day and already 409s on a day the person holds. */
  const addTruckPinDays = async (employeeId: string, truckId: string, days: Weekday[]) => {
    try {
      await axiosClient.post('/truck-pins', {
        employee_id: employeeId, truck_id: truckId, days,
      });
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not add the day.'));
      throw err;
    }
  };

  const removeSeparation = async (sep: Separation) => {
    try {
      await axiosClient.delete(`/separations/${sep.id}`);
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Could not lift the separation.'));
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

      <SectionHeader
        icon={<Pin className="w-4 h-4" />}
        title="Crew Pins"
        helpKey="crew_pin"
        onHelp={setHelpKey}
        action={
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium shadow-sm hover:opacity-90 transition-opacity"
          >
            <Plus className="w-4 h-4" /> New crew
          </button>
        }
      />

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
        <EmptyState icon={<Pin className="w-5 h-5" />}>
          No crew pins yet. Pin a crew that works well together and they will be
          assigned to the same truck automatically.
        </EmptyState>
      ) : (
        <div className="grid gap-3">
          {pins.map(pin => (
            <PinCard
              key={pin.id}
              pin={pin}
              employees={employees}
              crewPinnedIds={crewPinnedIds}
              onToggle={setActive}
              onDelete={remove}
              onEdit={editPin}
            />
          ))}
        </div>
      )}

      {/* Both pin axes live on one surface deliberately. They are two halves of
          one idea, and the rule that a person can hold only one of them is far
          easier to understand when both are visible than when the second is a
          409 from a screen you cannot see. */}
      <TruckPinSection
        onHelp={setHelpKey}
        truckPins={truckPins}
        trucks={trucks}
        employees={employees}
        crewPinnedIds={crewPinnedIds}
        onDelete={removeTruckPin}
        onRetruck={retruck}
        onAddDays={addTruckPinDays}
        onSaved={load}
        onError={setError}
      />

      {/* Last of the three, and deliberately so: the two pin axes are what a
          dispatcher comes to this page to do, and a separation is the rarer,
          heavier action. Reading order matches frequency of use. */}
      <SeparationSection
        onHelp={setHelpKey}
        separations={separations}
        employees={employees}
        onDelete={removeSeparation}
        onSaved={load}
        onError={setError}
      />

      <SettingsHelpDrawer fieldKey={helpKey} onClose={() => setHelpKey(null)} />
    </div>
  );
}

function PinCard({
  pin, employees, crewPinnedIds, onToggle, onDelete, onEdit,
}: {
  pin: CrewPin;
  employees: Employee[];
  crewPinnedIds: Set<string>;
  onToggle: (p: CrewPin, active: boolean) => void;
  onDelete: (p: CrewPin) => void;
  onEdit: (p: CrewPin, patch: CrewPinUpdatePayload) => Promise<void>;
}) {
  /* Edit state is local to the card, so opening one editor does not disturb the
     others and cancelling restores the server's values rather than a shared
     draft. */
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(pin.name);
  const [draftMembers, setDraftMembers] = useState<string[]>(
    () => pin.members.map(m => m.employee_id),
  );
  const [saving, setSaving] = useState(false);

  const open = () => {
    setDraftName(pin.name);
    setDraftMembers(pin.members.map(m => m.employee_id));
    setEditing(true);
  };

  /* The anchor is not a member and cannot become one; everyone pinned to
     ANOTHER crew is unavailable, but this crew's own members must stay
     selectable or editing would empty the list it is meant to edit. */
  const mine = useMemo(() => new Set(pin.members.map(m => m.employee_id)), [pin.members]);
  const candidates = useMemo(
    () => crewCandidates(employees, e =>
      e.id === pin.driver_id ||
      e.role === 'driver' ||
      (crewPinnedIds.has(e.id) && !mine.has(e.id))),
    [employees, pin.driver_id, crewPinnedIds, mine],
  );

  const trimmed = draftName.trim();
  const membersChanged =
    draftMembers.length !== mine.size || draftMembers.some(id => !mine.has(id));
  const dirty = (trimmed !== pin.name && trimmed.length > 0) || membersChanged;

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      // Send only what changed. A no-op field still rewrites rows server-side.
      const patch: CrewPinUpdatePayload = {};
      if (trimmed !== pin.name && trimmed.length > 0) patch.name = trimmed;
      if (membersChanged) patch.member_ids = draftMembers;
      await onEdit(pin, patch);
      setEditing(false);
    } catch {
      // handler surfaced it; stay open so the edit is not lost
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`${CARD} ${pin.is_active ? '' : 'opacity-70 bg-accent/20'}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {editing ? (
              <input
                value={draftName}
                onChange={e => setDraftName(e.target.value)}
                maxLength={80}
                aria-label="Crew name"
                autoFocus
                className="border border-input rounded-lg px-2 py-1 text-sm font-semibold bg-background focus:ring-1 focus:ring-primary focus:border-primary outline-none"
              />
            ) : (
              <h3 className="font-semibold tracking-tight">{pin.name}</h3>
            )}
            {!pin.is_active && (
              <span className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground bg-accent rounded-md px-1.5 py-0.5">
                Inactive
              </span>
            )}
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {pin.members.length} member{pin.members.length === 1 ? '' : 's'}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Anchored to <span className="font-medium text-foreground">{pin.driver_name ?? 'a driver'}</span>
            . The crew follows whichever truck they are assigned.
          </p>
        </div>

        {/* Delete is separated by a divider rather than sitting flush beside
            Deactivate. They read as equal-weight controls otherwise, and only
            one of them is destructive. */}
        <div className="flex items-center gap-1">
          {!editing && (
            <button
              onClick={open}
              className="inline-flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            >
              <Pencil className="w-3.5 h-3.5" /> Edit
            </button>
          )}
          <button
            onClick={() => onToggle(pin, !pin.is_active)}
            className="inline-flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            {pin.is_active ? <><X className="w-3.5 h-3.5" /> Deactivate</> : <><RotateCcw className="w-3.5 h-3.5" /> Reactivate</>}
          </button>
          <span className="w-px h-5 bg-border mx-1" aria-hidden />
          <button
            onClick={() => onDelete(pin)}
            aria-label={`Delete ${pin.name}`}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-danger hover:bg-danger/10 transition-colors"
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

      {/* Sorted by role, not by insertion. The screenshot showed
          trainer/walker/walker/captain/walker — the captain is the route lead
          and was buried in the middle of the list. */}
      {editing ? (
        /* Checkboxes, not a multi-select: a dispatcher editing a crew is
           looking for one name in a short list, and a native multi-select
           hides the current selection behind a scroll and loses it on a
           stray click. */
        <div className="mt-3 space-y-3">
          <div className="rounded-lg border border-border bg-accent/20 p-2 max-h-56 overflow-y-auto">
            {candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground p-1">
                No one else is available. Everyone is on another crew pin.
              </p>
            ) : (
              <div className="grid sm:grid-cols-2 gap-1">
                {candidates.map(e => {
                  const on = draftMembers.includes(e.id);
                  return (
                    <label
                      key={e.id}
                      className="flex items-center gap-2 text-sm rounded-md px-2 py-1.5 hover:bg-accent cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => setDraftMembers(prev =>
                          on ? prev.filter(id => id !== e.id) : [...prev, e.id])}
                        className="accent-primary"
                      />
                      <span className="font-medium truncate">{e.name}</span>
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground ml-auto shrink-0">
                        {e.role.replace('_', ' ')}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void save()}
              disabled={!dirty || saving || trimmed.length === 0}
              className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-accent transition-colors"
            >
              Cancel
            </button>
            {trimmed.length === 0 && (
              <span className="text-xs text-danger">A crew needs a name.</span>
            )}
          </div>
        </div>
      ) : (
      <div className="mt-3 flex flex-wrap gap-1.5">
        {pin.members.length === 0 ? (
          <span className="text-sm text-muted-foreground">No members yet.</span>
        ) : (
          pin.members
            .slice()
            .sort((a, b) =>
              CREW_ROLE_ORDER.indexOf(a.role as typeof CREW_ROLE_ORDER[number]) -
              CREW_ROLE_ORDER.indexOf(b.role as typeof CREW_ROLE_ORDER[number]) ||
              (a.name ?? '').localeCompare(b.name ?? ''))
            .map(m => (
              <PersonChip
                key={m.employee_id}
                name={m.name ?? 'Unknown'}
                role={m.role}
                tone={m.role === 'captain' ? 'lead' : 'default'}
              />
            ))
        )}
      </div>
      )}
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
    () => crewCandidates(employees, e => e.id === driverId || e.role === 'driver'),
    [employees, driverId],
  );

  const byRole = useMemo(() => {
    const groups = new Map<string, Employee[]>();
    for (const e of candidates) {
      const g = groups.get(e.role);
      if (g) g.push(e); else groups.set(e.role, [e]);
    }
    return groups;
  }, [candidates]);

  const chosen = (role: string) =>
    memberIds.filter(id => employees.find(e => e.id === id)?.role === role).length;

  /* Composition rules, stated where the choice is made rather than enforced
     silently: exactly one captain leads the truck, walkers do the route, and
     trainers are optional because a crew without a trainee needs none. */
  const RULES: Record<string, string> = {
    captain: 'choose 1',
    trainer: 'optional',
    walker: 'choose 1 or more',
  };

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
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">
            Crew name
          </label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            maxLength={80}
            placeholder="A Team"
            className={SELECT_CLASS}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">
            Driver (anchor)
          </label>
          <SelectMenu
            value={driverId}
            onChange={setDriverId}
            placeholder="Select a driver…"
            ariaLabel="Driver (anchor)"
            options={drivers.map(d => ({ value: d.id, label: d.name }))}
          />
        </div>
      </div>

      {/* Grouped by role rather than one flat list. A crew is built role by role
          — one captain, then walkers — and a single alphabetical list of 80
          names makes that impossible to see. The role tag on each chip becomes
          redundant once they are grouped, so it is dropped. */}
      <div className="space-y-3">
        <p className="text-sm font-medium">Crew members</p>
        {CREW_ROLE_ORDER.filter(r => (byRole.get(r) ?? []).length > 0).map(role => {
          const people = byRole.get(role) ?? [];
          const n = chosen(role);
          return (
            <div key={role}>
              <div className="flex items-baseline gap-2 mb-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide">
                  {role.replace('_', ' ')}s
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {RULES[role] ?? 'optional'}
                  {n > 0 && `, ${n} selected`}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                {people.map(e => {
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
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={submit}
          disabled={saving || !name.trim() || !driverId || chosen('captain') > 1}
          title={chosen('captain') > 1 ? 'A truck has one captain' : undefined}
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
  truckPins, trucks, employees, crewPinnedIds, onDelete, onRetruck, onAddDays,
  onSaved, onError, onHelp,
}: {
  onHelp: (k: string) => void;
  truckPins: TruckPin[];
  trucks: Truck[];
  employees: Employee[];
  crewPinnedIds: Set<string>;
  onDelete: (p: TruckPin) => void;
  onRetruck: (employeeId: string, truckId: string) => Promise<void>;
  onAddDays: (employeeId: string, truckId: string, days: Weekday[]) => Promise<void>;
  onSaved: () => Promise<void> | void;
  onError: (m: string) => void;
}) {
  const [adding, setAdding] = useState(false);

  /* One row per person per day, so a person with a Tuesday and a Thursday pin is
     two rows. Grouped for display because "Marcus: Truck 4 on Tue, Thu" is the
     fact a dispatcher holds in their head — the rows are storage, not meaning. */
  const grouped = useMemo(() => {
    const hubIds = new Set(trucks.filter(t => t.is_hub).map(t => t.id));
    const by = new Map<string, {
      pins: TruckPin[]; name: string; role: string; truck: string; isHub: boolean;
    }>();
    for (const p of truckPins) {
      const key = `${p.employee_id}|${p.truck_id}`;
      const hit = by.get(key);
      if (hit) hit.pins.push(p);
      else by.set(key, {
        pins: [p],
        name: p.employee_name ?? 'Unknown',
        role: p.employee_role ?? '',
        truck: p.truck_name ?? 'Unknown truck',
        isHub: hubIds.has(p.truck_id),
      });
    }
    return [...by.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [truckPins, trucks]);

  return (
    <section className="space-y-4 pt-2">
      <div className="border-t border-border pt-6">
        <SectionHeader
          icon={<TruckIcon className="w-4 h-4" />}
          title="Truck Pins"
          helpKey="truck_pin"
          onHelp={onHelp}
          action={
            <button
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium shadow-sm hover:opacity-90 transition-opacity"
            >
              <Plus className="w-4 h-4" /> Pin to truck
            </button>
          }
        />
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
        <EmptyState icon={<CalendarDays className="w-5 h-5" />}>
          No truck pins yet. Pin someone to a truck on the days they work it.
        </EmptyState>
      ) : (
        <div className="grid gap-3">
          {grouped.map(g => (
            <TruckPinCard
              key={`${g.name}-${g.truck}`}
              group={g}
              trucks={trucks}
              onDelete={onDelete}
              onRetruck={onRetruck}
              onAddDays={onAddDays}
            />
          ))}
        </div>
      )}
    </section>
  );
}

/** One person on one truck, with the days they hold it.
 *
 *  Both edits live here rather than in a modal (ADR-373 D4): the thing being
 *  edited is three chips and a truck name, and a dialog to change one of them
 *  costs more attention than the edit does. */
function TruckPinCard({
  group: g, trucks, onDelete, onRetruck, onAddDays,
}: {
  group: { pins: TruckPin[]; name: string; role: string; truck: string; isHub: boolean };
  trucks: Truck[];
  onDelete: (p: TruckPin) => void;
  onRetruck: (employeeId: string, truckId: string) => Promise<void>;
  onAddDays: (employeeId: string, truckId: string, days: Weekday[]) => Promise<void>;
}) {
  const [moving, setMoving] = useState(false);
  const [busy, setBusy] = useState(false);

  const employeeId = g.pins[0].employee_id;
  const truckId = g.pins[0].truck_id;
  const held = useMemo(() => new Set(g.pins.map(p => p.day_of_week)), [g.pins]);

  /* A day the person already holds on ANOTHER truck would 409 on POST. The
     server is still the authority; this only avoids offering a click that is
     guaranteed to fail. */
  const free = WEEKDAYS.filter(d => !held.has(d));

  const addDay = async (day: Weekday) => {
    if (busy) return;
    setBusy(true);
    try { await onAddDays(employeeId, truckId, [day]); }
    catch { /* surfaced by the handler */ }
    finally { setBusy(false); }
  };

  const move = async (id: string) => {
    if (busy || id === truckId) { setMoving(false); return; }
    setBusy(true);
    try { await onRetruck(employeeId, id); setMoving(false); }
    catch { /* surfaced by the handler */ }
    finally { setBusy(false); }
  };

  return (
            <div className={CARD}>
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h3 className="font-semibold tracking-tight">
                    {g.name}
                    {g.role && (
                      <span className="text-muted-foreground uppercase ml-2 text-[10px] tracking-wide">
                        {g.role.replace('_', ' ')}
                      </span>
                    )}
                  </h3>
                  {/* The hub marker belongs HERE too, not only in the picker.
                      "Held to Hub" reads as an ordinary truck otherwise, and a
                      hub is never auto-dispatched (ADR-274). */}
                  <p className="text-sm text-muted-foreground mt-1 flex items-center gap-1.5">
                    Held to
                    {g.isHub && <Warehouse className="w-3.5 h-3.5" />}
                    <span className="font-medium text-foreground">{g.truck}</span>
                    {g.isHub && (
                      <span className="text-[10px] uppercase tracking-wide bg-accent rounded-md px-1.5 py-0.5">
                        hub
                      </span>
                    )}
                  </p>
                </div>

                {/* Changing the truck is one action for the whole person, not
                    per day (ADR-373 D3) — a per-row truck picker invites
                    leaving someone on two trucks in one week. */}
                {moving ? (
                  <div className="flex items-center gap-2">
                    <select
                      autoFocus
                      defaultValue={truckId}
                      disabled={busy}
                      aria-label={`Move ${g.name} to another truck`}
                      onChange={e => void move(e.target.value)}
                      className="border border-input rounded-lg px-2 py-1.5 text-sm bg-background focus:ring-1 focus:ring-primary focus:border-primary outline-none"
                    >
                      {trucks.map(t => (
                        <option key={t.id} value={t.id}>
                          {t.name}{t.is_hub ? ' (hub)' : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => setMoving(false)}
                      className="text-sm text-muted-foreground hover:text-foreground px-2 py-1.5 rounded-lg hover:bg-accent transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setMoving(true)}
                    className="inline-flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                  >
                    <ArrowRightLeft className="w-3.5 h-3.5" /> Move
                  </button>
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {g.pins
                  .slice()
                  .sort((a, b) => WEEKDAYS.indexOf(a.day_of_week) - WEEKDAYS.indexOf(b.day_of_week))
                  .map(p => (
                    /* Day chips are REMOVABLE and member chips are not, so they
                       must not look identical — the × gets a hover affordance of
                       its own rather than being a glyph inside a flat tag. */
                    <span
                      key={p.id}
                      className="group inline-flex items-center gap-1 text-xs rounded-lg border border-border bg-accent/40 pl-2 pr-1 py-1"
                    >
                      <span className="font-medium">{p.day_of_week}</span>
                      <button
                        onClick={() => onDelete(p)}
                        aria-label={`Remove ${g.name} from ${g.truck} on ${p.day_of_week}`}
                        className="grid place-items-center w-4 h-4 rounded text-muted-foreground hover:bg-danger/15 hover:text-danger transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}

                {/* Adding a day is the same shape as removing one — a chip, in
                    the same row (ADR-373 D2). The dashed border says "not held
                    yet" without needing a label to explain it. */}
                {free.map(d => (
                  <button
                    key={d}
                    onClick={() => void addDay(d)}
                    disabled={busy}
                    aria-label={`Also pin ${g.name} to ${g.truck} on ${d}`}
                    title={`Also pin ${g.name} to ${g.truck} on ${d}`}
                    className="inline-flex items-center gap-1 text-xs rounded-lg border border-dashed border-border text-muted-foreground px-2 py-1 hover:border-primary hover:text-primary hover:bg-primary/5 disabled:opacity-50 transition-colors"
                  >
                    <Plus className="w-3 h-3" />
                    <span>{d.slice(0, 3)}</span>
                  </button>
                ))}
              </div>
            </div>
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

  /* Field crew only, grouped by role, drivers first.
     Drivers ARE included here: unlike a crew pin (where the driver is the anchor
     and cannot also be a member), a truck pin can hold a driver to their truck —
     the case that forced seating before assign_drivers (ADR-358 D3). */
  const employeeOptions = useMemo<SelectOption[]>(() => {
    const groups: [string, Employee[]][] = [
      ['Drivers', employees.filter(e => e.role === 'driver')],
      ...CREW_ROLE_ORDER.map(r => [
        `${r.charAt(0).toUpperCase()}${r.slice(1)}s`,
        employees.filter(e => e.role === r),
      ] as [string, Employee[]]),
    ];
    const out: SelectOption[] = [];
    for (const [label, people] of groups) {
      if (people.length === 0) continue;
      out.push({ value: `header-${label}`, label, header: true });
      for (const e of people.slice().sort((a, b) => a.name.localeCompare(b.name))) {
        out.push({
          value: e.id,
          label: e.name,
          // Disabled rather than hidden: the server refuses these with a 409
          // (ADR-358 D2). A missing name reads as a bug; a disabled one with a
          // reason reads as a rule.
          disabled: crewPinnedIds.has(e.id),
          hint: crewPinnedIds.has(e.id) ? 'in a crew pin' : undefined,
        });
      }
    }
    return out;
  }, [employees, crewPinnedIds]);

  /* Hubs are marked, not hidden. A hub is never auto-dispatched (ADR-274) and is
     staffed by hand, so pinning someone to one is legitimate but unusual — the
     dispatcher should see which it is before choosing, not discover it later. */
  const truckOptions = useMemo<SelectOption[]>(
    () => trucks
      .filter(t => t.is_active !== false)
      .slice()
      .sort((a, b) => Number(a.is_hub ?? false) - Number(b.is_hub ?? false) || a.name.localeCompare(b.name))
      .map(t => ({
        value: t.id,
        label: t.name,
        icon: t.is_hub
          ? <Warehouse className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          : <TruckIcon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />,
        hint: t.is_hub ? 'hub' : undefined,
      })),
    [trucks],
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
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">
            Employee
          </label>
          <SelectMenu
            value={employeeId}
            onChange={setEmployeeId}
            placeholder="Select someone…"
            ariaLabel="Employee"
            options={employeeOptions}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">
            Truck
          </label>
          <SelectMenu
            value={truckId}
            onChange={setTruckId}
            placeholder="Select a truck…"
            ariaLabel="Truck"
            options={truckOptions}
          />
        </div>
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

/* ── Separations (ADR-361) ──────────────────────────────────────────────────
   The inverse of a pin, and deliberately the same visual language: a pin says
   "always together", a separation says "never together", and a dispatcher
   reading this page should see them as two settings of one dial rather than as
   unrelated features.

   One thing this section must carry that the pin sections do not: a separation
   is INVISIBLE to both people in it. That is the whole point of the feature and
   also its main hazard — a dispatcher who forgets it will read an odd roster as
   a bug. So the invisibility is stated on the section itself, not left to the
   help drawer, and the empty state says it too. */
function SeparationSection({
  separations, employees, onHelp, onSaved, onDelete, onError,
}: {
  separations: Separation[];
  employees: Employee[];
  onHelp: (k: string) => void;
  onSaved: () => Promise<void> | void;
  onDelete: (s: Separation) => void;
  onError: (m: string) => void;
}) {
  const [adding, setAdding] = useState(false);

  const rows = useMemo(
    () => separations
      .slice()
      .sort((a, b) =>
        (a.employee_name ?? '').localeCompare(b.employee_name ?? '') ||
        (a.target_employee_name ?? '').localeCompare(b.target_employee_name ?? '')),
    [separations],
  );

  const roleOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of employees) m.set(e.id, e.role);
    return m;
  }, [employees]);

  return (
    <section className="space-y-4 pt-2">
      <div className="border-t border-border pt-6">
        <SectionHeader
          icon={<UserMinus className="w-4 h-4" />}
          title="Separations"
          helpKey="separation"
          onHelp={onHelp}
          action={
            <button
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium shadow-sm hover:opacity-90 transition-opacity"
            >
              <Plus className="w-4 h-4" /> Separate two people
            </button>
          }
        />
      </div>

      {adding && (
        <SeparationForm
          employees={employees}
          separations={separations}
          onCancel={() => setAdding(false)}
          onSaved={async () => { setAdding(false); await onSaved(); }}
          onError={onError}
        />
      )}

      {rows.length === 0 ? (
        <EmptyState icon={<UserMinus className="w-5 h-5" />}>
          No separations. Dispatch will pair anyone whose own bans allow it.
        </EmptyState>
      ) : (
        <div className="grid gap-3">
          {rows.map(sep => (
            <div key={sep.id} className={CARD}>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                {/* Two chips either side of a "kept apart" marker. Reusing
                    PersonChip keeps a separated pair reading like a crew roster
                    with the relationship inverted, which is what it is. */}
                <div className="flex items-center gap-2 flex-wrap min-w-0">
                  <PersonChip
                    name={sep.employee_name ?? 'Unknown'}
                    role={roleOf.get(sep.employee_id)}
                  />
                  <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                    <UserMinus className="w-3.5 h-3.5" />
                    kept apart
                  </span>
                  <PersonChip
                    name={sep.target_employee_name ?? 'Unknown'}
                    role={roleOf.get(sep.target_employee_id)}
                  />
                </div>
                <button
                  onClick={() => onDelete(sep)}
                  aria-label={`Lift the separation between ${sep.employee_name ?? 'this employee'} and ${sep.target_employee_name ?? 'the other'}`}
                  className="grid place-items-center w-8 h-8 rounded-lg text-muted-foreground hover:bg-danger/15 hover:text-danger transition-colors shrink-0"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SeparationForm({
  employees, separations, onCancel, onSaved, onError,
}: {
  employees: Employee[];
  separations: Separation[];
  onCancel: () => void;
  onSaved: () => void;
  onError: (m: string) => void;
}) {
  const [employeeId, setEmployeeId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [saving, setSaving] = useState(false);

  /* Drivers included alongside the crew roles. A separation is about two people
     never sharing a truck, and a driver shares a truck with everyone on it —
     excluding them would leave out the pairing most worth preventing. */
  const optionsFor = useCallback((other: string): SelectOption[] => {
    const groups: [string, Employee[]][] = [
      ['Drivers', employees.filter(e => e.role === 'driver')],
      ...CREW_ROLE_ORDER.map(r => [
        `${r.charAt(0).toUpperCase()}${r.slice(1)}s`,
        employees.filter(e => e.role === r),
      ] as [string, Employee[]]),
    ];
    // Already-separated pairs are disabled with a reason rather than hidden,
    // matching the truck-pin picker: the server answers a duplicate with a 409,
    // and a name that silently vanishes reads as a bug.
    const paired = new Set<string>();
    if (other) {
      for (const s of separations) {
        if (s.employee_id === other) paired.add(s.target_employee_id);
        if (s.target_employee_id === other) paired.add(s.employee_id);
      }
    }
    const out: SelectOption[] = [];
    for (const [label, people] of groups) {
      const list = people.filter(e => e.id !== other);
      if (list.length === 0) continue;
      out.push({ value: `header-${label}`, label, header: true });
      for (const e of list.slice().sort((a, b) => a.name.localeCompare(b.name))) {
        out.push({
          value: e.id,
          label: e.name,
          disabled: paired.has(e.id),
          hint: paired.has(e.id) ? 'already separated' : undefined,
        });
      }
    }
    return out;
  }, [employees, separations]);

  const submit = async () => {
    setSaving(true);
    try {
      await axiosClient.post('/separations/', {
        employee_id: employeeId,
        target_employee_id: targetId,
      });
      onSaved();
    } catch (err: unknown) {
      onError(errorText(err, 'Could not create the separation.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border border-border rounded-xl p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">
            Person
          </label>
          <SelectMenu
            value={employeeId}
            onChange={setEmployeeId}
            placeholder="Select someone…"
            ariaLabel="Person"
            options={optionsFor(targetId)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">
            Kept apart from
          </label>
          <SelectMenu
            value={targetId}
            onChange={setTargetId}
            placeholder="Select someone…"
            ariaLabel="Kept apart from"
            options={optionsFor(employeeId)}
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={submit}
          disabled={saving || !employeeId || !targetId || employeeId === targetId}
          className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Separate'}
        </button>
        <button onClick={onCancel} className="px-3 py-2 rounded-lg border border-border text-sm">
          Cancel
        </button>
      </div>
    </div>
  );
}
