import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import * as XLSX from 'xlsx';
import {
  ClipboardList, RefreshCw, Plus, Ban, Copy, Check, Upload, Lock, Trash2,
} from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { SkeletonCard } from '../../components/ui/Skeleton';
import ConfirmDialog from '../../components/ui/ConfirmDialog';
import { errorText } from '../../utils/errorText';
import {
  buildingTypeLabel, formatHours, workloadLabels,
} from '../../utils/addressProfile';
import type {
  CollectedProfile, CollectedWalkerDay, CollectedWalkerDayDetail,
  CollectionTokenCreated, CollectionTokenSummary,
} from '../../api/types';

/**
 * What came back from the public collection page (ADR-415 D6).
 *
 * ADR-415 built the submit endpoint and the tables; nothing could read them.
 * That is the same shape as ADR-340's incident — detection improved and the
 * noticing did not — so this is the reader.
 *
 * SUPER ADMIN ONLY, not platform staff. The rows are customer delivery
 * addresses, and ADR-343 D4 forbids any `platform_support` endpoint from
 * returning addresses: that login is cross-tenant, so PII behind it becomes a
 * cross-tenant PII surface. The gate is enforced server-side; this page simply
 * lives where only a super admin can reach it.
 *
 * Read plus issue/revoke, and no promotion. Nothing here moves a row into
 * `building_profiles` — the data is collected to be looked at, so the
 * quarantine table is the destination rather than a staging area (ADR-415 D6).
 */

const fmt = (iso: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
};

/** CSV escape: quote always, double interior quotes. Addresses carry commas and
 *  notes carry everything. */
const q = (v: unknown): string => `"${String(v ?? '').replace(/"/g, '""')}"`;

/** ADR-429: the EXPORT keeps stored values, deliberately.
 *
 *  The table humanises `loading_dock_mailroom` to "Loading dock: mailroom"
 *  because a person reads it. A CSV is read by a loader, and these column names
 *  already match `BuildingProfile` so a later import maps straight across —
 *  translating them would mean translating them back.
 *
 *  Display formats for people, wire formats for machines, and the same file
 *  cannot be both. */
const CSV_COLUMNS = [
  'normalised_address', 'building_category', 'building_type',
  'has_security_desk', 'workloads', 'workload_other', 'workload_class',
  'raw_note', 'opens_at', 'closes_at', 'break_start', 'break_end',
  'troublesome', 'collected_by', 'collected_on', 'submitted_at',
] as const;

/** One profile as a row, in CSV_COLUMNS order.
 *
 *  Column names match `BuildingProfile` so a later load maps straight across
 *  without a translation table. Extracted from `toCSV` so the CSV and the
 *  workbook are literally the same data rather than two lists that agree
 *  today. */
function profileRow(r: CollectedProfile): unknown[] {
  return [
    r.address, r.building_category, r.building_type,
    r.has_security_desk ? 'true' : 'false',
    // Pipe-separated, matching every other place workloads are written: a
    // comma inside a CSV cell survives the file and trips naive splitters.
    (r.workloads ?? []).join('|'), r.workload_other ?? '',
    r.workload_class, r.note ?? '',
    r.opens_at ?? '', r.closes_at ?? '', r.break_start ?? '', r.break_end ?? '',
    r.troublesome ? 'true' : 'false',
    r.collected_by ?? '', r.collected_on, r.submitted_at,
  ];
}

function toCSV(rows: CollectedProfile[]): string {
  return [
    CSV_COLUMNS.join(','),
    ...rows.map((r) => profileRow(r).map(q).join(',')),
  ].join('\n');
}

/** One row per ADDRESS on a route, not one per day.
 *
 *  The grain is deliberate: the comparison this data exists for is
 *  "which walker carried which address", so a row per day would need unpacking
 *  before it could be compared against the sort output. Day-level facts repeat
 *  down the rows, which is what makes the file joinable.
 */
const DAY_COLUMNS = [
  'walker_name', 'collected_on', 'arrival_time', 'departure_time',
  'route_id', 'route_start', 'route_end', 'difficulty',
  'bag_id', 'address', 'sort_zone', 'stop',
  'rts_count', 'ov_count', 'revision', 'submitted_at',
] as const;

/** Every day flattened to one row per address, in DAY_COLUMNS order. */
function dayRows(rows: CollectedWalkerDayDetail[]): unknown[][] {
  const out: unknown[][] = [];
  for (const d of rows) {
    for (const r of d.payload.routes ?? []) {
      const rts = r.rts?.length ?? 0;
      const ovs = r.ovs?.length ?? 0;
      // A route with no totes still gets a row: it happened, and dropping it
      // would make the route count in this file disagree with the listing.
      const totes = r.totes?.length ? r.totes : [{ bag_id: '', addresses: [] as string[] }];
      for (const t of totes) {
        const addrs = t.addresses?.length ? t.addresses : [''];
        for (const a of addrs) {
          out.push([
            d.walker_name, d.collected_on, d.arrival_time ?? '', d.departure_time ?? '',
            r.route_id, r.route_start, r.route_end, r.difficulty,
            t.bag_id, a,
            ('sort_zone' in t ? t.sort_zone : '') ?? '', ('stop' in t ? t.stop : '') ?? '',
            rts, ovs, d.revision, d.submitted_at,
          ]);
        }
      }
    }
  }
  return out;
}

function daysToCSV(rows: CollectedWalkerDayDetail[]): string {
  return [
    DAY_COLUMNS.join(','),
    ...dayRows(rows).map((r) => r.map(q).join(',')),
  ].join('\n');
}

/** Turns a header and rows into a one-sheet workbook.
 *
 *  Shared by both datasets so the xlsx and the CSV cannot drift: each caller
 *  passes the SAME column list and the SAME row builder it gives `toCSV`, and
 *  only the container differs.
 */
function sheetBlob(name: string, header: readonly string[], rows: unknown[][]): Blob {
  const ws = XLSX.utils.aoa_to_sheet([[...header], ...rows]);
  ws['!cols'] = header.map((h) => ({ wch: Math.max(12, Math.min(40, h.length + 6)) }));
  if (rows.length > 0) {
    ws['!autofilter'] = {
      ref: XLSX.utils.encode_range({
        s: { r: 0, c: 0 }, e: { r: rows.length, c: header.length - 1 },
      }),
    };
  }
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, name);
  const out = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer;
  return new Blob([out], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}

export default function CollectionData({ platform = true }: {
  /** Whose view this is (ADR-423).
   *
   *  ONE component for both, because the endpoints already scope themselves:
   *  a super admin's reads return everything, a company admin's return only
   *  their own company's rows, and create_token decides the scope from the
   *  caller. Duplicating the page would duplicate the campaign list, the
   *  drill-down, three export formats and the token controls in order to change
   *  a heading — and the duplicate would drift.
   *
   *  What this flag changes is only what the page SAYS, not what it can do.
   *  The gate is server-side; this is copy. */
  platform?: boolean;
}) {
  const [tokens, setTokens] = useState<CollectionTokenSummary[]>([]);
  const [profiles, setProfiles] = useState<CollectedProfile[]>([]);
  const [activeToken, setActiveToken] = useState<string | null>(null);
  /** Which dataset is on screen. The two campaigns collect different things —
   *  addresses describe a door, days describe a shift — so they get two views
   *  rather than one merged table whose columns are half empty either way. */
  const [dataset, setDataset] = useState<'addresses' | 'days'>('addresses');
  const [days, setDays] = useState<CollectedWalkerDay[]>([]);
  /** The expanded day, fetched on demand. The listing carries counts only. */
  const [openDay, setOpenDay] = useState<CollectedWalkerDayDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingRows, setLoadingRows] = useState(false);
  const [error, setError] = useState('');

  // The freshly-created secret. Held in component state ONLY, never refetched:
  // the backend returns it once, so once this page is left it is unrecoverable
  // and a new campaign must be issued.
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);
  const [label, setLabel] = useState('');
  // Both are enforced server-side and were unreachable from any client until
  // these existed — the ADR-381 shape: a live backend capability with no
  // surface. `expiresInDays` empty means no expiry, which is the schema's own
  // default (Optional, None).
  const [dailyCap, setDailyCap] = useState('500');
  const [expiresInDays, setExpiresInDays] = useState('');

  const loadTokens = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axiosClient.get<CollectionTokenSummary[]>('/collection/tokens');
      setTokens(data);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not load collection campaigns.'));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProfiles = useCallback(async (tokenId: string | null) => {
    setLoadingRows(true);
    try {
      const { data } = await axiosClient.get<CollectedProfile[]>('/collection/profiles', {
        params: tokenId ? { token_id: tokenId, limit: 1000 } : { limit: 1000 },
      });
      setProfiles(data);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not load collected addresses.'));
    } finally {
      setLoadingRows(false);
    }
  }, []);

  const loadDays = useCallback(async (tokenId: string | null) => {
    setLoadingRows(true);
    try {
      const { data } = await axiosClient.get<CollectedWalkerDay[]>('/collection/walker-days', {
        params: tokenId ? { token_id: tokenId, limit: 1000 } : { limit: 1000 },
      });
      setDays(data);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not load collected days.'));
    } finally {
      setLoadingRows(false);
    }
  }, []);

  /** One day in full. Fetched on expand rather than with the listing: forty
   *  days with every tote and address inline is a large response for a table
   *  that only shows counts. */
  const expandDay = useCallback(async (id: string) => {
    if (openDay?.id === id) { setOpenDay(null); return; }
    try {
      const { data } = await axiosClient.get<CollectedWalkerDayDetail>(
        `/collection/walker-days/${id}`);
      setOpenDay(data);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not load that day.'));
    }
  }, [openDay]);

  useEffect(() => { void loadTokens(); }, [loadTokens]);
  useEffect(() => {
    // Only the visible dataset is fetched. Loading both on every campaign
    // click would double the traffic to show one table.
    if (dataset === 'addresses') void loadProfiles(activeToken);
    else void loadDays(activeToken);
  }, [activeToken, dataset, loadProfiles, loadDays]);

  const createToken = async () => {
    if (!label.trim()) { setError('Give the campaign a name first.'); return; }
    setCreating(true);
    try {
      const cap = Number(dailyCap);
      if (!Number.isInteger(cap) || cap < 1 || cap > 5000) {
        setError('Daily cap must be a whole number between 1 and 5000.');
        setCreating(false);
        return;
      }
      const days = expiresInDays.trim() === '' ? null : Number(expiresInDays);
      if (days !== null && (!Number.isInteger(days) || days < 1 || days > 365)) {
        setError('Expiry must be a whole number of days between 1 and 365.');
        setCreating(false);
        return;
      }
      const { data } = await axiosClient.post<CollectionTokenCreated>('/collection/tokens', {
        label: label.trim(),
        daily_cap: cap,
        // Omitted entirely rather than sent as null: the schema is extra="forbid"
        // and treats an absent key as "no expiry".
        ...(days !== null ? { expires_in_days: days } : {}),
      });
      // SELECT the new campaign rather than holding its token in state. The
      // link then appears on its own row in the sidebar — same "copy it now"
      // moment the old banner gave, attached to the campaign it belongs to and
      // still there tomorrow (ADR-424).
      setLabel('');
      setExpiresInDays('');
      await loadTokens();
      setActiveToken(data.id);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not create the collection link.'));
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (t: CollectionTokenSummary) => {
    if (!window.confirm(`Revoke "${t.label}"? Submissions stop immediately.`)) return;
    try {
      await axiosClient.post(`/collection/tokens/${t.id}/revoke`);
      await loadTokens();
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not revoke that link.'));
    }
  };

  /** The row queued for deletion, or null. ADR-431.
   *
   *  Holding the ROW rather than an id so the dialog can name the address.
   *  That is the whole safety mechanism here: the realistic mistake is
   *  deleting the wrong row, and only the address catches it. */
  const [toDelete, setToDelete] = useState<CollectedProfile | null>(null);
  const [deleting, setDeleting] = useState(false);

  /** Remove one observation, permanently (ADR-431 D2).
   *
   *  No optimistic removal and no undo toast, which is the usual modern
   *  default: there is nothing to roll back to. The row is gone server-side
   *  before the list reloads, so showing it as gone early would only
   *  mis-report a failure. The refetch is the confirmation. */
  const confirmDelete = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await axiosClient.delete(`/collection/profiles/${toDelete.id}`);
      setToDelete(null);
      // Reload the CURRENT campaign, not all of them: loadProfiles(null)
      // silently widens the table to every campaign after a delete.
      await loadProfiles(activeToken);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not delete that address.'));
      setToDelete(null);
    } finally {
      setDeleting(false);
    }
  };

  /** Hands the bytes to the browser. Takes a Blob rather than a string so the
   *  same path serves text formats and the xlsx binary. */
  const save = (name: string, ext: string, blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}-${new Date().toISOString().slice(0, 10)}.${ext}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const text = (body: string, type: string) => new Blob([body], { type });

  const [downloading, setDownloading] = useState(false);

  /** THE export surface for collected data.
   *
   *  The collection pages have none: their data goes to the server, and a
   *  second copy leaving on a collector's phone would be the record without
   *  the access control. Everything anyone needs to take away is taken from
   *  here, behind the super-admin gate.
   *
   *  Three formats for each dataset, carrying the same rows and columns — only
   *  the container differs, so a recipient given one file is not given less
   *  than a recipient given another. */
  const download = async (fmt: 'csv' | 'json' | 'xlsx') => {
    if (dataset === 'addresses') {
      if (fmt === 'xlsx') {
        save('collected-addresses', 'xlsx', sheetBlob('Address profiles', CSV_COLUMNS, profiles.map(profileRow)));
      } else if (fmt === 'json') {
        save('collected-addresses', 'json',
          text(JSON.stringify({ profiles }, null, 2), 'application/json'));
      } else {
        save('collected-addresses', 'csv', text(toCSV(profiles), 'text/csv'));
      }
      return;
    }
    // The day export is one row per ADDRESS, so it needs every payload — and
    // the listing deliberately carries none. Fetched here, on an explicit
    // export, rather than eagerly on every page load: this is the one moment
    // the cost buys something.
    setDownloading(true);
    try {
      const full = await Promise.all(days.map((d) =>
        axiosClient.get<CollectedWalkerDayDetail>(`/collection/walker-days/${d.id}`)
          .then((r) => r.data)));
      if (fmt === 'xlsx') {
        save('collected-walker-days', 'xlsx', sheetBlob('Walker days', DAY_COLUMNS, dayRows(full)));
      } else if (fmt === 'json') {
        save('collected-walker-days', 'json',
          text(JSON.stringify({ days: full }, null, 2), 'application/json'));
      } else {
        save('collected-walker-days', 'csv', text(daysToCSV(full), 'text/csv'));
      }
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not build the day export.'));
    } finally {
      setDownloading(false);
    }
  };

  /** The selected campaign, or null on "All campaigns". Carries the link, so
   *  the row below can show it (ADR-424). */
  const selected = useMemo(
    () => tokens.find((t) => t.id === activeToken) ?? null,
    [tokens, activeToken],
  );
  const activeLabel = selected?.label;


  return (
    <div className="space-y-6">
      <SectionHeader
        eyebrow={platform ? 'Platform' : 'Survey'}
        title={platform ? 'Collected addresses' : 'Building survey'}
        description={platform
          ? 'Building profiles and logged days from every campaign, open and company. Read-only; nothing here changes routing.'
          : 'Building profiles your staff have collected. A link you issue here works only for signed-in employees of your company.'}
        actions={
          <button
            onClick={() => { void loadTokens(); void loadProfiles(activeToken); }}
            className="btn-secondary text-sm inline-flex items-center gap-1.5"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      <ErrorBanner message={error || null} />

      {/* The secret, shown once. Deliberately loud: leaving this page loses it,
          and the only recovery is issuing a new campaign. */}
      {/* ADR-424. NO floating "copy it now" banner.
          
          It sat at the top of the page, detached from the campaign it belonged
          to — with one campaign in the list it read as a page-level notice
          rather than THAT campaign's link, and with several it would have been
          ambiguous. The link now lives on its own row, where it is
          unambiguous and can be re-copied any time. */}

      <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)] items-start [&>*]:min-w-0">
        {/* ── Campaigns ────────────────────────────────────────────────── */}
        <aside className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
            <ClipboardList className="w-4 h-4" /> Campaigns
          </h2>

          <div className="flex gap-2">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void createToken(); }}
              placeholder="New campaign name"
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
            <button
              onClick={() => void createToken()}
              disabled={creating || !label.trim()}
              className="btn-primary shrink-0 px-3 disabled:opacity-40"
              title="Issue a collection link"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="block text-[11px] text-muted-foreground">Daily cap</span>
              <input
                type="number" min={1} max={5000} inputMode="numeric"
                value={dailyCap}
                onChange={(e) => setDailyCap(e.target.value)}
                className="mt-0.5 w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </label>
            <label className="block">
              <span className="block text-[11px] text-muted-foreground">Expires (days)</span>
              <input
                type="number" min={1} max={365} inputMode="numeric"
                value={expiresInDays}
                onChange={(e) => setExpiresInDays(e.target.value)}
                placeholder="never"
                className="mt-0.5 w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </label>
          </div>

          {loading ? (
            <SkeletonCard />
          ) : tokens.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No campaigns yet. Name one above to get a collection link.
            </p>
          ) : (
            <ul className="space-y-1">
              <li>
                <button
                  onClick={() => setActiveToken(null)}
                  className={`w-full rounded-lg px-2 py-1.5 text-left text-sm ${
                    activeToken === null ? 'bg-muted font-medium' : 'hover:bg-muted'
                  }`}
                >
                  All campaigns
                </button>
              </li>
              {tokens.map((t) => {
                const dead = t.revoked_at !== null;
                return (
                  <li key={t.id} className="group flex items-center gap-1">
                    <button
                      onClick={() => setActiveToken(t.id)}
                      className={`min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left text-sm ${
                        activeToken === t.id ? 'bg-muted font-medium' : 'hover:bg-muted'
                      }`}
                    >
                      <span className={`block truncate ${dead ? 'line-through opacity-60' : ''}`}>
                        {t.label}
                      </span>
                      <span className="block text-[11px] text-muted-foreground">
                        {/* Two different units, so never shown as a ratio:
                            submission_count is the campaign's LIFETIME total,
                            daily_cap is a per-day ceiling checked against a
                            same-day count the listing does not return. */}
                        {/* ADR-423. Which auth model this campaign uses, said
                            plainly: "open link" means the link IS the
                            credential and anyone holding it can submit, which
                            is a different thing to hand out than a company
                            link that also requires signing in. */}
                        <span className={t.scope === 'open' ? 'text-warning' : ''}>
                          {t.scope === 'open' ? 'open link' : 'company only'}
                        </span>
                        {' · '}
                        {t.submission_count} total · cap {t.daily_cap}/day
                        {dead && ' · revoked'}
                        {!dead && t.expires_at && ` · expires ${new Date(t.expires_at).toLocaleDateString()}`}
                        {t.created_by_name && ` · ${t.created_by_name}`}
                      </span>
                    </button>
                    {!dead && (
                      <button
                        onClick={() => void revoke(t)}
                        title="Revoke. Submissions stop immediately."
                        className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 hover:bg-danger/10 hover:text-danger focus:opacity-100 group-hover:opacity-100"
                      >
                        <Ban className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {/* The selected campaign's LINK, under the list and unambiguous about
              which campaign it belongs to (ADR-424). Shown for the selected
              campaign only: three links stacked in a sidebar is three chances
              to send the wrong one. */}
          {selected?.token && (
            <div className="rounded-lg border border-border bg-surface/60 p-2.5 space-y-1.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Link for {selected.label}
              </p>
              <div className="flex items-center gap-1.5">
                <code className="min-w-0 flex-1 truncate rounded-md border border-border bg-card px-2 py-1.5 font-mono text-[11px]">
                  {selected.token}
                </code>
                <button
                  onClick={() => {
                    void navigator.clipboard.writeText(selected.token ?? '');
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }}
                  className="btn-secondary shrink-0 px-2 py-1.5 text-xs inline-flex items-center gap-1"
                >
                  {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {selected.scope === 'open'
                  ? 'Anyone with this link can submit. Give it to collectors.'
                  : 'Only signed-in employees of your company can use this link.'}
              </p>
            </div>
          )}
        </aside>

        {/* ── Rows ─────────────────────────────────────────────────────── */}
        <section className="card p-4 space-y-3">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-sm font-semibold">
                {activeLabel ?? 'All campaigns'}
              </h2>
              <p className="text-[11px] text-muted-foreground">
                {dataset === 'addresses'
                  ? `${profiles.length} address${profiles.length === 1 ? '' : 'es'} collected`
                  : `${days.length} walker day${days.length === 1 ? '' : 's'} collected`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {/* Two datasets, two views. Addresses describe a door and days
                  describe a shift, so one merged table would be half empty
                  whichever row you were looking at. */}
              <div className="flex rounded-lg bg-muted p-0.5 text-sm">
                {(['addresses', 'days'] as const).map((k) => (
                  <button
                    key={k}
                    onClick={() => { setDataset(k); setOpenDay(null); }}
                    className={`rounded-md px-2.5 py-1 ${
                      dataset === k ? 'bg-card shadow-sm font-medium' : 'text-muted-foreground'
                    }`}
                  >
                    {k === 'addresses' ? 'Addresses' : 'Days'}
                  </button>
                ))}
              </div>
              {/* THE export surface. The collection pages have none — their
                  data goes to the server, and a copy leaving on a collector's
                  phone would be the record without the access control. */}
              {((dataset === 'addresses' && profiles.length > 0)
                || (dataset === 'days' && days.length > 0)) && (
                <div className="flex items-center gap-1">
                  {(['csv', 'json', 'xlsx'] as const).map((fmt) => (
                    <button
                      key={fmt}
                      onClick={() => void download(fmt)}
                      disabled={downloading}
                      className="btn-secondary text-sm inline-flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {/* Upload, not Download. lucide's Download arrow points
                          INTO a tray (receiving) and Upload points OUT of it
                          (sending) — so an EXPORT takes Upload. The walker log
                          fixed this same inversion; this page reintroduced it.
                          One convention, both pages. */}
                      <Upload className={`w-4 h-4 ${downloading ? 'animate-pulse' : ''}`} />
                      {fmt === 'xlsx' ? 'Excel' : fmt.toUpperCase()}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {loadingRows ? (
            <SkeletonCard />
          ) : dataset === 'days' ? (
            days.length === 0 ? (
              <p className="text-sm text-muted-foreground">No days submitted yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3 font-semibold">Walker</th>
                      <th className="py-2 pr-3 font-semibold">Date</th>
                      <th className="py-2 pr-3 font-semibold">Shift</th>
                      <th className="py-2 pr-3 font-semibold">Routes</th>
                      <th className="py-2 pr-3 font-semibold">Totes</th>
                      <th className="py-2 pr-3 font-semibold">RTS</th>
                      <th className="py-2 font-semibold">Submitted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {days.map((d) => (
                      <Fragment key={d.id}>
                        <tr
                          onClick={() => void expandDay(d.id)}
                          className="cursor-pointer border-b border-border/50 align-top hover:bg-muted/50"
                        >
                          <td className="py-2 pr-3 font-medium">{d.walker_name}</td>
                          <td className="py-2 pr-3 whitespace-nowrap">{d.collected_on}</td>
                          <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                            {d.arrival_time || '—'}–{d.departure_time || '—'}
                          </td>
                          <td className="py-2 pr-3">{d.route_count}</td>
                          <td className="py-2 pr-3">{d.tote_count}</td>
                          <td className="py-2 pr-3">{d.rts_count}</td>
                          <td className="py-2 whitespace-nowrap text-muted-foreground">
                            {fmt(d.submitted_at)}
                            {/* A revision above 1 means the day was re-sent.
                                Worth showing: it separates a corrected day
                                from a first submission without a diff. */}
                            {d.revision > 1 && (
                              <span className="ml-1 rounded bg-muted px-1 text-[10px]">
                                rev {d.revision}
                              </span>
                            )}
                          </td>
                        </tr>
                        {openDay?.id === d.id && (
                          <tr className="border-b border-border/50 bg-muted/30">
                            <td colSpan={7} className="px-3 py-3">
                              <div className="space-y-3">
                                {(openDay.payload.routes ?? []).map((r) => (
                                  <div key={r.route_id} className="rounded-lg border border-border bg-card p-2.5">
                                    <p className="text-xs font-semibold">
                                      Route {r.route_id}
                                      <span className="ml-2 font-normal text-muted-foreground">
                                        {r.route_start || '—'}–{r.route_end || '—'}
                                        {/* Route times are stored HH:MM, so
                                            they need no reformatting — only
                                            the difficulty reads as a raw
                                            value. */}
                                        {r.difficulty && (
                                          <> · {r.difficulty[0].toUpperCase() + r.difficulty.slice(1)}</>
                                        )}
                                      </span>
                                    </p>
                                    {r.notes && (
                                      <p className="mt-1 text-[11px] text-muted-foreground">{r.notes}</p>
                                    )}
                                    {(r.totes ?? []).map((t, i) => (
                                      <div key={`${t.bag_id}-${i}`} className="mt-1.5 text-[11px]">
                                        <span className="font-medium">{t.bag_id || '(no bag id)'}</span>
                                        {t.stop && <span className="text-muted-foreground"> · {t.stop}</span>}
                                        {t.addresses?.length > 0 && (
                                          <span className="text-muted-foreground">
                                            {' — '}{t.addresses.join('; ')}
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                    {(r.rts ?? []).length > 0 && (
                                      <p className="mt-1.5 text-[11px] text-warning">
                                        RTS: {r.rts.map((x) => `${x.tba || '?'} (${x.code || '?'})`).join(', ')}
                                      </p>
                                    )}
                                    {(r.ovs ?? []).length > 0 && (
                                      <p className="mt-1 text-[11px] text-muted-foreground">
                                        OVs: {r.ovs.map((o) => `${o.ov_id || '?'}${o.size ? ` ${o.size}` : ''}`).join(', ')}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : profiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing submitted yet.
            </p>
          ) : (
            /* Scrolls inside its own container — a wide table must never make
               the page scroll sideways. */
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3 font-semibold">Address</th>
                    <th className="py-2 pr-3 font-semibold">Type</th>
                    <th className="py-2 pr-3 font-semibold">Workload</th>
                    <th className="py-2 pr-3 font-semibold">Hours</th>
                    <th className="py-2 pr-3 font-semibold">By</th>
                    <th className="py-2 pr-3 font-semibold">Collected</th>
                    {/* No header text: an icon-only action column reads as
                        chrome, and "Actions" would be the widest thing in a
                        column holding one 12px button. */}
                    <th className="py-2 font-semibold"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {/* ADR-430. Rows that describe ONE door, marked.
                      
                      Two observations close a door to new collectors
                      (ADR-420), and the flat table gave the reader no way to
                      tell — a verified door and a door still wanting a second
                      look were identical rows. The count is computed from
                      door_key rather than fetched: the listing already carries
                      every row it is counting. */}
                  {profiles.map((p) => {
                    // Server-computed (ADR-430). Counting matching door_keys in
                    // `profiles` would be wrong the moment a campaign exceeds
                    // one page: a pair split across the boundary would read as
                    // two single observations, and the count would be right
                    // only for small campaigns.
                    const closed = p.closed;
                    return (
                    <tr key={p.id} className="border-b border-border/50 align-top">
                      <td className="py-2 pr-3">
                        <span className="flex items-center gap-1.5">
                          <span>{p.address}</span>
                          {/* A lock, not a colour: "closed" is a state of the
                              door, not a warning about the row, and colouring
                              the whole line would compete with `troublesome`
                              which genuinely is a warning. */}
                          {closed && (
                            <Lock
                              className="h-3 w-3 shrink-0 text-muted-foreground"
                              aria-label="Closed to new observations"
                            />
                          )}
                        </span>
                        {p.note && (
                          <span className="block text-[11px] text-muted-foreground">{p.note}</span>
                        )}
                        {p.troublesome && (
                          <span className="mt-0.5 inline-block rounded bg-warning/15 px-1.5 py-0.5 text-[10px] text-warning">
                            troublesome
                          </span>
                        )}
                      </td>
                      {/* ADR-429. LABELS, not stored values. The collector
                          chose "Loading dock: mailroom" from a list; showing
                          the admin `loading_dock_mailroom` back is the wire
                          format leaking into a reading surface.
                          buildingTypeLabel has existed since ADR-422 and this
                          page never called it. */}
                      <td className="py-2 pr-3">
                        <span className="block whitespace-nowrap">
                          {buildingTypeLabel(p.building_type)}
                        </span>
                        {/* The flag was collected and never displayed. It
                            changes what a walker must carry, which makes it
                            one of the more consequential things on the row. */}
                        {p.has_security_desk && (
                          <span className="mt-0.5 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            security desk
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {/* The collected SET, not workload_class — that column
                            is a single derived default (ADR-418), so showing it
                            here hid the second and third things the collector
                            actually ticked. */}
                        <span className="block">
                          {workloadLabels(p.workloads) || '—'}
                        </span>
                        {p.workload_other && (
                          <span className="block text-[11px] text-muted-foreground">
                            {p.workload_other}
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                        {formatHours(p.opens_at, p.closes_at) || '—'}
                        {(p.break_start || p.break_end) && (
                          <span className="block text-[11px]">
                            closed {formatHours(p.break_start, p.break_end)}
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                        {p.collected_by ?? '—'}
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                        {p.collected_on}
                        <span className="block text-[11px]">{fmt(p.submitted_at)}</span>
                        {/* Which of the door's observations this row is. Says
                            "1 of 2" rather than just "closed", so a reader can
                            see the pair rather than two unrelated rows. */}
                        <span className="mt-0.5 block text-[10px]">
                          {closed
                            ? `closed · ${p.observations} observations`
                            : 'open · 1 more wanted'}
                        </span>
                      </td>
                      {/* ADR-431. Delete, and deliberately no edit beside it:
                          this table records what collectors actually
                          submitted, and an admin retyping a value would make
                          the row a claim about two people while still reading
                          as one. A wrong value is fixed by the collector
                          resubmitting (ADR-426).

                          Quiet by default and red only on hover. UX Movement:
                          reserve red for the confirmation itself — a row of
                          permanently red buttons in a table draws the eye to
                          the one action nobody should take casually. */}
                      <td className="py-2 text-right">
                        <button
                          type="button"
                          onClick={() => setToDelete(p)}
                          disabled={deleting}
                          title="Delete this observation"
                          aria-label={`Delete the observation for ${p.address}`}
                          className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger focus:outline-none focus:ring-2 focus:ring-danger/40 disabled:opacity-50"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* NAMES THE ADDRESS, and says plainly that it cannot be undone.
          ADR-431 D2 rejected a typed confirmation ("type DELETE"): NN/g
          reserves that for the most dangerous and RARE actions, and removing a
          test submission from a 30-day survey is neither — the friction would
          be trained away on exactly the person who deletes most. The address is
          what catches the real error. */}
      <ConfirmDialog
        open={toDelete !== null}
        variant="danger"
        title="Delete this observation?"
        message={
          toDelete
            ? `${toDelete.address}, collected by ${toDelete.collected_by ?? 'an anonymous collector'}`
              + ` on ${toDelete.collected_on}. This cannot be undone, and field work cannot be re-walked.`
            : ''
        }
        confirmLabel="Delete it"
        cancelLabel="Keep it"
        onConfirm={confirmDelete}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}
