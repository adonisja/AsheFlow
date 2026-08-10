/**
 * My Assignments — what I worked, and how it went (ADR-268).
 *
 * Self-scoped: hits /assignment-history/me, which filters to the caller. There
 * is no employee picker here by design; reading someone else's history is a
 * dispatch action on a different endpoint.
 *
 * TWO THINGS THIS UI MUST NOT GET WRONG
 *
 * 1. RTS rate is confounded by route difficulty — 2.10% on easy routes vs
 *    10.81% on heavy ones, measured. Showing the raw rate as a judgement would
 *    tell someone who worked the hard routes that they did badly. So the raw
 *    number is context and `rts_rate_vs_class` is the verdict.
 *
 * 2. Addresses vanish after 48h by policy (ADR-219), not by failure. The UI
 *    says which mode it is in, so "no address" reads as "expired, by design"
 *    rather than "we lost it".
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import { getLocalYMD } from '../utils/date';
import type { AssignmentDay, AssignmentHistoryResponse } from '../api/types';
import {
  AlertCircle, CalendarDays, ChevronDown, ChevronUp, Package,
  RotateCcw, Truck, Users,
} from 'lucide-react';

/** Presets rather than a date picker: "how did last week go" is the question,
 *  and a two-field range form is friction for a phone-sized audience. */
const RANGES = [
  { key: '7',  label: 'Last 7 days',  days: 7 },
  { key: '30', label: 'Last 30 days', days: 30 },
  { key: '90', label: 'Last 90 days', days: 90 },
] as const;

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function prettyDate(iso: string): string {
  // Parsed as local, not UTC: `new Date('2026-08-07')` is midnight UTC, which
  // renders as the 6th in any timezone behind it.
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short',
  });
}

const RTS_LABEL: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Customer rescheduled',
  customer_cancelled_order: 'Customer cancelled',
};

/** How this day's RTS rate compares to others on routes of the SAME
 *  difficulty. Below 1.0 is better than typical. */
function VsClass({ value }: { value: number }) {
  const better = value < 0.95;
  const worse = value > 1.15;
  const tone = better ? 'text-success bg-success/10'
    : worse ? 'text-warning bg-warning/10'
    : 'text-subtle bg-muted';
  const word = better ? 'better than' : worse ? 'above' : 'about';
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-full ${tone}`}>
      {value.toFixed(2)}× — {word} typical for this difficulty
    </span>
  );
}

function DayCard({ day }: { day: AssignmentDay }) {
  const [open, setOpen] = useState(false);
  const delivered = day.packages_delivered;
  const total = day.packages_total;
  const pct = total ? Math.round((delivered / total) * 100) : null;

  return (
    <div className="card space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-semibold text-foreground">{prettyDate(day.route_date)}</p>
            {day.truck_name && (
              <span className="flex items-center gap-1 text-xs text-subtle">
                <Truck className="w-3 h-3" />{day.truck_name}
              </span>
            )}
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-subtle uppercase tracking-wide">
              {day.slot_role}
            </span>
            {day.effort_class && day.effort_class !== 'standard' && (
              /* Only the exceptions are worth a chip — 'standard' on every card
                 is noise that hides the heavy days. */
              <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                day.effort_class === 'heavy'
                  ? 'bg-warning/15 text-warning' : 'bg-info/10 text-info'
              }`}>
                {day.effort_class} route
              </span>
            )}
          </div>
          {day.route_numbers.length > 0 && (
            <p className="text-xs text-subtle mt-1">
              Route{day.route_numbers.length > 1 ? 's' : ''} {day.route_numbers.join(', ')}
              {day.stops_total > 0 && ` · ${day.stops_total} stops`}
            </p>
          )}
        </div>

        {total > 0 && (
          <div className="text-right shrink-0">
            <p className="text-lg font-semibold text-foreground leading-none">
              {delivered}<span className="text-subtle text-sm">/{total}</span>
            </p>
            <p className="text-[11px] text-subtle mt-0.5">{pct}% delivered</p>
          </div>
        )}
      </div>

      {total > 0 && (
        <div className="flex items-center gap-2 flex-wrap text-xs">
          <span className="flex items-center gap-1 text-subtle">
            <RotateCcw className="w-3 h-3" />
            {day.rts_count} returned
            {day.rts_rate !== null && ` (${(day.rts_rate * 100).toFixed(1)}%)`}
          </span>
          {day.rts_rate_vs_class !== null
            ? <VsClass value={day.rts_rate_vs_class} />
            : day.rts_count > 0 && (
              /* No baseline for this class yet. Saying so beats silently
                 omitting the comparison, which would read as "nothing to
                 report". */
              <span className="text-[11px] text-subtle">
                not enough company data to compare yet
              </span>
            )}
          {day.missing_count > 0 && (
            <span className="text-warning">{day.missing_count} missing</span>
          )}
        </div>
      )}

      {day.crew.length > 0 && (
        <div className="flex items-start gap-1.5 text-xs text-subtle">
          <Users className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{day.crew.map(c => c.name).join(', ')}</span>
        </div>
      )}

      {day.rts_details.length > 0 && (
        <div className="border-t border-border pt-2">
          <button
            onClick={() => setOpen(o => !o)}
            className="flex items-center gap-1.5 text-xs font-medium text-foreground hover:text-primary transition-colors"
          >
            <Package className="w-3.5 h-3.5" />
            {open ? 'Hide' : 'Show'} the {day.rts_details.length} package
            {day.rts_details.length > 1 ? 's' : ''} that came back
            {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

          {open && (
            <div className="mt-2 space-y-1.5">
              {day.address_detail === 'block' && (
                /* The address is gone by POLICY. Without this line the blank
                   looks like a data loss (ADR-219). */
                <p className="text-[11px] text-subtle italic">
                  Street addresses are removed 48 hours after the route — older
                  days show the reason only.
                </p>
              )}
              {day.rts_details.map(r => (
                <div key={r.tba_number} className="flex items-start justify-between gap-2 text-xs rounded-md bg-muted/40 px-2 py-1.5">
                  <div className="min-w-0">
                    <span className="font-medium text-foreground">
                      {RTS_LABEL[r.rts_type] ?? r.rts_type}
                    </span>
                    {r.normalised_address && (
                      <span className="text-subtle"> · {r.normalised_address}</span>
                    )}
                    <p className="text-subtle mt-0.5">{r.rts_explanation}</p>
                  </div>
                  {r.is_reattemptable && (
                    <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info uppercase tracking-wide">
                      retryable
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function MyAssignments() {
  const [rangeKey, setRangeKey] = useState<string>('30');
  const [data, setData] = useState<AssignmentHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (days: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<AssignmentHistoryResponse>(
        '/assignment-history/me',
        { params: { start_date: daysAgo(days), end_date: getLocalYMD() } },
      );
      setData(res.data);
    } catch (e) {
      setError(errorText(e, 'Could not load your assignment history.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const r = RANGES.find(x => x.key === rangeKey) ?? RANGES[1];
    load(r.days);
  }, [rangeKey, load]);

  const days = data?.days ?? [];
  const worked = days.filter(d => d.packages_total > 0);
  const totalPkgs = worked.reduce((n, d) => n + d.packages_total, 0);
  const totalDelivered = worked.reduce((n, d) => n + d.packages_delivered, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title flex items-center gap-2">
          <CalendarDays className="w-5 h-5 text-primary" />
          My Assignments
        </h1>
        <p className="text-sm text-subtle mt-1">
          The days you worked, who you rode with, and how each one went.
        </p>
      </div>

      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm w-fit">
        {RANGES.map(r => (
          <button
            key={r.key}
            onClick={() => setRangeKey(r.key)}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
              rangeKey === r.key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      {totalPkgs > 0 && (
        <div className="card flex items-center gap-6 flex-wrap">
          <div>
            <p className="text-xs text-subtle uppercase tracking-wider">Days worked</p>
            <p className="text-2xl font-bold text-foreground">{days.length}</p>
          </div>
          <div>
            <p className="text-xs text-subtle uppercase tracking-wider">Packages delivered</p>
            <p className="text-2xl font-bold text-foreground">
              {totalDelivered}
              <span className="text-sm text-subtle font-normal">/{totalPkgs}</span>
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="card border-danger/40 border flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-subtle">Loading…</p>
      ) : days.length === 0 ? (
        <div className="card text-center py-10">
          <p className="text-sm text-subtle">
            No assignments in this range.
          </p>
          <Link to="/my-route" className="text-sm text-primary hover:underline mt-2 inline-block">
            Go to today's route
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {days.map(d => <DayCard key={`${d.route_date}-${d.truck_name}`} day={d} />)}
        </div>
      )}
    </div>
  );
}
