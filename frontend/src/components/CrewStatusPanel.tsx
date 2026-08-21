import { useCallback, useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type {
  CrewAvailabilityResponse,
  CrewAvailabilityEntry,
  DeliveryStopResponse,
  RouteResponse,
} from '../api/types';

/** Crew status + live route board (ADR-197 Phase 0b/0a).
 *
 *  - Availability: who can take a NEW route this wave (active + free or >65%
 *    through their route). Dispatch/captain marks a member departed here.
 *  - Live board: select an active route to see where its walker is
 *    (planned / in_progress / completed per stop).
 *
 *  Both read-only-until-acted; the depart action is dispatch/captain gated
 *  server-side. Verified live after the staging deploy (ADR-197).
 */

const AVAIL_LABEL: Record<CrewAvailabilityEntry['availability'], string> = {
  not_arrived: 'Not Present',
  available: 'Available',
  on_route_early: 'On route (early)',
  on_route_returning: 'On route (returning)',
  done: 'Done',
  off_crew: 'Off crew',
};
const AVAIL_COLOR: Record<CrewAvailabilityEntry['availability'], string> = {
  not_arrived: 'text-slate-600 bg-slate-100',
  available: 'text-emerald-600 bg-emerald-50',
  on_route_early: 'text-amber-600 bg-amber-50',
  on_route_returning: 'text-sky-600 bg-sky-50',
  done: 'text-emerald-600 bg-emerald-50',
  off_crew: 'text-muted-foreground bg-accent',
};
const STOP_COLOR: Record<DeliveryStopResponse['status'], string> = {
  planned: 'text-muted-foreground',
  in_progress: 'text-sky-600 font-semibold',
  completed: 'text-emerald-600 line-through',
};

export default function CrewStatusPanel({
  assignmentId,
  routes,
}: {
  assignmentId: string;
  routes: RouteResponse[];
}) {
  const [avail, setAvail] = useState<CrewAvailabilityResponse | null>(null);
  const [members, setMembers] = useState<{ id: string; employee_id: string; role: string; status: string }[]>([]);
  const [boardRouteId, setBoardRouteId] = useState<string | null>(null);
  const [board, setBoard] = useState<DeliveryStopResponse[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, m] = await Promise.all([
        axiosClient.get<CrewAvailabilityResponse>(`/assignment-members/${assignmentId}/availability`),
        axiosClient.get<{ id: string; employee_id: string; role: string; status: string }[]>(`/assignment-members/${assignmentId}`),
      ]);
      setAvail(a.data);
      setMembers(m.data ?? []);
      setError(null);
    } catch {
      setError('Could not load crew status.');
    }
  }, [assignmentId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!boardRouteId) { setBoard([]); return; }
    axiosClient.get<DeliveryStopResponse[]>(`/rts/stops/${boardRouteId}`)
      .then(({ data }) => setBoard(data ?? []))
      .catch(() => setBoard([]));
  }, [boardRouteId]);

  const markDeparted = async (memberId: string) => {
    setBusy(memberId);
    try {
      await axiosClient.patch(`/assignment-members/${memberId}/status`, { status: 'departed' });
      await load();
    } catch {
      setError('Could not mark departed.');
    } finally {
      setBusy(null);
    }
  };

  const nameFor = (eid: string) =>
    avail?.entries.find(e => e.employee_id === eid)?.name ?? eid.slice(0, 8);
  const memberIdFor = (eid: string) => members.find(m => m.employee_id === eid)?.id ?? null;

  const activeRoutes = routes.filter(r => r.status === 'assigned' || r.status === 'in_progress');

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <h3 className="font-semibold text-sm">Crew status</h3>
        {avail && (
          <span className="text-xs text-muted-foreground">
            {avail.available_for_route} of {avail.active_crew} available for a route
          </span>
        )}
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {/* Availability list + depart action */}
      <div className="divide-y divide-border">
        {avail?.entries
          .filter(e => e.role !== 'driver')
          .map(e => {
            const mid = memberIdFor(e.employee_id);
            const off = e.membership_status !== 'active';
            return (
              <div key={e.employee_id} className="flex items-center gap-3 py-2">
                <div className="flex-1 min-w-0">
                  <p className={`text-sm truncate ${off ? 'text-muted-foreground line-through' : 'text-foreground'}`}>
                    {e.name ?? nameFor(e.employee_id)}
                  </p>
                  <p className="text-xs text-muted-foreground capitalize">{e.role}</p>
                </div>
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${AVAIL_COLOR[e.availability]}`}>
                  {AVAIL_LABEL[e.availability]}
                  {e.route_completion_pct != null ? ` · ${Math.round(e.route_completion_pct * 100)}%` : ''}
                </span>
                {!off && mid && (
                  <button
                    className="text-xs text-muted-foreground border border-border rounded px-2 py-1 hover:bg-accent disabled:opacity-50"
                    disabled={busy === mid}
                    onClick={() => markDeparted(mid)}
                  >
                    {busy === mid ? '…' : 'Departed'}
                  </button>
                )}
              </div>
            );
          })}
      </div>

      {/* Live route board */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs font-medium text-muted-foreground">Live board</span>
          <select
            className="text-xs border border-border rounded px-2 py-1 bg-background"
            value={boardRouteId ?? ''}
            onChange={e => setBoardRouteId(e.target.value || null)}
          >
            <option value="">Select a route…</option>
            {activeRoutes.map(r => (
              <option key={r.id} value={r.id}>
                #{r.route_number} · {r.executor?.name ?? 'unassigned'}
              </option>
            ))}
          </select>
        </div>
        {boardRouteId && (
          board.length > 0 ? (
            <ol className="space-y-1">
              {board.map(stop => (
                <li key={stop.id} className={`text-xs flex justify-between ${STOP_COLOR[stop.status]}`}>
                  <span className="truncate">{stop.stop_sequence}. {stop.normalised_address}</span>
                  <span className="ml-2 shrink-0 capitalize">{stop.status.replace('_', ' ')}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-muted-foreground italic">No stops recorded for this route yet.</p>
          )
        )}
      </div>
    </div>
  );
}
