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
import React, { useCallback, useEffect, useState } from 'react';
import {
  Search, Package, MapPin, Truck, AlertTriangle, CheckCircle2, Clock, User,
  Copy, Check, History, X,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import { SkeletonCard } from '../components/ui/Skeleton';
import type { PackageLookupResponse, PackageTimeline, FieldAddedResponse } from '../api/types';
import { shortDate } from '../utils/metric';
import { Link } from 'react-router-dom';

const MIN_CHARS = 4;
const RECENT_KEY = 'asheflow.packageLookup.recent';
const RECENT_MAX = 6;

/** Recent lookups, newest first.
 *
 * Dispatch fields several calls in a row and was re-typing full TBAs each time.
 * Stored per-browser rather than server-side: it is a convenience, not a record,
 * and a TBA is not something worth persisting to the account.
 *
 * Guarded because localStorage throws in private mode on some browsers, and a
 * search page should not fail to render over a convenience feature.
 */
function loadRecent(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function saveRecent(list: string[]) {
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch {
    /* private mode — recents are best-effort */
  }
}

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
  const [recent, setRecent] = useState<string[]>([]);

  /* Today's field-added packages, shown when there is nothing else on screen.
     The page used to open as a title and one input — no indication of what a
     result contains, and nothing to act on if you did not already have a TBA
     in hand. These are exactly the packages most likely to be asked about:
     added from the field today, so not on the original manifest.

     Reuses the endpoint behind Field Packages' "Added today" tab — no new
     backend, and the two views cannot disagree. */
  const [fieldAdded, setFieldAdded] = useState<FieldAddedResponse | null>(null);

  useEffect(() => {
    let alive = true;
    axiosClient
      .get<FieldAddedResponse>('/packages/intake/field-added')
      .then(r => { if (alive) setFieldAdded(r.data); })
      .catch(() => { /* a starting point is a convenience — never block search */ });
    return () => { alive = false; };
  }, []);

  useEffect(() => { setRecent(loadRecent()); }, []);

  /** Runs a lookup. Takes the term explicitly so a recent chip can trigger it
   *  without waiting for the input's state to settle. */
  const runSearch = useCallback(async (term: string) => {
    const q = term.trim();
    if (q.length < MIN_CHARS) return;
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<PackageLookupResponse>(
        `/packages/lookup?tba=${encodeURIComponent(q)}`,
      );
      setData(res.data);
      // Only remember searches that found something — a typo is not worth
      // offering back as a suggestion.
      if (res.data.matched_on !== 'none') {
        setRecent(prev => {
          const next = [q, ...prev.filter(r => r !== q)].slice(0, RECENT_MAX);
          saveRecent(next);
          return next;
        });
      }
    } catch (err) {
      const e2 = err as { response?: { data?: { detail?: string } } };
      setError(e2.response?.data?.detail ?? 'Lookup failed.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const search = (e: React.FormEvent) => {
    e.preventDefault();
    runSearch(tba);
  };

  const clearRecent = () => { setRecent([]); saveRecent([]); };

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

      {/* The minimum was enforced but never stated: below 4 characters the
          button simply went dead with no reason given. A suffix search on
          fewer characters would match half the depot, so the rule is real —
          it just has to be visible while someone is typing. */}
      {tba.trim().length > 0 && tba.trim().length < MIN_CHARS && (
        <p className="text-xs text-subtle">
          {MIN_CHARS - tba.trim().length} more character
          {MIN_CHARS - tba.trim().length === 1 ? '' : 's'} — a shorter suffix would
          match too many packages to be useful.
        </p>
      )}

      {/* Recent lookups — dispatch fields several calls in a row, and a TBA is
          long enough that re-typing it is a real cost. */}
      {recent.length > 0 && !loading && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-subtle flex items-center gap-1">
            <History className="w-3 h-3" /> Recent
          </span>
          {recent.map(r => (
            <button
              key={r}
              onClick={() => { setTba(r); runSearch(r); }}
              className="text-xs font-mono px-2 py-1 rounded-lg bg-accent/40 text-foreground hover:bg-accent transition-colors"
            >
              …{r.slice(-8)}
            </button>
          ))}
          <button
            onClick={clearRecent}
            className="text-xs text-subtle hover:text-foreground flex items-center gap-0.5"
            aria-label="Clear recent lookups"
          >
            <X className="w-3 h-3" /> Clear
          </button>
        </div>
      )}

      <ErrorBanner message={error} />

      {/* Skeleton rather than an empty region: on a slow lookup the page
          previously looked broken while the button said "Searching…". */}
      {loading && (
        <div className="space-y-3">
          <SkeletonCard className="h-40" />
        </div>
      )}

      {/* Starting point: today's field-added packages. Only while nothing else
          is on screen — once a search runs, the result is the subject. These are
          the packages most likely to be asked about, since they were added from
          the field today and are not on the original manifest. */}
      {!loading && !data && !error && (fieldAdded?.packages?.length ?? 0) > 0 && (
        <div className="card">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-sm font-semibold">Added from the field today</h2>
            <span className="text-xs text-subtle">{fieldAdded!.total} package
              {fieldAdded!.total === 1 ? '' : 's'}</span>
          </div>
          <ul className="divide-y divide-border">
            {fieldAdded!.packages.slice(0, 8).map(pkg => (
              <li key={pkg.tba}>
                <button
                  type="button"
                  onClick={() => { setTba(pkg.tba); void runSearch(pkg.tba); }}
                  className="w-full text-left py-2 flex items-center gap-3 hover:bg-accent rounded-md px-2 -mx-2"
                >
                  <span className="font-mono text-xs">{pkg.tba}</span>
                  <span className="text-xs text-muted-foreground truncate">
                    {pkg.route_number != null ? `Route ${pkg.route_number}` : 'no route'}
                    {pkg.walker_name ? ` · ${pkg.walker_name}` : ''}
                  </span>
                  <span className="text-xs text-subtle ml-auto shrink-0">
                    added by {pkg.added_by_name ?? 'unknown'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Nothing field-added today is the COMMON case early in a shift, and the
          page would otherwise fall back to a bare input — the very thing the
          starting point exists to avoid. Say what the page does instead. */}
      {!loading && !data && !error && (fieldAdded?.packages?.length ?? 0) === 0 && (
        <div className="card flex flex-col items-center justify-center py-10 gap-2 text-center">
          <Package className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Search a tracking number to see who is holding a package.
          </p>
          <p className="text-xs text-subtle max-w-md">
            The full TBA or its last {MIN_CHARS}+ characters both work. Packages added
            from the field today will appear here as a starting point.
          </p>
        </div>
      )}
      {!loading && data && data.matched_on === 'none' && (
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
      {!loading && data?.ambiguous && (
        <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg bg-warning/10 border border-warning/30 text-warning text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {(data.results ?? []).length} packages end with “{data.query}”. Enter more
            characters to narrow it.
          </span>
        </div>
      )}

      {!loading && (data?.results ?? []).map(pkg => (
        <TimelineCard key={pkg.tba_number} pkg={pkg} />
      ))}
    </div>
  );
}

function TimelineCard({ pkg }: { pkg: PackageTimeline }) {
  const hasException = (pkg.exceptions?.length ?? 0) > 0;
  const [copied, setCopied] = useState(false);

  /** Copy the TBA — the operator is usually pasting it into Amazon's portal or
   *  a message to the walker, and re-reading 15 characters off screen invites
   *  transcription errors. */
  const copyTba = async () => {
    try {
      await navigator.clipboard.writeText(pkg.tba_number);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (insecure context) — the number is still on screen */
    }
  };

  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <button
            onClick={copyTba}
            className="font-mono text-sm text-foreground break-all hover:text-primary transition-colors flex items-center gap-1.5 text-left"
            title="Copy tracking number"
          >
            {pkg.tba_number}
            {copied
              ? <Check className="w-3.5 h-3.5 text-success shrink-0" />
              : <Copy className="w-3.5 h-3.5 text-muted-foreground shrink-0" />}
          </button>
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

      {/* Actions. Deliberately NOT deep-linking to a walker: neither
          /walker-performance nor /incidents reads a URL param today, so a link
          would land on the page without selecting anyone — worse than no link.
          Revisit if those pages gain param support. */}
      {pkg.current_holder_name && (
        <div className="flex items-center gap-2 flex-wrap pt-1">
          <Link
            to="/crew-status"
            className="text-xs text-primary hover:underline"
          >
            Crew status →
          </Link>
          {hasException && (
            <Link to="/incidents" className="text-xs text-primary hover:underline">
              Incidents →
            </Link>
          )}
        </div>
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
