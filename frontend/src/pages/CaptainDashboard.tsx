import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Truck, Users, Route as RouteIcon, PackageX, Boxes,
  AlertTriangle, RefreshCw, ChevronRight, MapPin,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';

/**
 * Captain's home (ADR-274 D20).
 *
 * A captain is a truck's route lead — they run the anchor-point sort, own RTS
 * and reattempts, and answer for the crew. Until now they had no web landing
 * page at all: `homeRouteForGroups` dropped them to `/`, and `captain` was in
 * none of the web role lists.
 *
 * SYNOPSIS, NOT A SIXTH COPY OF THE DATA. Every card summarises a page that
 * already exists and links to it — the captain's day is one truck, so the value
 * here is seeing all four signals at once, not new functionality. Anything that
 * needs detail belongs on the page that owns it.
 *
 * NEEDS-YOU STRIP. Read at 06:00 between tasks, not studied. The counts that
 * imply an action surface above the fold and only when non-zero, so a quiet
 * morning renders a quiet page.
 *
 * EMPTY STATE, NOT YESTERDAY. A captain not crewed today gets "no truck
 * assigned", never their last truck's crew — showing stale crew as if it were
 * today is how someone ends up at the wrong bay talking to the wrong people.
 */

interface CrewMember {
  employee_id: string;
  name?: string | null;
  role: string;
  availability: string;
  route_completion_pct?: number | null;
}
interface CrewTruck {
  truck_assignment_id: string;
  truck_id: string;
  truck_name?: string | null;
  active_crew: number;
  available_for_route: number;
  members: CrewMember[];
}

export default function CaptainDashboard() {
  const navigate = useNavigate();
  const today = getLocalYMD();

  const [loading, setLoading]   = useState(true);
  const [truck, setTruck]       = useState<CrewTruck | null>(null);
  const [dockZone, setDockZone] = useState<string | null>(null);
  const [routes, setRoutes]     = useState<{ status: string }[]>([]);
  const [rts, setRts]           = useState<{ rts_count?: number; reattempts_pending?: number } | null>(null);
  const [roster, setRoster]     = useState<{ tote_count: number; checked_count: number; load_confirmed?: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Crew status is the anchor: it resolves WHICH truck is mine, and the
      // backend already truck-scopes a captain to their own (ADR-256 D11), so
      // trucks[0] is the captain's truck rather than an arbitrary one.
      const crew = await axiosClient.get(`/crew-status/${today}`);
      const mine: CrewTruck | undefined = (crew.data?.trucks ?? [])[0];
      setTruck(mine ?? null);

      if (!mine) return;   // not crewed today — the empty state below

      // Everything after this hangs off the truck assignment. Failures are
      // tolerated per-card: one dead endpoint must not blank the whole page,
      // because the other three signals are still actionable.
      const taId = mine.truck_assignment_id;
      await Promise.all([
        axiosClient.get(`/walker-routes/${taId}/routes`)
          .then(r => setRoutes(r.data ?? [])).catch(() => {}),
        axiosClient.get(`/rts/summary/${taId}`)
          .then(r => setRts(r.data)).catch(() => {}),
        axiosClient.get(`/sort/${today}/rosters`, { params: { mine: true } })
          .then(r => setRoster((r.data?.rosters ?? [])[0] ?? null)).catch(() => {}),
        axiosClient.get(`/dispatch/${today}`)
          .then(r => {
            const ts = (r.data?.truck_assignments ?? [])
              .find((t: { truck_id: string }) => t.truck_id === mine.truck_id);
            setDockZone(ts?.dock_zone ?? null);
          }).catch(() => {}),
      ]);
    } catch {
      setTruck(null);
    } finally {
      setLoading(false);
    }
  }, [today]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading your truck…
      </div>
    );
  }

  if (!truck) {
    return (
      <div className="space-y-6 animate-slide-up">
        <Header dockZone={null} truckName={null} />
        <div className="card text-center py-16">
          <Truck className="w-12 h-12 mx-auto text-muted-foreground opacity-20 mb-3" />
          <h3 className="text-base font-medium text-foreground">No truck assigned today</h3>
          <p className="text-sm text-subtle mt-1 max-w-sm mx-auto">
            You are not on a crew for {today}. Dispatch assigns captains on the
            Assignments board — this page fills in once you are placed.
          </p>
        </div>
      </div>
    );
  }

  const unassigned = routes.filter(r => r.status === 'unassigned').length;
  const notArrived = truck.members.filter(m => m.availability === 'not_arrived').length;
  const unchecked  = roster ? Math.max(0, roster.tote_count - roster.checked_count) : 0;
  const needs: { label: string; n: number; to: string }[] = [
    { label: `${unassigned} route${unassigned === 1 ? '' : 's'} unassigned`, n: unassigned, to: '/walker-sort' },
    { label: `${unchecked} tote${unchecked === 1 ? '' : 's'} unchecked`,     n: unchecked,  to: '/walker-sort' },
    { label: `${notArrived} crew not arrived`,                              n: notArrived, to: '/crew-status' },
  ].filter(x => x.n > 0);

  const done = routes.filter(r => r.status === 'completed').length;

  return (
    <div className="space-y-6 animate-slide-up">
      <Header dockZone={dockZone} truckName={truck.truck_name ?? null} />

      {needs.length > 0 && (
        <div className="card border-warning/30 bg-warning/5">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-warning" />
            <h2 className="text-sm font-semibold text-foreground">Needs you</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {needs.map(n => (
              <button
                key={n.label}
                onClick={() => navigate(n.to)}
                className="flex items-center gap-1 text-xs font-medium bg-warning/10 text-warning hover:bg-warning/20 px-2.5 py-1 rounded-lg transition-colors"
              >
                {n.label}<ChevronRight className="w-3 h-3" />
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title="My Crew" icon={Users} to="/crew-status" navigate={navigate}
              hint={`${truck.active_crew} active · ${truck.available_for_route} free`}>
          <ul className="space-y-1.5">
            {truck.members.slice(0, 5).map(m => (
              <li key={m.employee_id} className="flex items-center justify-between text-sm">
                <span className="text-foreground truncate">{m.name ?? '—'}</span>
                <span className="text-xs text-muted-foreground capitalize shrink-0 ml-2">
                  {m.role} · {m.availability.replace(/_/g, ' ')}
                </span>
              </li>
            ))}
            {truck.members.length > 5 && (
              <li className="text-xs text-muted-foreground pt-1">
                +{truck.members.length - 5} more
              </li>
            )}
          </ul>
        </Card>

        <Card title="Routes" icon={RouteIcon} to="/walker-sort" navigate={navigate}
              hint={routes.length ? `${done}/${routes.length} complete` : 'not committed'}>
          {routes.length === 0 ? (
            <Empty text="No routes committed yet — commit the sort on AP Sort." />
          ) : (
            <Stat rows={[
              ['Committed', routes.length],
              ['Unassigned', unassigned],
              ['Complete', done],
            ]} />
          )}
        </Card>

        <Card title="Station Load" icon={Boxes} to="/walker-sort" navigate={navigate}
              hint={roster?.load_confirmed ? 'confirmed' : 'not confirmed'}>
          {!roster ? (
            <Empty text="No roster yet — it appears after the station sort." />
          ) : (
            <Stat rows={[
              ['Totes', roster.tote_count],
              ['Checked', roster.checked_count],
              ['Outstanding', unchecked],
            ]} />
          )}
        </Card>

        <Card title="Returns" icon={PackageX} to="/field-ops" navigate={navigate}
              hint="RTS & reattempts">
          {!rts ? (
            <Empty text="Nothing returned yet today." />
          ) : (
            <Stat rows={[
              ['RTS packages', rts.rts_count ?? 0],
              ['Reattempts pending', rts.reattempts_pending ?? 0],
            ]} />
          )}
        </Card>
      </div>
    </div>
  );
}

function Header({ truckName, dockZone }: { truckName: string | null; dockZone: string | null }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold text-foreground">
        {truckName ? `${truckName} — today` : 'Your day'}
      </h1>
      <p className="text-subtle mt-1 flex items-center gap-2">
        {dockZone
          ? <><MapPin className="w-3.5 h-3.5" /> Dock {dockZone}</>
          : 'Your truck, crew and routes at a glance.'}
      </p>
    </div>
  );
}

function Card({
  title, icon: Icon, hint, to, navigate, children,
}: {
  title: string;
  icon: typeof Users;
  hint?: string;
  to: string;
  navigate: ReturnType<typeof useNavigate>;
  children: React.ReactNode;
}) {
  return (
    <div className="card flex flex-col">
      {/* The header is the drill-through. ManagementView's cards are dead ends —
          every summary here opens the page that owns the detail. */}
      <button
        onClick={() => navigate(to)}
        className="flex items-center justify-between mb-3 pb-2 border-b border-border text-left group"
      >
        <span className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">{title}</span>
        </span>
        <span className="flex items-center gap-1 text-xs text-muted-foreground group-hover:text-primary transition-colors">
          {hint}<ChevronRight className="w-3.5 h-3.5" />
        </span>
      </button>
      {children}
    </div>
  );
}

function Stat({ rows }: { rows: [string, number][] }) {
  return (
    <div className="space-y-1.5">
      {rows.map(([label, n]) => (
        <div key={label} className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">{label}</span>
          <span className="font-semibold text-foreground tabular-nums">{n}</span>
        </div>
      ))}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-xs text-muted-foreground py-2">{text}</p>;
}
