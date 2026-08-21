import { useCallback, useEffect, useMemo, useState } from 'react';
import { Users, RefreshCw, Search } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';
import { errorText } from '../utils/errorText';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import type {
  CrewStatusResponse,
  CrewStatusTruck,
  CrewStatusMember,
  AvailableTrainersResponse,
} from '../api/types';

/** Crew Status page (ADR-197 Phase B).
 *
 *  Fleet-aware: dispatch/mgmt/admin get every truck (tabbed, plus an "All" tab);
 *  captains/drivers get only their own truck. Each member shows availability
 *  (ADR-197 Phase 0b), trip count (ADR-199 D3), and pairing (ADR-199) — an
 *  orphaned trainee (trainer late/absent) exposes a dispatch-only Reassign
 *  action wired to the Phase B endpoints. Name filter narrows the active tab.
 */

/**
 * ONE grid definition for the header and every row — if these were written
 * twice they would drift, and a header that does not line up with its column
 * is worse than no header.
 *
 *   name            status        trips  progress   pairing        actions
 *   minmax(0,18rem) 8.5rem        4rem   7rem       minmax(0,12rem) max-content
 *
 * Only PAIRING flexes (`minmax(12rem,1fr)`). Measured, the fixed tracks left
 * 161px unused at the right of the card, so the actions column floated short
 * of the edge. Letting the widest TEXT column absorb the slack pushes actions
 * to the edge without reintroducing the mid-row stretch that a flexible FIRST
 * track caused. Everything else stays fixed, which is what keeps 197 rows
 * aligned. `gap-x-7` (28px) — 16px read as cramped for a six-column table.
 * `justify-between` spreads the whole grid to the card's width, so the row
 * uses the space instead of huddling left with ~490px empty — measured, that
 * was the state before these columns existed.
 *
 * Trips / progress / pairing are empty pre-shift and fill as crews go out.
 * An em dash is shown rather than a blank so an empty cell reads as "no value
 * yet" rather than a rendering fault.
 */
const CREW_GRID =
  'grid grid-cols-1 sm:grid-cols-[minmax(0,18rem)_8.5rem_4rem_7rem_minmax(12rem,1fr)_max-content] ' +
  'items-center gap-x-7 gap-y-1';

const AVAIL_LABEL: Record<CrewStatusMember['availability'], string> = {
  not_arrived: 'Not Present',
  available: 'Available',
  on_route_early: 'On route (early)',
  on_route_returning: 'On route (returning)',
  done: 'Done',
  off_crew: 'Off crew',
};
/* Semantic tokens, not raw palette utilities: a `bg-emerald-50` pill keeps its
   near-white fill in dark theme, and none of these follow a palette change.
   The `/10` tint gives a quiet pill on both themes from one value. */
const AVAIL_COLOR: Record<CrewStatusMember['availability'], string> = {
  not_arrived: 'text-muted-foreground bg-muted-foreground/10',
  available: 'text-success bg-success/10',
  on_route_early: 'text-warning bg-warning/10',
  on_route_returning: 'text-info bg-info/10',
  done: 'text-success bg-success/10',
  off_crew: 'text-muted-foreground bg-accent',
};

export default function CrewStatus() {
  const { groups } = useAuth();
  const isDispatch = groups.some(g => ['dispatch', 'management', 'admin'].includes(g));

  const [date, setDate] = useState(getLocalYMD());
  const [data, setData] = useState<CrewStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTruck, setActiveTruck] = useState<string>('all');
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [reassign, setReassign] = useState<CrewStatusMember | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axiosClient.get<CrewStatusResponse>(`/crew-status/${date}`);
      setData(data);
      setError(null);
    } catch (e) {
      setError(errorText(e, 'Could not load crew status.'));
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  const trucks = data?.trucks ?? [];
  const multiTruck = trucks.length > 1;

  const visibleTrucks: CrewStatusTruck[] = useMemo(() => {
    const chosen = activeTruck === 'all' ? trucks : trucks.filter(t => t.truck_assignment_id === activeTruck);
    const q = filter.trim().toLowerCase();
    if (!q) return chosen;
    return chosen
      .map(t => ({ ...t, members: t.members.filter(m => (m.name ?? '').toLowerCase().includes(q)) }))
      .filter(t => t.members.length > 0);
  }, [trucks, activeTruck, filter]);

  const markDeparted = async (memberId: string) => {
    setBusy(memberId);
    try {
      await axiosClient.patch(`/assignment-members/${memberId}/status`, { status: 'departed' });
      await load();
    } catch (e) {
      setError(errorText(e, 'Could not mark departed.'));
    } finally {
      setBusy(null);
    }
  };

  // Roll call (ADR-198): mark a not-arrived member in. The server derives
  // early/present/late from the clock; absent = ncns. Flips them off Not Arrived
  // into the working crew status (the soft presence gate).
  const takeRollCall = async (m: CrewStatusMember, absent: boolean) => {
    setBusy(m.employee_id);
    try {
      await axiosClient.post('/roll-call', { employee_id: m.employee_id, date, ncns: absent });
      await load();
    } catch (e) {
      setError(errorText(e, 'Could not record roll call.'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="p-4 space-y-4">
      <SectionHeader
        eyebrow="Operations"
        title={<span className="inline-flex items-center gap-2"><Users className="w-5 h-5" /> Crew Status</span>}
        description="Live crew availability, trips, and pairings"
      />

      <div className="flex flex-wrap items-center gap-3">
        <input
          type="date"
          value={date}
          onChange={e => setDate(e.target.value)}
          className="text-sm border border-border rounded px-2 py-1 bg-background"
        />
        <button
          onClick={load}
          className="inline-flex items-center gap-1 text-sm border border-border rounded px-2 py-1 hover:bg-accent"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
        <div className="relative ml-auto">
          <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            placeholder="Filter by name…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="text-sm border border-border rounded pl-7 pr-2 py-1 bg-background"
          />
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      {/* Truck tabs (multi-truck only) */}
      {multiTruck && (
        <div className="flex flex-wrap gap-1 border-b border-border">
          <TabButton active={activeTruck === 'all'} onClick={() => setActiveTruck('all')} label="All trucks" />
          {trucks.map(t => (
            <TabButton
              key={t.truck_assignment_id}
              active={activeTruck === t.truck_assignment_id}
              onClick={() => setActiveTruck(t.truck_assignment_id)}
              label={t.truck_name ?? t.truck_id.slice(0, 6)}
            />
          ))}
        </div>
      )}

      {!loading && trucks.length === 0 && (
        <p className="text-sm text-muted-foreground italic">No crew assigned on this date.</p>
      )}

      {visibleTrucks.map(truck => (
        <div key={truck.truck_assignment_id} className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold text-sm">{truck.truck_name ?? 'Truck'}</h3>
            <span className="text-xs text-muted-foreground">
              {truck.available_for_route} of {truck.active_crew} available for a route
            </span>
          </div>
          {/* Column header — hidden below `sm`, where the grid collapses to one
              column and headers would be meaningless. */}
          <div className={`${CREW_GRID} hidden sm:grid pb-1.5 border-b border-border text-[11px] font-semibold uppercase tracking-wider text-muted-foreground`}>
            <span>Crew</span>
            <span>Status</span>
            <span className="text-right">Trips</span>
            <span>Progress</span>
            <span>Pairing</span>
            <span className="text-right">Actions</span>
          </div>
          <div className="divide-y divide-border">
            {truck.members.map(m => (
              <MemberRow
                key={m.employee_id}
                m={m}
                isDispatch={isDispatch}
                busy={busy}
                onDepart={markDeparted}
                onReassign={() => setReassign(m)}
                onRollCall={takeRollCall}
              />
            ))}
          </div>
        </div>
      ))}

      {reassign && (
        <ReassignModal
          trainee={reassign}
          date={date}
          onClose={() => setReassign(null)}
          onDone={async () => { setReassign(null); await load(); }}
        />
      )}
    </div>
  );
}

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px transition-colors ${
        active ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'
      }`}
    >
      {label}
    </button>
  );
}

function MemberRow({
  m, isDispatch, busy, onDepart, onReassign, onRollCall,
}: {
  m: CrewStatusMember;
  isDispatch: boolean;
  busy: string | null;
  onDepart: (memberId: string) => void;
  onReassign: () => void;
  onRollCall: (m: CrewStatusMember, absent: boolean) => void;
}) {
  const off = m.membership_status !== 'active';
  const notArrived = m.availability === 'not_arrived';
  const rollBusy = busy === m.employee_id;
  return (
    /* Six cells, matching CREW_GRID's six header columns exactly. Fixed tracks
       keep them aligned down 197 rows; `1fr` anywhere here reintroduces the
       stretch that left ~490px of the card empty.

       Trips / Progress / Pairing are null pre-shift and fill as crews go out,
       so each renders an em dash rather than nothing — an empty cell should
       read as "no value yet", not as a broken render.

       STATE vs ACTION stays a styling distinction, not a positional one:
         state   quiet tinted pill, plain noun, not clickable
         action  bordered/filled button, verb-first ("Mark Present") */
    <div className={`${CREW_GRID} py-2.5`}>
      {/* 1 — crew member */}
      <div className="min-w-0">
        <p className={`text-sm ${off ? 'text-muted-foreground line-through' : 'text-foreground'}`}>
          {m.name ?? m.employee_id.slice(0, 8)}
        </p>
        <p className="text-xs text-muted-foreground capitalize">{m.role}</p>
      </div>

      {/* 2 — status */}
      <div className="flex flex-wrap items-center gap-1.5">
        {m.orphaned && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full text-danger bg-danger/10">
            Trainer absent
          </span>
        )}
        {m.role !== 'driver' && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${AVAIL_COLOR[m.availability]}`}>
            {AVAIL_LABEL[m.availability]}
          </span>
        )}
      </div>

      {/* 3 — trips */}
      <span className="text-xs tabular-nums text-right text-muted-foreground">
        {m.trip_count > 0 ? m.trip_count : '—'}
      </span>

      {/* 4 — progress. Stop count and percent are the same fact at two
             granularities; showing both would just be noise. */}
      <span className="text-xs tabular-nums text-muted-foreground">
        {m.current_stop_sequence != null && m.current_stop_total
          ? `${m.current_stop_sequence}/${m.current_stop_total}`
          : m.route_completion_pct != null
            ? `${Math.round(m.route_completion_pct * 100)}%`
            : '—'}
      </span>

      {/* 5 — pairing. A role-coloured initials chip plus the partner's name,
             so the cell reads as a RELATIONSHIP at a glance rather than as a
             string starting with an arrow character. The label above the name
             says which direction the pairing runs, which "→ A. Tyrell" left the
             reader to infer. Trainee violet / trainer amber are the same role
             tokens the rest of the app uses (ADR-254). */}
      {(() => {
        const partner = m.paired_trainee_name ?? m.paired_trainer_name;
        if (!partner) return <span className="text-xs text-muted-foreground">—</span>;
        const isTrainee = Boolean(m.paired_trainee_name);
        return (
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="shrink-0 grid place-items-center rounded-full text-[10px] font-semibold w-6 h-6"
              style={{
                background: `hsl(var(--${isTrainee ? 'trainee' : 'trainer'}) / 0.15)`,
                color: `hsl(var(--${isTrainee ? 'trainee' : 'trainer'}))`,
              }}
              aria-hidden
            >
              {partner.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()}
            </span>
            <span className="min-w-0">
              <span className="block text-[10px] uppercase tracking-wide text-muted-foreground leading-none">
                {isTrainee ? 'Training' : 'Trainer'}
              </span>
              <span className="block text-xs text-foreground truncate leading-tight">{partner}</span>
            </span>
          </div>
        );
      })()}

      {/* 6 — actions */}
      <div className="flex items-center justify-end gap-2">
        {isDispatch && notArrived && (
          <>
            <button
              className="text-xs font-medium text-success-foreground bg-success rounded-md px-2.5 py-1 hover:opacity-90 disabled:opacity-50"
              disabled={rollBusy}
              onClick={() => onRollCall(m, false)}
            >
              {rollBusy ? '…' : 'Mark Present'}
            </button>
            <button
              className="text-xs font-medium text-warning border border-warning/40 rounded-md px-2.5 py-1 hover:bg-warning/10 disabled:opacity-50"
              disabled={rollBusy}
              onClick={() => onRollCall(m, true)}
            >
              Mark Absent
            </button>
          </>
        )}

        {isDispatch && m.orphaned && (
          <button
            onClick={onReassign}
            className="text-xs font-medium text-primary-foreground bg-primary rounded-md px-2.5 py-1 hover:opacity-90"
          >
            Reassign trainer
          </button>
        )}

        {isDispatch && !off && !notArrived && m.member_id && m.role !== 'driver' && (
          <button
            className="text-xs font-medium text-muted-foreground border border-border rounded-md px-2.5 py-1 hover:bg-accent disabled:opacity-50"
            disabled={busy === m.member_id}
            onClick={() => onDepart(m.member_id!)}
          >
            {busy === m.member_id ? '…' : 'Mark departed'}
          </button>
        )}
      </div>
    </div>
  );
}

function ReassignModal({
  trainee, date, onClose, onDone,
}: {
  trainee: CrewStatusMember;
  date: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [sugg, setSugg] = useState<AvailableTrainersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    axiosClient
      .get<AvailableTrainersResponse>(`/dispatch/${date}/available-trainers/${trainee.employee_id}`)
      .then(({ data }) => setSugg(data))
      .catch(e => setError(errorText(e, 'Could not load available trainers.')));
  }, [date, trainee.employee_id]);

  const pick = async (trainerId: string) => {
    setBusy(trainerId);
    try {
      await axiosClient.post('/dispatch/reassign-trainee', {
        trainee_id: trainee.employee_id,
        new_trainer_id: trainerId,
        date,
      });
      onDone();
    } catch (e) {
      setError(errorText(e, 'Reassignment failed.'));
      setBusy(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-card rounded-lg border border-border p-4 w-full max-w-md space-y-3" onClick={e => e.stopPropagation()}>
        <h3 className="font-semibold text-sm">Reassign {trainee.name ?? 'trainee'}</h3>
        <p className="text-xs text-muted-foreground">
          Their trainer is absent. Choose an available trainer to pair them with.
        </p>
        {error && <ErrorBanner message={error} />}
        {!sugg && !error && <p className="text-xs text-muted-foreground">Loading…</p>}
        {sugg && sugg.suggestions.length === 0 && (
          <p className="text-xs text-muted-foreground italic">No available (trainee-less) trainers on this date.</p>
        )}
        <div className="divide-y divide-border">
          {sugg?.suggestions.map(s => (
            <div key={s.trainer_id} className="flex items-center gap-2 py-2">
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">{s.trainer_name ?? s.trainer_id.slice(0, 8)}</p>
                <p className="text-xs text-muted-foreground">
                  {s.truck_name ?? 'truck'}{s.same_truck ? ' · same truck' : ' · transfer'}
                  {s.has_route ? ' · has route' : ''}
                </p>
              </div>
              <button
                className="text-xs text-white bg-primary rounded px-2 py-1 hover:opacity-90 disabled:opacity-50"
                disabled={busy === s.trainer_id}
                onClick={() => pick(s.trainer_id)}
              >
                {busy === s.trainer_id ? '…' : 'Choose'}
              </button>
            </div>
          ))}
        </div>
        <div className="flex justify-end">
          <button onClick={onClose} className="text-xs border border-border rounded px-3 py-1 hover:bg-accent">Cancel</button>
        </div>
      </div>
    </div>
  );
}
