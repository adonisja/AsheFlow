import { useCallback, useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { RemovalsResponse } from '../api/types';
import { PackageX, CheckCircle2 } from 'lucide-react';

/**
 * AP pulls panel (ADR-177 decision c) — shown on AP Sort for the crew.
 *
 * Out-of-zone packages riding inside good totes are flagged at the station
 * for visibility but physically pulled and recorded HERE, at the anchor
 * point, by the walker/driver. Confirming feeds the same returns tracking
 * as station removals (backend scopes drivers/trainers to their own truck).
 */
export default function ApPullsPanel({ date }: { date: string }) {
  const [data, setData] = useState<RemovalsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await axiosClient.get<RemovalsResponse>(`/sort/${date}/removals`);
      setData(res.data);
    } catch {
      /* drivers may lack removals read access in older deployments — hide */
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  const pulls = (data?.removals ?? []).filter(r => r.pull_point === 'anchor_point');
  if (pulls.length === 0) return null;

  const onConfirm = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await axiosClient.post<RemovalsResponse>(`/sort/removals/${id}/confirm`);
      setData(res.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Confirm failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <PackageX className="w-4 h-4 text-danger" />
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          AP pulls — out-of-zone packages to remove &amp; return
        </p>
      </div>
      {error && (
        <div className="p-2.5 text-xs text-danger bg-danger/5 border border-danger/20 rounded-xl">{error}</div>
      )}
      <div className="border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-accent/40 text-muted-foreground">
              <th className="px-2 py-1.5 text-left">Bag</th>
              <th className="px-2 py-1.5 text-left">TBA</th>
              <th className="px-2 py-1.5 text-left w-40">Status</th>
            </tr>
          </thead>
          <tbody>
            {pulls.map(r => (
              <tr key={r.id} className={`border-b border-border/40 last:border-0 ${r.status === 'removed' ? 'opacity-60' : ''}`}>
                <td className="px-2 py-1.5 font-mono text-xs font-semibold text-foreground">{r.bag_id}</td>
                <td className="px-2 py-1.5 font-mono text-xs text-foreground">{r.tba}</td>
                <td className="px-2 py-1.5">
                  {r.status === 'removed' ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-success">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      pulled{r.removed_by_name ? ` · ${r.removed_by_name}` : ''}
                    </span>
                  ) : (
                    <button
                      disabled={busy}
                      onClick={() => onConfirm(r.id)}
                      className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-danger text-white hover:bg-danger/90 disabled:opacity-50"
                    >
                      Pulled — return to station
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
