/**
 * ADR-277 D3 — the buildings on MY truck today.
 *
 * Sits alongside the company-wide /building-profiles queue rather than
 * replacing it: dispatch clears a backlog across the company, a captain works
 * the truck in front of them.
 *
 * Three groups, in the order a captain works them. The third — addresses this
 * truck visited with no profile at all — is the point of the page. It turns a
 * review queue into a collection prompt, which is what makes captains the
 * walking banks for this data rather than reviewers of other people's notes.
 */
import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import { SkeletonCard } from '../components/ui/Skeleton';
import { errorText } from '../utils/errorText';
import type { TruckBuildingsResponse, TruckBuildingStop } from '../api/types';

const BUILDING_TYPE_LABELS: Record<string, string> = {
  mailroom: 'Mail room',
  receptionist: 'Receptionist',
  doorman: 'Doorman',
  walkup: 'Walk-up',
  elevator: 'Elevator',
  biz_front: 'Business — front desk',
  biz_freight: 'Business — freight',
  biz_security: 'Business — security',
  biz_loading_dock: 'Business — loading dock',
};

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/** An address the ADR-219 purge has already nulled. The stop still counts —
 *  block_key survives — but there is no address left to show. */
function addressLabel(stop: TruckBuildingStop): string {
  return stop.normalised_address ?? `${stop.block_key} (address expired)`;
}

function StopRow({ stop }: { stop: TruckBuildingStop }) {
  const p = stop.profile;
  const rejected = p?.address_status === 'rejected';

  return (
    <li className="flex items-start justify-between gap-3 py-2.5 border-b border-border last:border-0">
      <div className="min-w-0">
        <div className="text-sm font-medium truncate">{addressLabel(stop)}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span>{stop.block_key}</span>
          {stop.stop_count > 1 && (
            <>
              <span aria-hidden>·</span>
              {/* Why this is shown: a building this truck hits six times a week
                  is worth profiling before one it hit once. */}
              <span>{stop.stop_count} visits</span>
            </>
          )}
          {p && (
            <>
              <span aria-hidden>·</span>
              <span>{BUILDING_TYPE_LABELS[p.building_type] ?? p.building_type}</span>
            </>
          )}
        </div>

        {/* ADR-277 D3: operational_note only. raw_note is unreviewed walker
            free text and the one field that might carry a person's name. */}
        {p?.operational_note && (
          <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{p.operational_note}</p>
        )}

        {rejected && (
          <p className="mt-1 text-xs text-warning">
            Address not found{p?.geo_message ? `: ${p.geo_message}` : ''}. Edit it to retry.
          </p>
        )}
      </div>

      <div className="shrink-0 text-right">
        {p ? (
          <>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {p.building_type_status}
            </div>
            {/* ADR-276 D6: remaining weight, not a raw count — "1 of 2" does
                not tell a captain whether THEIR tap finishes it. */}
            {typeof p.remaining_weight === 'number' && p.remaining_weight > 0 && (
              <div className="mt-0.5 text-[10px] text-muted-foreground">
                {p.remaining_weight === 1 ? '1 more needed' : `${p.remaining_weight} more needed`}
              </div>
            )}
          </>
        ) : (
          <Link
            to="/building-profiles"
            className="text-xs font-medium text-primary hover:underline"
          >
            Add profile
          </Link>
        )}
      </div>
    </li>
  );
}

function Group({
  title,
  subtitle,
  stops,
  emptyText,
  tone,
}: {
  title: string;
  subtitle: string;
  stops: TruckBuildingStop[];
  emptyText: string;
  tone: 'primary' | 'muted';
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span
          className={`text-xs font-semibold ${
            tone === 'primary' && stops.length > 0 ? 'text-primary' : 'text-muted-foreground'
          }`}
        >
          {stops.length}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>

      {stops.length === 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">{emptyText}</p>
      ) : (
        <ul className="mt-2">
          {stops.map((s) => (
            <StopRow key={s.normalised_address ?? `${s.block_key}-${s.stop_count}`} stop={s} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default function TruckBuildings() {
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState<TruckBuildingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<TruckBuildingsResponse>(
        `/building-profiles/for-truck/${date}`,
      );
      setData(res.data);
    } catch (e) {
      setError(errorText(e, 'Could not load buildings for this truck.'));
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <SectionHeader
        title="Buildings on my truck"
        description="What your crew is walking into today, and what nobody has told us yet."
      />

      <div className="flex items-center gap-2">
        <label htmlFor="truck-buildings-date" className="text-xs text-muted-foreground">
          Date
        </label>
        <input
          id="truck-buildings-date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1 text-sm"
        />
        {data?.truck_name && (
          <span className="text-xs text-muted-foreground">Truck {data.truck_name}</span>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <SkeletonCard />
      ) : !data ? null : data.no_truck_assigned ? (
        /* Not an error, and deliberately not three empty lists — those would
           read as "every building on your route is profiled". */
        <div className="rounded-lg border border-border bg-card p-6 text-center">
          <p className="text-sm font-medium">No truck assigned for this date</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Pick a date you were crewed on, or use the{' '}
            <Link to="/building-profiles" className="text-primary hover:underline">
              company-wide list
            </Link>
            .
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <Group
            tone="primary"
            title="Needs your sign-off"
            subtitle="The field agreed. One route lead confirms it."
            stops={data.needs_signoff}
            emptyText="Nothing waiting on you."
          />
          <Group
            tone="muted"
            title="No profile yet"
            subtitle="Your truck delivered here and nobody has recorded what it is like."
            stops={data.no_profile}
            emptyText="Every address on this truck has a profile."
          />
          <Group
            tone="muted"
            title="Known"
            subtitle="Verified intelligence your crew can rely on."
            stops={data.known}
            emptyText="Nothing verified for this truck yet."
          />
        </div>
      )}
    </div>
  );
}
