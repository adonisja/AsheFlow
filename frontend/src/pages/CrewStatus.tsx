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
const AVAIL_COLOR: Record<CrewStatusMember['availability'], string> = {
  not_arrived: 'text-slate-600 bg-slate-100',
  available: 'text-emerald-600 bg-emerald-50',
  on_route_early: 'text-amber-600 bg-amber-50',
  on_route_returning: 'text-sky-600 bg-sky-50',
  done: 'text-emerald-600 bg-emerald-50',
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
    <div className="max-w-5xl mx-auto p-4 space-y-4">
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
    <div className="flex items-center gap-3 py-2">
      <div className="flex-1 min-w-0">
        <p className={`text-sm truncate ${off ? 'text-muted-foreground line-through' : 'text-foreground'}`}>
          {m.name ?? m.employee_id.slice(0, 8)}
        </p>
        <p className="text-xs text-muted-foreground capitalize">
          {m.role}
          {m.role !== 'trainee' && m.paired_trainee_name ? ` · training ${m.paired_trainee_name}` : ''}
          {m.role === 'trainee' && m.paired_trainer_name ? ` · trainer ${m.paired_trainer_name}` : ''}
        </p>
      </div>

      {m.trip_count > 0 && (
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {m.trip_count} trip{m.trip_count === 1 ? '' : 's'}
        </span>
      )}

      {m.orphaned && (
        <span className="text-xs font-medium px-2 py-0.5 rounded-full text-red-600 bg-red-50">Trainer absent</span>
      )}

      {m.role !== 'driver' && (
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${AVAIL_COLOR[m.availability]}`}>
          {AVAIL_LABEL[m.availability]}
          {m.route_completion_pct != null ? ` · ${Math.round(m.route_completion_pct * 100)}%` : ''}
        </span>
      )}

      {/* Roll call: mark a not-arrived member in (Present) or absent. Dispatch can
          mark any crew member; the server derives early/present/late from the clock. */}
      {isDispatch && notArrived && (
        <div className="flex items-center gap-1">
          {/* `success` token, not bg-emerald-600 + text-white: that pair is
              3.77:1 on 12px text — an AA failure — and a raw palette utility
              does not follow a theme change. Token is 6.53:1 light / 9.76:1
              dark. Same class as the mobile fixes in ADR-255. */}
          <button
            className="text-xs text-success-foreground bg-success rounded px-2 py-1 hover:opacity-90 disabled:opacity-50"
            disabled={rollBusy}
            onClick={() => onRollCall(m, false)}
          >
            {rollBusy ? '…' : 'Present'}
          </button>
          <button
            className="text-xs text-amber-700 border border-amber-300 rounded px-2 py-1 hover:bg-amber-50 disabled:opacity-50"
            disabled={rollBusy}
            onClick={() => onRollCall(m, true)}
          >
            Absent
          </button>
        </div>
      )}

      {isDispatch && m.orphaned && (
        <button
          onClick={onReassign}
          className="text-xs text-white bg-primary rounded px-2 py-1 hover:opacity-90"
        >
          Reassign
        </button>
      )}

      {isDispatch && !off && !notArrived && m.member_id && m.role !== 'driver' && (
        <button
          className="text-xs text-muted-foreground border border-border rounded px-2 py-1 hover:bg-accent disabled:opacity-50"
          disabled={busy === m.member_id}
          onClick={() => onDepart(m.member_id!)}
        >
          {busy === m.member_id ? '…' : 'Departed'}
        </button>
      )}
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
