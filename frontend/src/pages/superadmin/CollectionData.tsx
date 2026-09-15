import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ClipboardList, RefreshCw, Plus, Ban, Copy, Check, Download, AlertTriangle,
} from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { SkeletonCard } from '../../components/ui/Skeleton';
import { errorText } from '../../utils/errorText';
import type {
  CollectedProfile, CollectionTokenCreated, CollectionTokenSummary,
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

const CSV_COLUMNS = [
  'normalised_address', 'building_type', 'workload_class', 'raw_note',
  'opens_at', 'closes_at', 'break_start', 'break_end',
  'troublesome', 'collected_by', 'collected_on', 'submitted_at',
] as const;

/** Column names match `BuildingProfile` so a later load maps straight across
 *  without a translation table — the same shape the collection page exports. */
function toCSV(rows: CollectedProfile[]): string {
  const out = [CSV_COLUMNS.join(',')];
  for (const r of rows) {
    out.push([
      r.address, r.building_type, r.workload_class, r.note ?? '',
      r.opens_at ?? '', r.closes_at ?? '', r.break_start ?? '', r.break_end ?? '',
      r.troublesome ? 'true' : 'false',
      r.collected_by ?? '', r.collected_on, r.submitted_at,
    ].map(q).join(','));
  }
  return out.join('\n');
}

export default function CollectionData() {
  const [tokens, setTokens] = useState<CollectionTokenSummary[]>([]);
  const [profiles, setProfiles] = useState<CollectedProfile[]>([]);
  const [activeToken, setActiveToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingRows, setLoadingRows] = useState(false);
  const [error, setError] = useState('');

  // The freshly-created secret. Held in component state ONLY, never refetched:
  // the backend returns it once, so once this page is left it is unrecoverable
  // and a new campaign must be issued.
  const [newToken, setNewToken] = useState<CollectionTokenCreated | null>(null);
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

  useEffect(() => { void loadTokens(); }, [loadTokens]);
  useEffect(() => { void loadProfiles(activeToken); }, [activeToken, loadProfiles]);

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
      setNewToken(data);
      setLabel('');
      setExpiresInDays('');
      await loadTokens();
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

  const download = () => {
    const blob = new Blob([toCSV(profiles)], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `collected-addresses-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const activeLabel = useMemo(
    () => tokens.find((t) => t.id === activeToken)?.label,
    [tokens, activeToken],
  );

  // Narrowed once, above the JSX: `token` is Optional on the wire, and a `!`
  // inside the guard would keep compiling if the guard were ever loosened.
  const secret = newToken?.token ?? null;

  return (
    <div className="space-y-6">
      <SectionHeader
        eyebrow="Platform"
        title="Collected addresses"
        description="Building profiles submitted from the public collection page. Read-only; nothing here changes routing."
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
      {secret !== null && (
        <div className="rounded-xl border border-warning/50 bg-warning/10 p-4 space-y-2">
          <p className="inline-flex items-center gap-1.5 text-sm font-semibold text-warning">
            <AlertTriangle className="w-4 h-4" />
            Copy this link now. It is not shown again.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded-lg border border-border bg-card px-3 py-2 font-mono text-xs">
              {secret}
            </code>
            <button
              onClick={() => {
                void navigator.clipboard.writeText(secret);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="btn-secondary text-sm inline-flex items-center gap-1.5"
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button onClick={() => setNewToken(null)} className="btn-secondary text-sm">
              Done
            </button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Give this to collectors. They paste it into the Addresses tab on the
            collection page.
          </p>
        </div>
      )}

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
        </aside>

        {/* ── Rows ─────────────────────────────────────────────────────── */}
        <section className="card p-4 space-y-3">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-sm font-semibold">
                {activeLabel ?? 'All campaigns'}
              </h2>
              <p className="text-[11px] text-muted-foreground">
                {profiles.length} address{profiles.length === 1 ? '' : 'es'} collected
              </p>
            </div>
            {profiles.length > 0 && (
              <button onClick={download} className="btn-secondary text-sm inline-flex items-center gap-1.5">
                <Download className="w-4 h-4" /> CSV
              </button>
            )}
          </div>

          {loadingRows ? (
            <SkeletonCard />
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
                    <th className="py-2 font-semibold">Collected</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((p) => (
                    <tr key={p.id} className="border-b border-border/50 align-top">
                      <td className="py-2 pr-3">
                        <span className="block">{p.address}</span>
                        {p.note && (
                          <span className="block text-[11px] text-muted-foreground">{p.note}</span>
                        )}
                        {p.troublesome && (
                          <span className="mt-0.5 inline-block rounded bg-warning/15 px-1.5 py-0.5 text-[10px] text-warning">
                            troublesome
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap">{p.building_type}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">{p.workload_class}</td>
                      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                        {p.opens_at ? `${p.opens_at}–${p.closes_at ?? '?'}` : '—'}
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                        {p.collected_by ?? '—'}
                      </td>
                      <td className="py-2 whitespace-nowrap text-muted-foreground">
                        {p.collected_on}
                        <span className="block text-[11px]">{fmt(p.submitted_at)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
