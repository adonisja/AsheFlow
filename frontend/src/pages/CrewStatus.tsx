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
    /* A GRID, not a flex row — this is a 33-row roster, so the same field must
       land in the same place on every line. Three tracks:

         name (1fr)     state (140px)     actions (auto)
         Rasheed Grant  Not Present       [Mark Present] [Mark Absent]
         Trainer

       Three earlier attempts all failed on spacing, and each failure was the
       same mistake — treating a table as a row of loose flex items:
         · `flex-1` on the name stretched it to ~870px and pushed state and
           actions to the far right, leaving a ~1000px gap mid-row;
         · stacking actions onto a second line copied the MOBILE layout, where
           it exists only because a ~350px row cannot fit the content;
         · `basis-64` capped the name but left three cramped groups huddled at
           the left of an otherwise empty row.
       A fixed state track is what makes the column align regardless of label
       length ("Not Present" vs "On route (early) · 40%"), and the name track is
       CAPPED at 22rem rather than `1fr` — measured at 1180px, `1fr` handed the
       name 953px for ~150px of text, which is the same dead space as `flex-1`
       wearing a grid. 22rem fits the longest real label
       ("Jerome Whitfield · training Akkeem Tyrell", ~330px) and lets the row
       end where the content ends.

       The actions track is `max-content`, not `auto`: measured on the rendered
       page, `auto` stretched it to 690px for ~200px of buttons — the same dead
       space, moved to the third column. `justify-start` stops the grid itself
       filling the row.

       STATE vs ACTION is carried by styling and wording, not by position:
         state   quiet tinted pill, plain noun, not clickable
         action  bordered/filled button, verb-first ("Mark Present")

       Below `sm` the tracks collapse to one column and everything stacks —
       the mobile layout, reached by constraint rather than a breakpoint guess.
       The name never truncates, so real names are not clipped at 390px. */
    <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,22rem)_140px_max-content] justify-start items-center gap-x-4 gap-y-2 py-2.5">
      <div className="min-w-0">
        <p className={`text-sm ${off ? 'text-muted-foreground line-through' : 'text-foreground'}`}>
          {m.name ?? m.employee_id.slice(0, 8)}
        </p>
        <p className="text-xs text-muted-foreground capitalize">
          {m.role}
          {m.role !== 'trainee' && m.paired_trainee_name ? ` · training ${m.paired_trainee_name}` : ''}
          {m.role === 'trainee' && m.paired_trainer_name ? ` · trainer ${m.paired_trainer_name}` : ''}
          {m.trip_count > 0 ? ` · ${m.trip_count} trip${m.trip_count === 1 ? '' : 's'}` : ''}
        </p>
      </div>

      {/* State track — always occupied so the actions column starts at the same
          x on every row, even for a driver with no availability tag. */}
      <div className="flex flex-wrap items-center gap-1.5">
        {m.orphaned && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full text-danger bg-danger/10">
            Trainer absent
          </span>
        )}
        {m.role !== 'driver' && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${AVAIL_COLOR[m.availability]}`}>
            {AVAIL_LABEL[m.availability]}
            {m.route_completion_pct != null ? ` · ${Math.round(m.route_completion_pct * 100)}%` : ''}
          </span>
        )}
      </div>

      {/* Actions track — verb-first, and only rendered when one applies. */}
      <div className="flex items-center gap-2">
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
