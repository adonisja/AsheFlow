import { errorText } from '../utils/errorText';
import { useCallback, useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { RemovalsResponse } from '../api/types';
import { PackageX, CheckCircle2, Clock } from 'lucide-react';

/**
 * AP pulls — driver view (ADR-177/178).
 *
 * Out-of-zone packages ride inside good totes to the anchor point. The WALKER
 * whose route owns the tote finds the package and hands it to the driver; the
 * driver confirms receipt here (two-party handoff), which completes the pull
 * and feeds returns tracking. "expect from" is derived from the current route
 * assignment, so it auto-updates on rebalance.
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
      /* hidden if unreadable */
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  const pulls = (data?.removals ?? []).filter(r => r.pull_point === 'anchor_point');
  if (pulls.length === 0) return null;

  const onReceive = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await axiosClient.post<RemovalsResponse>(`/sort/removals/${id}/receive`);
      setData(res.data);
    } catch (e: unknown) {
      const detail = errorText(e, '') || undefined;
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
          AP returns · out-of-zone packages coming back from walkers
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
              <th className="px-2 py-1.5 text-left">Expect from</th>
              <th className="px-2 py-1.5 text-left w-48">Status</th>
            </tr>
          </thead>
          <tbody>
            {pulls.map(r => {
              const st = r.handoff_status ?? 'pending';
              return (
                <tr key={r.id} className={`border-b border-border/40 last:border-0 ${r.status === 'removed' ? 'opacity-60' : ''}`}>
                  <td className="px-2 py-1.5 font-mono text-xs font-semibold text-foreground">{r.bag_id}</td>
                  <td className="px-2 py-1.5 font-mono text-xs text-foreground">{r.tba}</td>
                  <td className="px-2 py-1.5 text-xs text-foreground">
                    {r.owner_walker_name
                      ? <>{r.owner_walker_name}{r.owner_route_number != null && <span className="text-muted-foreground"> · route {r.owner_route_number}</span>}</>
                      : <span className="text-muted-foreground italic">awaiting route assignment</span>}
                  </td>
                  <td className="px-2 py-1.5">
                    {st === 'received' ? (
                      <span className="inline-flex items-center gap-1 text-[11px] text-success">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        received{r.received_by_name ? ` · ${r.received_by_name}` : ''}
                      </span>
                    ) : st === 'handed_over' ? (
                      <button
                        disabled={busy}
                        onClick={() => onReceive(r.id)}
                        className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-danger text-white hover:bg-danger/90 disabled:opacity-50"
                      >
                        Confirm received
                      </button>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                        <Clock className="w-3.5 h-3.5" /> awaiting walker handover
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
