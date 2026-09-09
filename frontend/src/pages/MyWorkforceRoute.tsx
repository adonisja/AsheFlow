import { useCallback, useEffect, useState } from 'react';
import { Navigation, RefreshCw, Package, Clock } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';
import { errorText } from '../utils/errorText';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import type { MyRouteOut } from '../api/types';

/** The walker's own route in workforce mode (ADR-297, ADR-406).
 *
 *  A separate page from `/my-route`, which is full mode's and gated on
 *  `route_sort`. ADR-297 D1 made the same call for the endpoint: workforce mode
 *  gets its own rather than a mode-branch inside a screen built for stops. The
 *  data genuinely differs — the unit of work is the TOTE, not the stop — so a
 *  shared page would spend its time hiding half of itself.
 *
 *  Until this existed, a workforce walker had no web view of their route at
 *  all, which matters because ADR-402 D4 records that no app is shipped: the
 *  browser is the field surface.
 */
export default function MyWorkforceRoute() {
  const { hasFeature } = useAuth();
  const [date] = useState(getLocalYMD());
  const [data, setData] = useState<MyRouteOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axiosClient.get<MyRouteOut>(`/workforce/my-route/${date}`);
      setData(res.data);
      setError('');
    } catch (e: unknown) {
      setError(errorText(e, 'Could not load your route.'));
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  if (!hasFeature('workforce_sort')) {
    return (
      <div className="card p-6 text-sm text-muted-foreground">
        This company works from an Amazon package feed. Your route is under My
        Route.
      </div>
    );
  }

  const reserved = data?.reserved_routes ?? [];

  return (
    <div className="space-y-6 animate-slide-up">
      <SectionHeader
        eyebrow="Workforce"
        title={<span className="flex items-center gap-2"><Navigation className="w-5 h-5" /> My Route</span>}
        description="The totes you are carrying and the blocks they cover"
        actions={
          <button className="btn-ghost flex items-center gap-2" onClick={load}>
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      <ErrorBanner message={error || null} />

      {loading ? (
        <div className="card p-6 text-sm text-muted-foreground">Loading…</div>
      ) : !data || data.no_route_assigned ? (
        <>
          <div className="card p-6 text-sm text-muted-foreground">
            No route yet. Your captain will assign one.
          </div>
          {/* A walker with no CURRENT route can still hold a reserved one — it
              becomes theirs to start the moment the captain hands it over. */}
          {reserved.length > 0 && <ReservedList routes={reserved} />}
        </>
      ) : (
        <>
          <div className="card p-4 space-y-3">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold">Route {data.route_number}</span>
                <span className="text-xs text-muted-foreground">{data.truck_name}</span>
              </div>
              <span className={`px-2 py-0.5 rounded-lg text-[11px] font-medium capitalize ${
                data.status === 'in_progress' ? 'bg-primary/10 text-primary'
                : 'bg-warning/10 text-warning'
              }`}>
                {data.status === 'in_progress' ? 'Out' : 'Ready'}
              </span>
            </div>

            {data.departed_at && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground tabular-nums">
                <Clock className="w-3.5 h-3.5" />
                Out since {new Date(data.departed_at).toLocaleTimeString([], {
                  hour: '2-digit', minute: '2-digit',
                })}
              </div>
            )}

            {/* ADR-297 D5: flex_package_count is THE count. package_count is
                absent from this payload entirely, so it cannot be shown by
                accident. Null means nobody has scanned yet, which is not zero. */}
            {data.flex_package_count !== null && (
              <div className="text-sm">
                {data.flex_package_count} {data.flex_package_count === 1 ? 'package' : 'packages'}
              </div>
            )}
          </div>

          {/* ADR-297 D3: the TOTE is the unit of work. A walker picks up totes,
              not stops, so this is the list they actually work from. */}
          <div className="card p-4">
            <div className="text-sm font-medium mb-3">
              {data.totes.length} {data.totes.length === 1 ? 'tote' : 'totes'}
            </div>
            <div className="space-y-2">
              {data.totes.map(t => (
                <div key={t.bag_id} className="flex items-start gap-3">
                  <span
                    className="w-6 h-6 rounded-full border border-border shrink-0 mt-0.5"
                    style={{ background: t.bag_color ?? 'transparent' }}
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <div className="font-medium">{t.bag_id}</div>
                    <div className="text-xs text-muted-foreground">
                      {t.block_description ?? t.bag_color_name ?? ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {reserved.length > 0 && <ReservedList routes={reserved} />}
        </>
      )}
    </div>
  );
}

/** ADR-406 D2. A route with this walker's name on it, waiting.
 *
 *  Deliberately offers NO start action. The depart endpoint refuses a route
 *  that is not `assigned`, so a button here could only ever produce a 409 — and
 *  the sequencing is the captain's to control.
 *
 *  The operator's reason for showing it at all is not convenience: a reserved
 *  route is a commitment with a name on it, and seen rather than unseen it is
 *  the difference between "there is more work" and "route 7 is yours".
 */
function ReservedList({ routes }: { routes: { route_id: string; route_number: number; tote_count: number; block_keys: string[] }[] }) {
  return (
    <div className="card p-4">
      <div className="text-sm font-medium mb-1">Reserved for you</div>
      <p className="text-xs text-muted-foreground mb-3">
        Yours to take once you close the route you are on.
      </p>
      <div className="space-y-3">
        {routes.map(r => (
          <div key={r.route_id} className="rounded-lg border border-border p-3">
            <div className="flex items-center gap-2">
              <Package className="w-4 h-4 text-muted-foreground shrink-0" />
              <span className="font-medium">Route {r.route_number}</span>
              <span className="text-xs text-muted-foreground">
                {r.tote_count} {r.tote_count === 1 ? 'tote' : 'totes'}
              </span>
            </div>
            {r.block_keys.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {r.block_keys.map(b => (
                  <span key={b} className="px-1.5 py-0.5 rounded bg-accent text-[11px] text-muted-foreground">
                    {b.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
