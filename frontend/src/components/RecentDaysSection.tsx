/**
 * Recent days — the per-day half of My Stats (ADR-268).
 *
 * Lives INSIDE MyPerformanceCard rather than on its own page. My Stats already
 * answers "how am I doing overall" from the same source (our DeliveryStop/RTS
 * data), and mobile's MyAccountScreen states the placement rule this follows:
 * tabs are split by WHO SAYS IT — you, us, Amazon — and things reading from one
 * source do not get split across surfaces.
 *
 * What this adds that the aggregate tiles cannot show:
 *   - which truck, and who was on it
 *   - the route's effort_class
 *   - therefore a DIFFICULTY-NORMALISED rate, where the tiles show raw counts
 *
 * That last point is the reason this exists. Raw RTS rate is confounded:
 * 2.10% on easy routes vs 10.81% on heavy ones, measured. The lifetime totals
 * above cannot correct for that; per-day, with effort_class in hand, we can.
 */
import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import { getLocalYMD } from '../utils/date';
import type {
  AssignmentDay, AssignmentHistoryResponse, HistoryRTSDetail,
} from '../api/types';
import { ChevronDown, ChevronUp, Truck, Users } from 'lucide-react';

const LOOKBACK_DAYS = 30;

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function prettyDate(iso: string): string {
  // Split and rebuild as LOCAL. `new Date('2026-08-07')` is midnight UTC and
  // renders as the 6th anywhere behind it.
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

function DayRow({ day }: { day: AssignmentDay }) {
  const [open, setOpen] = useState(false);
  const hasWork = day.packages_total > 0;
  const vs = day.rts_rate_vs_class;

  return (
    <div className="rounded-lg border border-border bg-background px-3 py-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-foreground">{prettyDate(day.route_date)}</span>
            {day.truck_name && (
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <Truck className="w-3 h-3" />{day.truck_name}
              </span>
            )}
            {day.effort_class && day.effort_class !== 'standard' && (
              /* Only exceptions earn a chip — 'standard' on every row is noise
                 that hides the heavy days. */
              <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                day.effort_class === 'heavy' ? 'bg-warning/15 text-warning' : 'bg-info/10 text-info'
              }`}>
                {day.effort_class}
              </span>
            )}
          </div>
          {day.crew.length > 0 && (
            <p className="flex items-center gap-1 text-[11px] text-muted-foreground mt-0.5">
              <Users className="w-3 h-3 shrink-0" />
              <span className="truncate">{day.crew.map(c => c.name).join(', ')}</span>
            </p>
          )}
        </div>

        {hasWork && (
          <div className="text-right shrink-0">
            <p className="text-sm font-semibold text-foreground leading-none">
              {day.packages_delivered}
              <span className="text-muted-foreground font-normal">/{day.packages_total}</span>
            </p>
            {/* WHOSE numbers these are. A walker's 142 and a driver's 2,865 are
                different measurements, and rendering them identically was the
                original bug (ADR-268). */}
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {day.counts_scope === 'truck' ? 'whole truck' : 'your stops'}
            </p>
            {vs !== null ? (
              /* The verdict. The raw rate alone would mark whoever drew the
                 heavy routes as worse; this is the comparison that is fair. */
              <p className={`text-[10px] mt-0.5 ${
                vs < 0.95 ? 'text-success' : vs > 1.15 ? 'text-warning' : 'text-muted-foreground'
              }`}>
                {vs.toFixed(2)}× typical
              </p>
            ) : day.rts_count > 0 && (
              <p className="text-[10px] text-muted-foreground mt-0.5">
                {day.rts_count} returned
              </p>
            )}
          </div>
        )}
      </div>

      {day.rts_details.length > 0 && (
        <>
          <button
            onClick={() => setOpen(o => !o)}
            className="mt-1.5 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {day.rts_details.length} came back
          </button>
          {open && (
            <div className="mt-1.5 space-y-1">
              {day.address_detail === 'block' && (
                /* The address is gone by POLICY (ADR-219), not by failure.
                   Without this the blank reads as lost data. */
                <p className="text-[10px] text-muted-foreground italic">
                  Street addresses are removed 48h after the route.
                </p>
              )}
              {day.rts_details.map(r => <RTSRow key={r.tba_number} r={r} />)}
            </div>
          )}
        </>
      )}

      {/* Supervised trainees (ADR-269). Rendered SEPARATELY and indented — the
          counts above are the trainer's own executed stops, these are the
          trainee's. Merging them is the ADR-244 attribution bug and makes both
          numbers unreadable.

          Kept field-for-field identical to the mobile RecentDaysSection: two
          hand-maintained renderers over one endpoint, so any change here lands
          there in the same commit. */}
      {(day.supervised ?? []).map(sup => (
        <div key={sup.employee_id} className="mt-2 pl-2 border-l-2 border-primary/60">
          <p className="text-xs font-semibold text-foreground">
            {sup.name}
            <span className="ml-1 font-normal text-[11px] text-muted-foreground">
              · you supervised
            </span>
          </p>
          <p className="text-[11px] text-muted-foreground mb-0.5">
            {sup.packages_delivered}/{sup.packages_total} delivered
            {sup.rts_count > 0 && ` · ${sup.rts_count} back`}
            {/* vs_class, not the raw rate: a trainee on a heavy route is not
                worse than one on an easy route at the same raw number. */}
            {sup.rts_rate_vs_class != null && ` · ${sup.rts_rate_vs_class}× typical`}
          </p>
          <div className="space-y-1">
            {sup.rts_details.map(r => <RTSRow key={r.tba_number} r={r} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

/** One returned package. Shared by a day's own RTS list and by the supervised
 *  block below it, so the two cannot present the same record differently. */
function RTSRow({ r }: { r: HistoryRTSDetail }) {
  return (
    <div className="text-[11px]">
      <p className="text-muted-foreground">
        <span className="text-foreground">{RTS_LABEL[r.rts_type] ?? r.rts_type}</span>
        {r.normalised_address && ` · ${r.normalised_address}`}
        {r.is_reattemptable && (
          <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-info/10 text-info uppercase tracking-wide">
            retryable
          </span>
        )}
      </p>
      {/* The walker's own words. rts_type is a dropdown value; this is what
          they actually wrote, and it is the part that explains the day to them
          a week later. */}
      {r.rts_explanation && (
        <p className="text-muted-foreground/80 italic">{r.rts_explanation}</p>
      )}
    </div>
  );
}

export default function RecentDaysSection() {
  const [days, setDays] = useState<AssignmentDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get<AssignmentHistoryResponse>('/assignment-history/me', {
      params: { start_date: daysAgo(LOOKBACK_DAYS), end_date: getLocalYMD() },
    })
      .then(({ data }) => setDays(data.days))
      .catch(e => setError(errorText(e, 'Could not load your recent days.')));
  }, []);

  // Silent on failure, matching MyPerformanceCard: a stats section must not
  // error the account page around it.
  if (error || !days || days.length === 0) return null;

  return (
    <div className="mt-4 pt-4 border-t border-border">
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-sm font-semibold text-foreground">Recent days</h3>
        <span className="text-[11px] text-muted-foreground">last {LOOKBACK_DAYS} days</span>
      </div>
      <div className="space-y-1.5">
        {days.map(d => <DayRow key={`${d.route_date}-${d.truck_name ?? ''}`} day={d} />)}
      </div>
    </div>
  );
}
