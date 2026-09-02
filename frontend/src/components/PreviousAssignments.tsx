/**
 * Previous Assignments — what a past day actually ran (ADR-268).
 *
 * The read-only counterpart to the live board. The date picker lives HERE and
 * nowhere else: every write on the current board (publish, finalize, assign,
 * swap, remove) is keyed to the selected date, so a shared picker let a
 * dispatcher publish crews against a day that had already happened. Splitting
 * the surfaces removes that by construction rather than by disabling controls.
 *
 * Day summary first, trucks beneath: "how was the day" is the question a
 * dispatcher opens this with, and the per-truck detail is what they drill into
 * after seeing a number they do not like.
 */
import { useCallback, useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import { getLocalYMD } from '../utils/date';
import type { DayReplay, ReplayTruckOutcome } from '../api/types';
import {
  AlertCircle, ChevronDown, ChevronUp, Package, RotateCcw, Truck, Users,
} from 'lucide-react';

const RTS_LABEL: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Customer rescheduled',
  customer_cancelled_order: 'Customer cancelled',
};

function yesterday(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function pct(n: number, d: number): number | null {
  return d > 0 ? Math.round((n / d) * 1000) / 10 : null;
}

function TruckCard({ truck }: { truck: ReplayTruckOutcome }) {
  const [openCrew, setOpenCrew] = useState(false);
  const [openReasons, setOpenReasons] = useState(false);
  const ran = truck.packages_total > 0;
  const rate = pct(truck.rts_count, truck.packages_total);
  const reasons = Object.entries(truck.rts_reasons).sort((a, b) => b[1] - a[1]);

  return (
    <div className="card space-y-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Truck className="w-4 h-4 text-primary shrink-0" />
            <span className="font-semibold text-foreground">{truck.truck_name ?? 'Unnamed truck'}</span>
            {truck.effort_class && truck.effort_class !== 'standard' && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                truck.effort_class === 'heavy' ? 'bg-warning/15 text-warning' : 'bg-info/10 text-info'
              }`}>
                {truck.effort_class}
              </span>
            )}
          </div>
          <p className="text-xs text-subtle mt-0.5">
            {truck.route_numbers.length > 0
              ? `Route${truck.route_numbers.length > 1 ? 's' : ''} ${truck.route_numbers.join(', ')} · ${truck.stops_total} stops`
              : 'No routes ran'}
            {truck.crew.length > 0 && ` · ${truck.crew.length} crew`}
          </p>
        </div>

        {ran && (
          <div className="text-right shrink-0">
            <p className="text-lg font-semibold text-foreground leading-none">
              {truck.packages_delivered}
              <span className="text-subtle text-sm font-normal">/{truck.packages_total}</span>
            </p>
            <p className="text-[11px] text-subtle mt-0.5">
              {truck.rts_count} returned{rate !== null && ` (${rate}%)`}
            </p>
          </div>
        )}
      </div>

      {reasons.length > 0 && (
        <div className="border-t border-border pt-2">
          <button
            onClick={() => setOpenReasons(o => !o)}
            className="flex items-center gap-1.5 text-xs font-medium text-foreground hover:text-primary transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Why {truck.rts_count} came back
            {openReasons ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          {openReasons && (
            <div className="mt-1.5 space-y-1">
              {reasons.map(([type, n]) => (
                <div key={type} className="flex items-center justify-between text-xs">
                  <span className="text-subtle">{RTS_LABEL[type] ?? type}</span>
                  <span className="text-foreground font-medium">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {truck.crew.length > 0 && (
        <div className="border-t border-border pt-2">
          <button
            onClick={() => setOpenCrew(o => !o)}
            className="flex items-center gap-1.5 text-xs font-medium text-foreground hover:text-primary transition-colors"
          >
            <Users className="w-3.5 h-3.5" />
            Crew ({truck.crew.length})
            {openCrew ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          {openCrew && (
            <div className="mt-1.5 space-y-1">
              {truck.crew.map(m => (
                <div key={m.employee_id} className="flex items-center justify-between gap-2 text-xs rounded-md bg-muted/40 px-2 py-1">
                  <span className="flex items-center gap-1.5 min-w-0">
                    <span className="text-foreground truncate">{m.name}</span>
                    <span className="text-[10px] px-1 py-0.5 rounded bg-muted text-subtle uppercase tracking-wide shrink-0">
                      {m.slot_role}
                    </span>
                  </span>
                  <span className="shrink-0 text-subtle">
                    {m.packages_delivered}/{m.packages_total}
                    {m.rts_count > 0 && ` · ${m.rts_count} RTS`}
                    {m.is_truck_lead && (
                      /* Their line IS the truck's load. Unlabelled, this row
                         reads as one person who delivered 30x everyone else. */
                      <span className="ml-1 text-[10px] text-info">whole truck</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function PreviousAssignments() {
  const [day, setDay] = useState<string>(yesterday());
  const [data, setData] = useState<DayReplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<DayReplay>(`/assignment-history/day/${d}`);
      setData(res.data);
    } catch (e) {
      setError(errorText(e, 'Could not load that day.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(day); }, [day, load]);

  const ranTrucks = data?.trucks.filter(t => t.packages_total > 0) ?? [];
  const idleTrucks = data?.trucks.filter(t => t.packages_total === 0) ?? [];
  const dayRate = data ? pct(data.rts_count, data.packages_total) : null;
  const deliveredPct = data ? pct(data.packages_delivered, data.packages_total) : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <input
          type="date"
          value={day}
          max={getLocalYMD()}
          onChange={(e) => setDay(e.target.value)}
          className="rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm focus:border-primary focus:ring-1 focus:ring-primary outline-none"
        />
        <span className="text-xs text-subtle">Read-only. This day has already run.</span>
      </div>

      {error && (
        <div className="card border-danger/40 border flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-subtle">Loading…</p>
      ) : !data || data.trucks.length === 0 ? (
        <div className="card text-center py-10">
          <p className="text-sm text-subtle">No dispatch ran on this date.</p>
        </div>
      ) : (
        <>
          {/* Day summary first — "how was the day" is what this is opened with. */}
          <div className="card">
            <div className="flex items-center gap-6 flex-wrap">
              <div>
                <p className="text-xs text-subtle uppercase tracking-wider">Delivered</p>
                <p className="text-2xl font-bold text-foreground">
                  {data.packages_delivered}
                  <span className="text-sm text-subtle font-normal">/{data.packages_total}</span>
                </p>
                {deliveredPct !== null && (
                  <p className="text-[11px] text-subtle">{deliveredPct}% of the load</p>
                )}
              </div>
              <div>
                <p className="text-xs text-subtle uppercase tracking-wider">Returned</p>
                <p className="text-2xl font-bold text-foreground">{data.rts_count}</p>
                {dayRate !== null && <p className="text-[11px] text-subtle">{dayRate}% RTS</p>}
              </div>
              <div>
                <p className="text-xs text-subtle uppercase tracking-wider">Trucks out</p>
                <p className="text-2xl font-bold text-foreground">
                  {ranTrucks.length}
                  <span className="text-sm text-subtle font-normal">/{data.trucks.length}</span>
                </p>
              </div>
              {data.missing_count > 0 && (
                <div>
                  <p className="text-xs text-subtle uppercase tracking-wider">Missing</p>
                  <p className="text-2xl font-bold text-warning">{data.missing_count}</p>
                </div>
              )}
            </div>
          </div>

          {ranTrucks.map(t => <TruckCard key={t.truck_id} truck={t} />)}

          {idleTrucks.length > 0 && (
            /* Rostered but never ran. Worth showing rather than hiding — a
               truck with a crew and no routes is a question, not an absence. */
            <div className="card">
              <p className="text-xs text-subtle uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                <Package className="w-3.5 h-3.5" />
                No routes ran ({idleTrucks.length})
              </p>
              <p className="text-sm text-subtle">
                {idleTrucks.map(t => t.truck_name ?? 'Unnamed').join(', ')}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}