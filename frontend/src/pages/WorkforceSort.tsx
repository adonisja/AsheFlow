import { useCallback, useEffect, useMemo, useState } from 'react';
import { Route as RouteIcon, RefreshCw, Play, AlertTriangle, Users } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';
import { errorText } from '../utils/errorText';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import type {
  WorkforceRouteOut,
  CommitWorkforceSortOut,
  TruckDayTotalsOut,
} from '../api/types';

/** Build Routes — workforce mode's sort (ADR-291/302/402).
 *
 *  Full mode receives every package with an address attached and sorts once.
 *  Workforce mode DISCOVERS the work: a captain opens each tote, reads 1-3
 *  addresses, and this turns that accumulated geography into routes. So the
 *  sort is re-runnable by design, and re-running is the normal case rather
 *  than a recovery step.
 *
 *  ADR-302 D2 governs what a re-run may touch, and the rule is physical:
 *  `in_progress` and `completed` routes are FILTERED OUT because their totes
 *  left the truck with a walker; `assigned` routes are clearable but only on
 *  an explicit choice, because someone was told that route was theirs.
 *
 *  ADR-402 D4: there is no mobile app in the field yet, so this page is used
 *  ON A PHONE. It is built narrow-first — cards, not a table — and widens on
 *  a desktop rather than the reverse.
 */

/** ADR-402 D4. The captain reads this one-handed in a truck, so a route is a
 *  card that stacks, never a table row that needs sideways scrolling. */
function RouteCard({ r, onAct, busy }: {
  r: WorkforceRouteOut;
  onAct: (action: 'depart' | 'close' | 'count', route: WorkforceRouteOut) => void;
  busy: boolean;
}) {
  const executor = r.participants.find(p => p.role === 'executor');
  const supervisors = r.participants.filter(p => p.role === 'supervisor');

  // ADR-402 D2: derived, never stored. Only when BOTH stamps exist — a route
  // that is out has no duration yet, and 0 would read as "took no time".
  const duration = useMemo(() => {
    if (!r.departed_at || !r.returned_at) return null;
    const mins = Math.round(
      (new Date(r.returned_at).getTime() - new Date(r.departed_at).getTime()) / 60000,
    );
    if (mins < 0) return null;
    return mins < 60 ? `${mins}m` : `${Math.floor(mins / 60)}h ${mins % 60}m`;
  }, [r.departed_at, r.returned_at]);

  // ADR-406 D1. `reserved` is not a status — it is what an assigned route looks
  // like while its walker is out with another. Shown distinctly because the
  // captain's question is "what can be walked NOW", and a route held for
  // someone mid-route answers that differently from one waiting to go.
  const reserved = r.assignment_kind === 'reserved';
  const label = reserved ? 'reserved' : r.status.replace('_', ' ');
  const tone =
    r.status === 'completed'   ? 'bg-success/10 text-success'
    : r.status === 'in_progress' ? 'bg-primary/10 text-primary'
    : reserved                   ? 'bg-accent text-muted-foreground'
    : r.status === 'assigned'    ? 'bg-warning/10 text-warning'
    : 'bg-accent text-muted-foreground';

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-lg font-semibold">Route {r.route_number}</span>
          {/* ADR-400 A4: an OV is its own unit, so it is counted separately.
              Folding it into "12 totes" would tell a captain to look for
              twelve bags when two of them are loose packages. */}
          <span className="text-xs text-muted-foreground">
            {(() => {
              const ovs = r.tote_ids.filter(t => /^OV\d+$/.test(t)).length;
              const totes = r.tote_ids.length - ovs;
              const parts = [];
              if (totes) parts.push(`${totes} ${totes === 1 ? 'tote' : 'totes'}`);
              if (ovs) parts.push(`${ovs} OV`);
              return parts.join(' + ') || 'empty';
            })()}
          </span>
        </div>
        <span className={`px-2 py-0.5 rounded-lg text-[11px] font-medium capitalize ${tone}`}>
          {label}
        </span>
      </div>

      {/* Crew. A training pair is a trainee executing with a trainer
          supervising (ADR-212), so both are named — the flattened
          assigned_to_name could only ever show one of them. */}
      <div className="flex items-start gap-2 text-sm">
        <Users className="w-4 h-4 mt-0.5 text-muted-foreground shrink-0" />
        {r.participants.length === 0 ? (
          <span className="text-muted-foreground">Not assigned</span>
        ) : (
          <div className="min-w-0">
            <span className="font-medium">{executor?.name ?? 'Unassigned'}</span>
            {reserved && (
              <span className="text-muted-foreground"> (waiting for them)</span>
            )}
            {supervisors.length > 0 && (
              <span className="text-muted-foreground">
                {' '}with {supervisors.map(s => s.name).join(', ')}
              </span>
            )}
          </div>
        )}
      </div>

      {(r.departed_at || r.returned_at) && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground tabular-nums">
          {r.departed_at && <span>Out {new Date(r.departed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}
          {r.returned_at && <span>Back {new Date(r.returned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}
          {duration && <span className="font-medium text-foreground">{duration}</span>}
        </div>
      )}

      {r.block_keys.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {r.block_keys.map(b => (
            <span key={b} className="px-1.5 py-0.5 rounded bg-accent text-[11px] text-muted-foreground">
              {b.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}

      {/* The day's state transitions. The captain drives all of them: the
          walker is on the street, and a button they cannot press is worse than
          no button (ADR-300 D1).

          A RESERVED route gets none of these — depart refuses a route whose
          status is not `assigned`, so the buttons would only 409. */}
      {!reserved && (r.status === 'assigned' || r.status === 'in_progress') && (
        <div className="flex flex-wrap gap-2 pt-1">
          {r.status === 'assigned' && (
            <button
              className="btn-primary text-sm"
              onClick={() => onAct('depart', r)}
              disabled={busy}
            >
              Send out
            </button>
          )}
          {r.status === 'in_progress' && (
            <>
              <button
                className="btn-ghost text-sm"
                onClick={() => onAct('count', r)}
                disabled={busy}
              >
                {r.flex_package_count === null ? 'Record Flex count' : 'Edit count'}
              </button>
              <button
                className="btn-primary text-sm"
                onClick={() => onAct('close', r)}
                disabled={busy}
              >
                Close route
              </button>
            </>
          )}
        </div>
      )}

      {/* ADR-291 D11 / ADR-297 D5: flex_package_count is THE parcel count.
          package_count counts captain-entered ADDRESSES and is deliberately
          not shown — displaying both invites reading an address count as a
          parcel count. Null means not recorded yet, which is not zero. */}
      {r.flex_package_count !== null && (
        <div className="text-xs text-muted-foreground">
          {r.flex_package_count} {r.flex_package_count === 1 ? 'package' : 'packages'} scanned
        </div>
      )}
    </div>
  );
}

export default function WorkforceSort() {
  const { hasFeature } = useAuth();
  const [date] = useState(getLocalYMD());
  const [taId, setTaId] = useState<string | null>(null);
  const [routes, setRoutes] = useState<WorkforceRouteOut[]>([]);
  const [totals, setTotals] = useState<TruckDayTotalsOut | null>(null);
  const [result, setResult] = useState<CommitWorkforceSortOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [sorting, setSorting] = useState(false);
  const [error, setError] = useState('');
  const [confirmClear, setConfirmClear] = useState(false);
  const [acting, setActing] = useState(false);
  const [countFor, setCountFor] = useState<WorkforceRouteOut | null>(null);
  const [countValue, setCountValue] = useState('');
  const [closeNoCount, setCloseNoCount] = useState<WorkforceRouteOut | null>(null);

  /** The truck-assignment id is what every write here is keyed by, and no
   *  workforce endpoint hands it over: `my-truck` returns truck_id, and
   *  `day-totals` REQUIRES the assignment id to return it. Mobile derives it
   *  from /dispatch/{date}, which is full-mode only and 404s here — so this
   *  reads the company-scoped truck-assignments list instead, which is
   *  mode-independent. */
  const bootstrap = useCallback(async () => {
    setLoading(true);
    try {
      const mine = await axiosClient.get<{ truck_id: string | null }>(
        `/workforce/my-truck/${date}`,
      );
      const truckId = mine.data.truck_id;
      if (!truckId) { setTaId(null); setError(''); return; }

      // `/assignments/`, not `/truck-assignments/` — the router file is named
      // truck_assignments.py but its prefix is `/assignments`. Sort.tsx and
      // WalkerSort.tsx both call it this way; test_ui_api_paths_exist caught
      // the guess.
      const tas = await axiosClient.get<{ id: string; truck_id: string }[]>(
        '/assignments/', { params: { date } },
      );
      const ta = tas.data.find(t => t.truck_id === truckId);
      if (!ta) { setTaId(null); setError(''); return; }
      setTaId(ta.id);
      setError('');
    } catch (e: unknown) {
      setError(errorText(e, 'Could not work out which truck you are on.'));
    } finally {
      setLoading(false);
    }
  }, [date]);

  const loadRoutes = useCallback(async (assignmentId: string) => {
    try {
      // Not Promise.all: a failing sibling would sink the whole batch and
      // blank a page whose other half loaded fine.
      const r = await axiosClient.get<WorkforceRouteOut[]>(
        `/workforce/routes/${date}`, { params: { truck_assignment_id: assignmentId } },
      );
      setRoutes(r.data);
      try {
        const t = await axiosClient.get<TruckDayTotalsOut>(
          `/workforce/day-totals/${date}`, { params: { truck_assignment_id: assignmentId } },
        );
        setTotals(t.data);
      } catch { /* totals are a nicety; routes are the page */ }
      setError('');
    } catch (e: unknown) {
      setError(errorText(e, 'Could not load this truck’s routes.'));
    }
  }, [date]);

  useEffect(() => { bootstrap(); }, [bootstrap]);
  useEffect(() => { if (taId) loadRoutes(taId); }, [taId, loadRoutes]);

  const assigned = useMemo(() => routes.filter(r => r.status === 'assigned'), [routes]);

  const send = useCallback(async (
    action: 'depart' | 'close', route: WorkforceRouteOut,
  ) => {
    setActing(true);
    try {
      await axiosClient.patch(`/workforce/routes/${route.id}/${action}`);
      setError('');
      if (taId) await loadRoutes(taId);
    } catch (e: unknown) {
      setError(errorText(e, `Could not ${action === 'depart' ? 'send that route out' : 'close that route'}.`));
    } finally {
      setActing(false);
      setCloseNoCount(null);
    }
  }, [taId, loadRoutes]);

  const act = useCallback(async (
    action: 'depart' | 'close' | 'count', route: WorkforceRouteOut,
  ) => {
    if (action === 'count') {
      setCountValue(route.flex_package_count?.toString() ?? '');
      setCountFor(route);
      return;
    }
    // ADR-401 D2. THE PRE-CLOSE WARNING. Closing FREEZES flex_package_count
    // (ADR-300 D5): a route closed without one can never be given one, and its
    // packages are then missing from every figure the day produces. The server
    // does not refuse — a captain may have a real reason — so this is the only
    // place the hole can be prevented rather than reported afterwards.
    if (action === 'close' && route.flex_package_count === null) {
      setCloseNoCount(route);
      return;
    }
    await send(action, route);
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const saveCount = useCallback(async () => {
    if (!countFor) return;
    const n = Number(countValue);
    if (!Number.isInteger(n) || n < 0 || n > 2000) {
      setError('Enter the package count Flex showed, between 0 and 2000.');
      return;
    }
    setActing(true);
    try {
      await axiosClient.patch(
        `/workforce/routes/${countFor.id}/package-count`, { package_count: n },
      );
      setCountFor(null);
      setError('');
      if (taId) await loadRoutes(taId);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not record that count.'));
    } finally {
      setActing(false);
    }
  }, [countFor, countValue, taId, loadRoutes]);

  /** ADR-302 D2a. Clearing a route someone was told is theirs is an
   *  operational act, so `clearAll` is passed only from the confirm dialog —
   *  never inferred, and never the default. */
  const runSort = useCallback(async (clearAll: boolean) => {
    if (!taId) return;
    setSorting(true);
    try {
      const res = await axiosClient.post<CommitWorkforceSortOut>(
        '/workforce/commit-sort',
        { truck_assignment_id: taId, route_date: date, clear_all_assigned: clearAll },
      );
      setResult(res.data);
      setRoutes(res.data.routes);
      setError('');
      loadRoutes(taId);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not build routes.'));
    } finally {
      setSorting(false);
      setConfirmClear(false);
    }
  }, [taId, date, loadRoutes]);

  if (!hasFeature('workforce_sort')) {
    return (
      <div className="card p-6 text-sm text-muted-foreground">
        Route building is part of workforce mode. This company sorts from an
        Amazon package feed instead.
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <SectionHeader
        eyebrow="Workforce sort"
        title={<span className="flex items-center gap-2"><RouteIcon className="w-5 h-5" /> Build Routes</span>}
        description="Group the totes you have addressed into routes"
      />

      <ErrorBanner message={error || null} />

      {loading ? (
        <div className="card p-6 text-sm text-muted-foreground">Loading…</div>
      ) : !taId ? (
        <div className="card p-6 text-sm text-muted-foreground">
          You are not crewed on a truck today, so there is nothing to sort.
        </div>
      ) : (
        <>
          <div className="card p-4 flex flex-wrap items-center gap-3">
            <button
              className="btn-primary flex items-center gap-2"
              onClick={() => (assigned.length > 0 ? setConfirmClear(true) : runSort(false))}
              disabled={sorting}
            >
              <Play className="w-4 h-4" />
              {sorting ? 'Building…' : routes.length > 0 ? 'Re-build routes' : 'Build routes'}
            </button>
            <button
              className="btn-ghost flex items-center gap-2"
              onClick={() => taId && loadRoutes(taId)}
              disabled={sorting}
            >
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
            {totals && (
              <span className="text-xs text-muted-foreground ml-auto tabular-nums">
                {totals.routes_closed}/{totals.routes_total} closed
              </span>
            )}
          </div>

          {/* Everything the sort could not place. Reported, never silently
              dropped — a tote missing from a route is a tote nobody walks. */}
          {result && (
            <div className="card p-4 space-y-2 text-sm">
              <div className="font-medium">
                Sorted {result.totes_sorted} {result.totes_sorted === 1 ? 'tote' : 'totes'}
                {' '}into {result.routes.length} {result.routes.length === 1 ? 'route' : 'routes'}
              </div>
              {result.retained_routes > 0 && (
                <div className="text-muted-foreground">
                  {result.retained_routes} route{result.retained_routes === 1 ? ' is' : 's are'} already
                  out with a walker, so {result.retained_routes === 1 ? 'it was' : 'they were'} left alone.
                </div>
              )}
              {result.unaddressed_bags.length > 0 && (
                <div className="flex items-start gap-2 text-warning">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>
                    Not routed, no address entered:{' '}
                    <span className="font-medium">{result.unaddressed_bags.join(', ')}</span>
                  </span>
                </div>
              )}
              {result.unparseable.length > 0 && (
                <div className="flex items-start gap-2 text-warning">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>
                    Address could not be read:{' '}
                    <span className="font-medium">{result.unparseable.join(', ')}</span>
                  </span>
                </div>
              )}
              {result.disagreements.length > 0 && (
                <div className="text-muted-foreground">
                  {result.disagreements.length} tote
                  {result.disagreements.length === 1 ? ' had' : 's had'} addresses on different
                  blocks. The sort used the most common one.
                </div>
              )}
              {result.overflowed_routes > 0 && (
                <div className="text-warning">
                  {result.overflowed_routes} route
                  {result.overflowed_routes === 1 ? ' is' : 's are'} over the capacity limit.
                </div>
              )}
            </div>
          )}

          {routes.length === 0 ? (
            <div className="card p-6 text-sm text-muted-foreground">
              No routes yet. Address the totes on your truck, then build routes.
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {routes.map(r => <RouteCard key={r.id} r={r} onAct={act} busy={acting} />)}
            </div>
          )}
        </>
      )}

      {/* ADR-291 D11. The count a captain reads off Amazon Flex while the
          walker scans. AsheFlow's own package_count counts captain-entered
          ADDRESSES — a tote with three addresses may hold fifty parcels — so
          this transcription is the only true package number the day produces. */}
      {countFor && (
        <div className="card p-4 space-y-3">
          <div className="font-medium">Route {countFor.route_number}: Flex count</div>
          <p className="text-xs text-muted-foreground">
            The number of packages Amazon Flex showed when this route was
            scanned.
          </p>
          <input
            className="input w-full"
            inputMode="numeric"
            value={countValue}
            onChange={e => setCountValue(e.target.value)}
            placeholder="e.g. 52"
            autoFocus
          />
          <div className="flex gap-2">
            <button className="btn-primary" onClick={saveCount} disabled={acting}>
              {acting ? 'Saving…' : 'Save count'}
            </button>
            <button className="btn-ghost" onClick={() => setCountFor(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ADR-401 D2 / ADR-300 D5. The close FREEZES the Flex count, so a route
          closed without one can never be given one. The server permits it — a
          captain may have a real reason — which makes this the only place the
          hole can be prevented rather than discovered in a report weeks later. */}
      <ConfirmDialog
        open={closeNoCount !== null}
        title="Close without a Flex count?"
        message={
          `Route ${closeNoCount?.route_number} has no package count. Closing ` +
          `locks that in: the count cannot be added afterwards, and this ` +
          `route's packages will be missing from the day's totals.`
        }
        confirmLabel="Close anyway"
        cancelLabel="Go back"
        variant="warning"
        onConfirm={() => closeNoCount && send('close', closeNoCount)}
        onCancel={() => setCloseNoCount(null)}
      />

      <ConfirmDialog
        open={confirmClear}
        title="Re-build every route?"
        message={
          `${assigned.length} route${assigned.length === 1 ? ' has' : 's have'} already been ` +
          `assigned to a walker. Re-building clears ${assigned.length === 1 ? 'it' : 'them'} ` +
          `and plans again from every addressed tote. Routes already out with a walker are ` +
          `left alone.`
        }
        confirmLabel="Re-build"
        variant="warning"
        onConfirm={() => runSort(true)}
        onCancel={() => setConfirmClear(false)}
      />
    </div>
  );
}
