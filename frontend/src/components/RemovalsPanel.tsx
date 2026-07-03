import { useCallback, useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { RemovalsResponse, RemovalOut } from '../api/types';
import { PackageX, Printer, Loader2, CheckCircle2 } from 'lucide-react';

/**
 * Out-of-zone removals panel (ADR-176).
 *
 * These units are NOT the company's freight — they fall outside the company
 * zone, must be pulled off the truck at the station and returned to Amazon,
 * and are never transferred between trucks. Dispatch confirms each physical
 * pull here; the Returns Manifest print is the handback paper trail.
 */

function RemovalRow({ r, busy, onConfirm }: {
  r: RemovalOut; busy: boolean; onConfirm: (id: string) => void;
}) {
  const removed = r.status === 'removed';
  return (
    <tr className={`border-b border-border/40 last:border-0 ${removed ? 'opacity-60' : ''}`}>
      <td className="px-2 py-1.5 font-mono text-xs font-semibold text-foreground">{r.bag_id}</td>
      <td className="px-2 py-1.5 text-xs text-foreground">
        {r.whole_tote
          ? <span className="font-semibold">Whole tote</span>
          : <span className="font-mono">{r.tba}</span>}
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums text-xs text-foreground">{r.package_count}</td>
      <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">{r.locator ?? '—'}</td>
      <td className="px-2 py-1.5">
        {removed ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-success">
            <CheckCircle2 className="w-3.5 h-3.5" />
            removed{r.removed_by_name ? ` · ${r.removed_by_name}` : ''}
          </span>
        ) : (
          <button
            disabled={busy}
            onClick={() => onConfirm(r.id)}
            className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-danger text-white hover:bg-danger/90 disabled:opacity-50"
          >
            Confirm removed
          </button>
        )}
      </td>
    </tr>
  );
}

export default function RemovalsPanel({ date }: { date: string }) {
  const [data, setData] = useState<RemovalsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await axiosClient.get<RemovalsResponse>(`/sort/${date}/removals`);
      setData(res.data);
    } catch {
      setError('Could not load removals.');
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  const onConfirm = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await axiosClient.post<RemovalsResponse>(`/sort/removals/${id}/confirm`);
      setData(res.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Confirm failed — refresh and try again.');
    } finally {
      setBusy(false);
    }
  };

  if (!data || data.removals.length === 0) return null;

  const totalPkgs = data.removals.reduce((n, r) => n + r.package_count, 0);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <PackageX className="w-4 h-4 text-danger" />
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Out-of-zone removals — pull off the truck, return to Amazon
        </p>
        <div className="flex-1" />
        <a
          href={`/sort/returns-print?date=${date}`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <Printer className="w-3.5 h-3.5" /> Returns manifest
        </a>
      </div>

      <div className={`p-2.5 rounded-xl border text-xs ${
        data.flagged_count > 0
          ? 'bg-danger/5 border-danger/20 text-danger'
          : 'bg-success/5 border-success/20 text-success'
      }`}>
        {data.flagged_count > 0
          ? <>{data.flagged_count} unit{data.flagged_count === 1 ? '' : 's'} still on trucks — not our delivery area. These are removals, not transfers.</>
          : <>All {data.removed_count} out-of-zone unit{data.removed_count === 1 ? '' : 's'} pulled ({totalPkgs} packages) — ready for Amazon handback.</>}
      </div>

      {error && (
        <div className="p-2.5 text-xs text-danger bg-danger/5 border border-danger/20 rounded-xl">{error}</div>
      )}

      <div className="border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-accent/40 text-muted-foreground">
              <th className="px-2 py-1.5 text-left">Bag</th>
              <th className="px-2 py-1.5 text-left">Unit</th>
              <th className="px-2 py-1.5 text-right">Pkgs</th>
              <th className="px-2 py-1.5 text-left">Dock</th>
              <th className="px-2 py-1.5 text-left w-44">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.removals.map(r => (
              <RemovalRow key={r.id} r={r} busy={busy} onConfirm={onConfirm} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
