/**
 * Package lookup — find who has a package from its TBA (ADR-245).
 *
 * Dispatch's actual question is "a customer is asking about TBA…447, who has
 * it?". Every other package read is route-scoped, so answering it meant already
 * knowing the route — backwards.
 *
 * Shows the whole timeline rather than just a name, because the follow-up
 * question is always "and what happened to it": assigned to a route, a stop
 * started or completed, and any RTS/missing/damaged record.
 *
 * Gated dispatch + management + admin, matching the backend. This is
 * operational tracking, distinct from the Tier 3 appeal-evidence search.
 */
import React, { useState } from 'react';
import {
  Search, Package, MapPin, Truck, AlertTriangle, CheckCircle2, Clock, User,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import type { PackageLookupResponse, PackageTimeline } from '../api/types';
import { shortDate } from '../utils/metric';

const MIN_CHARS = 4;

/** Where the holder answer came from — shown so a stale "assigned" is not read
 *  as a confirmed delivery. */
const BASIS_LABEL: Record<string, string> = {
  delivered:   'delivered by',
  in_progress: 'currently with',
  assigned:    'assigned to',
  exception:   'last handled by',
};

export default function PackageLookup() {
  const [tba, setTba] = useState('');
  const [data, setData] = useState<PackageLookupResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = tba.trim();
    if (q.length < MIN_CHARS) return;
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<PackageLookupResponse>(
        `/packages/lookup?tba=${encodeURIComponent(q)}`,
      );
      setData(res.data);
    } catch (err) {
      const e2 = err as { response?: { data?: { detail?: string } } };
      setError(e2.response?.data?.detail ?? 'Lookup failed.');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-slide-up">
      <div>
        <h1 className="page-title flex items-center gap-2">
          <Package className="w-5 h-5 text-primary" /> Package Lookup
        </h1>
        <p className="text-subtle mt-1">
          Find who has a package from its tracking number.
        </p>
      </div>

      <form onSubmit={search} className="card flex items-center gap-2">
        <Search className="w-4 h-4 text-muted-foreground shrink-0" />
        <input
          value={tba}
          onChange={e => setTba(e.target.value)}
          placeholder="Full TBA, or the last 4+ characters"
          className="flex-1 bg-transparent text-sm outline-none"
          aria-label="Tracking number"
        />
        <button
          type="submit"
          disabled={loading || tba.trim().length < MIN_CHARS}
          className="btn-primary text-sm disabled:opacity-40"
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </form>

      <ErrorBanner message={error} />

      {data && data.matched_on === 'none' && (
        <div className="card flex flex-col items-center justify-center py-12 gap-2 text-center">
          <Package className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No record of <span className="font-mono">{data.query}</span>.
          </p>
          <p className="text-xs text-subtle max-w-md">
            The package may not have been manifested to a route yet, or the
            number may belong to another station.
          </p>
        </div>
      )}

      {/* A suffix hitting several packages is reported, never silently narrowed
          — picking one for the operator would be a guess about which customer
          they are on the phone with. */}
      {data?.ambiguous && (
        <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg bg-warning/10 border border-warning/30 text-warning text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {(data.results ?? []).length} packages end with “{data.query}”. Enter more
            characters to narrow it.
          </span>
        </div>
      )}

      {(data?.results ?? []).map(pkg => <TimelineCard key={pkg.tba_number} pkg={pkg} />)}
    </div>
  );
}

function TimelineCard({ pkg }: { pkg: PackageTimeline }) {
  const hasException = (pkg.exceptions?.length ?? 0) > 0;

  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="font-mono text-sm text-foreground break-all">{pkg.tba_number}</p>
          {pkg.current_holder_name ? (
            <p className="text-lg font-bold text-foreground mt-1 flex items-center gap-1.5">
              <User className="w-4 h-4 text-primary shrink-0" />
              {pkg.current_holder_name}
              <span className="text-xs font-normal text-subtle">
                · {BASIS_LABEL[pkg.holder_basis ?? ''] ?? pkg.holder_basis}
              </span>
            </p>
          ) : (
            <p className="text-sm text-subtle mt-1">No holder on record.</p>
          )}
        </div>
        {hasException && (
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full border bg-danger/10 text-danger border-danger/20 shrink-0">
            {pkg.exceptions!.length} exception{pkg.exceptions!.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {(pkg.assignments?.length ?? 0) > 0 && (
        <Section icon={Truck} title="Assigned">
          {pkg.assignments!.map((a, i) => (
            <Row
              key={i}
              main={`${a.walker_name ?? 'Unassigned'}${a.truck_name ? ` · ${a.truck_name}` : ''}`}
              meta={`Route ${a.route_number ?? '—'} · ${a.route_date}${a.route_status ? ` · ${a.route_status}` : ''}`}
            />
          ))}
        </Section>
      )}

      {(pkg.deliveries?.length ?? 0) > 0 && (
        <Section icon={MapPin} title="Stops">
          {pkg.deliveries!.map((d, i) => (
            <Row
              key={i}
              icon={d.status === 'completed' ? CheckCircle2 : Clock}
              tone={d.status === 'completed' ? 'text-success' : 'text-warning'}
              main={d.walker_name ?? 'Unknown walker'}
              meta={[
                d.status,
                d.completed_at ? `completed ${shortDate(d.completed_at)}` : null,
                // Only shown when it differs — during supervision or peer
                // coverage the completer is not the stop's walker (ADR-244).
                d.recorded_by_name && d.recorded_by_name !== d.walker_name
                  ? `recorded by ${d.recorded_by_name}` : null,
              ].filter(Boolean).join(' · ')}
            />
          ))}
        </Section>
      )}

      {hasException && (
        <Section icon={AlertTriangle} title="Exceptions" tone="text-danger">
          {pkg.exceptions!.map((x, i) => (
            <Row
              key={i}
              main={`${x.source.toUpperCase()}${x.rts_type ? ` · ${x.rts_type.replace(/_/g, ' ')}` : ''}${x.damage_stage ? ` · ${x.damage_stage.replace(/_/g, ' ')}` : ''}`}
              meta={[
                x.walker_name ?? x.recorded_by_name,
                x.recorded_at ? shortDate(x.recorded_at) : null,
                x.resolution_status,
                x.rts_explanation || x.notes,
              ].filter(Boolean).join(' · ')}
            />
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({
  icon: Icon, title, tone = 'text-muted-foreground', children,
}: {
  icon: React.ElementType;
  title: string;
  tone?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className={`text-xs uppercase tracking-wider mb-1.5 flex items-center gap-1 ${tone}`}>
        <Icon className="w-3 h-3" /> {title}
      </p>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({
  main, meta, icon: Icon, tone,
}: {
  main: string;
  meta?: string;
  icon?: React.ElementType;
  tone?: string;
}) {
  return (
    <div className="flex items-start gap-2 p-2 rounded-lg bg-accent/20">
      {Icon && <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${tone ?? ''}`} />}
      <div className="min-w-0">
        <p className="text-sm text-foreground">{main}</p>
        {meta && <p className="text-xs text-subtle">{meta}</p>}
      </div>
    </div>
  );
}
