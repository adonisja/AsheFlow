import { errorText } from '../utils/errorText';
import { useCallback, useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { RemovalsResponse } from '../api/types';
import { PackageX, CheckCircle2, ArrowRight } from 'lucide-react';

/**
 * Walker AP returns (ADR-178) — shown on /my-route.
 *
 * Out-of-zone packages ride inside the walker's totes. They are NOT deliveries:
 * the walker hands them back to the driver at the anchor point. This lists the
 * OOZ packages whose bag is in one of the walker's route totes, with a
 * "Handing to driver" action. Scoped server-side to the walker's own routes.
 */
export default function WalkerApReturnsPanel({ date, bagIds }: { date: string; bagIds: string[] }) {
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

  const bagSet = new Set(bagIds);
  const mine = (data?.removals ?? []).filter(
    r => r.pull_point === 'anchor_point' && bagSet.has(r.bag_id),
  );
  if (mine.length === 0) return null;

  const onHandover = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await axiosClient.post<RemovalsResponse>(`/sort/removals/${id}/handover`);
      setData(res.data);
    } catch (e: unknown) {
      const detail = errorText(e, '') || undefined;
      setError(detail ?? 'Action failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-danger/30 bg-danger/5 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <PackageX className="w-4 h-4 text-danger shrink-0" />
        <p className="text-sm font-semibold text-foreground">Return to driver — not deliveries</p>
      </div>
      <p className="text-xs text-muted-foreground">
        These packages are outside the company's delivery area. Do not deliver them —
        hand them to your driver at the anchor point.
      </p>
      {error && (
        <div className="p-2.5 text-xs text-danger bg-danger/10 border border-danger/20 rounded-xl">{error}</div>
      )}
      <div className="space-y-2">
        {mine.map(r => {
          const st = r.handoff_status ?? 'pending';
          return (
            <div key={r.id} className="flex items-center gap-2 p-2.5 bg-card rounded-xl border border-border">
              <div className="flex-1 min-w-0 text-xs">
                <span className="font-mono font-semibold text-foreground">{r.tba}</span>
                <span className="text-muted-foreground"> · bag {r.bag_id}</span>
              </div>
              {st === 'received' ? (
                <span className="inline-flex items-center gap-1 text-[11px] text-success shrink-0">
                  <CheckCircle2 className="w-3.5 h-3.5" /> received by driver
                </span>
              ) : st === 'handed_over' ? (
                <span className="text-[11px] text-warning font-semibold shrink-0">handed over — awaiting driver</span>
              ) : (
                <button
                  disabled={busy}
                  onClick={() => onHandover(r.id)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg bg-danger text-white hover:bg-danger/90 disabled:opacity-50 shrink-0"
                >
                  Handing to driver <ArrowRight className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
