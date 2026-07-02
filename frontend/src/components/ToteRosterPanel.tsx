import { useCallback, useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { RostersResponse, TruckRoster, RosterTote, ToteTransferOut } from '../api/types';
import {
  CheckCircle2, ChevronDown, ChevronUp, Package, Printer,
  ArrowLeftRight, AlertTriangle, Loader2,
} from 'lucide-react';

/**
 * Station load finalization panel (ADR-174).
 *
 * mode="dispatch" — full check-off + transfer resolution for every truck.
 * mode="driver"   — the caller's own truck: load checklist plus incoming /
 *                   outgoing station transfers with counterpart truck+driver.
 *
 * All mutations return the refreshed rosters payload, so state stays in sync
 * without refetch choreography.
 */

interface Props {
  date: string;
  mode: 'dispatch' | 'driver';
}

function TransferBadge({ t, truckId }: { t: ToteTransferOut; truckId: string }) {
  const incoming = t.to_truck_id === truckId;
  const other = incoming ? t.from_truck_name : t.to_truck_name;
  const driver = incoming ? t.from_driver_name : t.to_driver_name;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold ${
      t.status === 'suggested' ? 'bg-warning/10 text-warning' : 'bg-primary/10 text-primary'
    }`}>
      <ArrowLeftRight className="w-3 h-3" />
      {incoming ? 'from' : 'to'} {other}{driver ? ` · ${driver}` : ''}
      {t.status === 'suggested' && ' (pending)'}
    </span>
  );
}

function PendingTransferCard({
  t, busy, onResolve,
}: { t: ToteTransferOut; busy: boolean; onResolve: (id: string, action: 'confirm' | 'keep') => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2 p-2.5 bg-warning/5 border border-warning/20 rounded-xl">
      <div className="flex-1 min-w-[200px] text-xs">
        <span className="font-mono font-semibold text-foreground">{t.bag_id}</span>
        <span className="text-muted-foreground"> ({t.package_count ?? '?'} pkgs) — currently on </span>
        <span className="font-semibold text-foreground">{t.from_truck_name}</span>
        {t.from_driver_name && <span className="text-muted-foreground"> ({t.from_driver_name})</span>}
        <span className="text-muted-foreground"> · new sort wants </span>
        <span className="font-semibold text-foreground">{t.to_truck_name}</span>
        {t.to_driver_name && <span className="text-muted-foreground"> ({t.to_driver_name})</span>}
      </div>
      {/* Suggested destination is the default/primary action; keeping the
          current truck stays available as the secondary option. */}
      <button
        disabled={busy}
        onClick={() => onResolve(t.id, 'confirm')}
        className="btn-primary text-xs px-3 py-1.5 disabled:opacity-50"
      >
        Move to {t.to_truck_name}
      </button>
      <button
        disabled={busy}
        onClick={() => onResolve(t.id, 'keep')}
        className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-accent text-foreground disabled:opacity-50"
      >
        Keep on {t.from_truck_name}
      </button>
    </div>
  );
}

function ToteRow({
  tote, roster, allRosters, mode, busy, onCheck, onTransfer,
}: {
  tote: RosterTote;
  roster: TruckRoster;
  allRosters: TruckRoster[];
  mode: 'dispatch' | 'driver';
  busy: boolean;
  onCheck: (bag: string, checked: boolean) => void;
  onTransfer: (bag: string, toTruckId: string) => void;
}) {
  const [moveOpen, setMoveOpen] = useState(false);
  return (
    <tr className={`border-b border-border/40 last:border-0 ${tote.checked ? 'bg-success/5' : ''}`}>
      <td className="px-2 py-1.5">
        <input
          type="checkbox"
          className="w-4 h-4 accent-[var(--color-success,#16a34a)] cursor-pointer"
          checked={tote.checked}
          disabled={busy}
          onChange={() => onCheck(tote.bag_id, !tote.checked)}
          title={tote.checked && tote.checked_by_name ? `Checked by ${tote.checked_by_name}` : 'Check off as loaded'}
        />
      </td>
      <td className="px-2 py-1.5 font-mono text-xs font-semibold text-foreground">{tote.bag_id}</td>
      <td className="px-2 py-1.5 font-mono text-[11px] text-muted-foreground">
        {tote.dock_tags.join(', ') || '—'}
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums text-xs text-foreground">{tote.package_count}</td>
      <td className="px-2 py-1.5 text-[11px] text-muted-foreground">
        {tote.ov_count > 0
          ? <>
              <span className="font-semibold text-foreground">{tote.ov_count}</span>
              {' '}({tote.ov_sizes.map(sz => sz.replace('OV_', '')).join(', ')})
              {tote.ov_dock_tags.length > 0 && (
                <span className="font-mono"> @ {tote.ov_dock_tags.join(', ')}</span>
              )}
            </>
          : '—'}
      </td>
      <td className="px-2 py-1.5">
        {tote.transfer && <TransferBadge t={tote.transfer} truckId={roster.truck_id} />}
      </td>
      {mode === 'dispatch' && (
        <td className="px-2 py-1.5 text-right relative">
          {!tote.transfer && (
            <>
              <button
                disabled={busy}
                onClick={() => setMoveOpen(v => !v)}
                className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                Move…
              </button>
              {moveOpen && (
                <div className="absolute right-2 z-20 mt-1 bg-card border border-border rounded-xl shadow-lg py-1 min-w-[140px]">
                  {allRosters.filter(r => r.truck_id !== roster.truck_id).map(r => (
                    <button
                      key={r.truck_id}
                      className="block w-full text-left px-3 py-1.5 text-xs hover:bg-accent text-foreground"
                      onClick={() => { setMoveOpen(false); onTransfer(tote.bag_id, r.truck_id); }}
                    >
                      {r.zone_label}{r.driver_name ? ` · ${r.driver_name}` : ''}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </td>
      )}
    </tr>
  );
}

function TruckSection({
  roster, allRosters, mode, busy, onCheck, onTransfer,
}: {
  roster: TruckRoster;
  allRosters: TruckRoster[];
  mode: 'dispatch' | 'driver';
  busy: boolean;
  onCheck: (bag: string, checked: boolean) => void;
  onTransfer: (bag: string, toTruckId: string) => void;
}) {
  const [open, setOpen] = useState(mode === 'driver');
  const pct = roster.totes.length > 0 ? Math.round((roster.checked_count / roster.totes.length) * 100) : 0;
  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-3 px-3 py-2.5 bg-accent/30 hover:bg-accent/50 text-left"
      >
        <span className="font-semibold text-sm text-foreground">{roster.zone_label}</span>
        {roster.driver_name && <span className="text-xs text-muted-foreground">{roster.driver_name}</span>}
        <div className="flex-1 mx-2 h-1.5 bg-border rounded-full overflow-hidden max-w-[160px]">
          <div className={`h-full rounded-full ${pct === 100 ? 'bg-success' : 'bg-primary'}`} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">
          {roster.checked_count}/{roster.totes.length} loaded
        </span>
        {roster.incoming.length + roster.outgoing.length > 0 && (
          <span className="text-[10px] font-semibold text-warning">
            ⇄ {roster.incoming.length + roster.outgoing.length}
          </span>
        )}
        {open ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
      </button>
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-accent/20 text-muted-foreground">
                <th className="px-2 py-1.5 text-left w-8">✓</th>
                <th className="px-2 py-1.5 text-left">Bag</th>
                <th className="px-2 py-1.5 text-left">Dock</th>
                <th className="px-2 py-1.5 text-right">Pkgs</th>
                <th className="px-2 py-1.5 text-left">OVs</th>
                <th className="px-2 py-1.5 text-left">Transfer</th>
                {mode === 'dispatch' && <th className="px-2 py-1.5 w-16" />}
              </tr>
            </thead>
            <tbody>
              {roster.totes.map(t => (
                <ToteRow
                  key={t.bag_id}
                  tote={t}
                  roster={roster}
                  allRosters={allRosters}
                  mode={mode}
                  busy={busy}
                  onCheck={onCheck}
                  onTransfer={onTransfer}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function ToteRosterPanel({ date, mode }: Props) {
  const [data, setData] = useState<RostersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<RostersResponse>(`/sort/${date}/rosters`, {
        params: mode === 'driver' ? { mine: true } : {},
      });
      setData(res.data);
    } catch {
      setError('Could not load tote rosters.');
    } finally {
      setLoading(false);
    }
  }, [date, mode]);

  useEffect(() => { load(); }, [load]);

  const mutate = async (fn: () => Promise<{ data: RostersResponse }>) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      setData(res.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Action failed — refresh and try again.');
    } finally {
      setBusy(false);
    }
  };

  const onCheck = (bag: string, checked: boolean) =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/${date}/totes/${encodeURIComponent(bag)}/check`, { checked }));
  const onResolve = (id: string, action: 'confirm' | 'keep') =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/transfers/${id}/resolve`, { action }));
  const onTransfer = (bag: string, toTruckId: string) =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/${date}/totes/${encodeURIComponent(bag)}/transfer`, { to_truck_id: toTruckId }));

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading tote rosters…
      </div>
    );
  }
  if (!data || !data.roster_available || data.rosters.length === 0) {
    if (mode === 'driver') return null;  // nothing staged for this driver yet
    return (
      <div className="p-4 text-sm text-muted-foreground border border-dashed border-border rounded-xl">
        <Package className="w-4 h-4 inline mr-1.5" />
        Tote rosters appear here after the next sort run (zones from before roster
        persistence show counts only).
      </div>
    );
  }

  // Pending suggested transfers, deduplicated across trucks
  const pending = new Map<string, ToteTransferOut>();
  data.rosters.forEach(r =>
    [...r.incoming, ...r.outgoing]
      .filter(t => t.status === 'suggested')
      .forEach(t => pending.set(t.id, t)),
  );

  return (
    <div className="space-y-3">
      {/* Soft gate banner (ADR-174 decision b: warn, never block) */}
      {data.loading_finalized ? (
        <div className="flex items-center gap-2 p-3 bg-success/5 border border-success/20 rounded-xl text-sm">
          <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
          <span className="text-foreground font-medium">Loading finalized</span>
          <span className="text-muted-foreground">— every tote checked, no pending transfers. AP Sort is working from physical truth.</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 p-3 bg-warning/5 border border-warning/20 rounded-xl text-sm">
          <AlertTriangle className="w-4 h-4 text-warning shrink-0" />
          <span className="text-foreground font-medium">Loading not finalized</span>
          <span className="text-muted-foreground">
            — {data.pending_transfer_count} pending transfer{data.pending_transfer_count === 1 ? '' : 's'},{' '}
            {data.unchecked_count} tote{data.unchecked_count === 1 ? '' : 's'} unchecked.
            {mode === 'dispatch' ? ' AP Sort will proceed on unconfirmed contents.' : ''}
          </span>
        </div>
      )}

      {error && (
        <div className="p-2.5 text-xs text-danger bg-danger/5 border border-danger/20 rounded-xl">{error}</div>
      )}

      {mode === 'dispatch' && pending.size > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Pending transfers — confirm the move or keep in place
          </p>
          {[...pending.values()].map(t => (
            <PendingTransferCard key={t.id} t={t} busy={busy} onResolve={onResolve} />
          ))}
        </div>
      )}

      {mode === 'dispatch' && (
        <div className="flex justify-end">
          <a
            href={`/sort/print?date=${date}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <Printer className="w-3.5 h-3.5" /> Print load sheets
          </a>
        </div>
      )}

      <div className="space-y-2">
        {data.rosters.map(r => (
          <TruckSection
            key={r.zone_id}
            roster={r}
            allRosters={data.rosters}
            mode={mode}
            busy={busy}
            onCheck={onCheck}
            onTransfer={onTransfer}
          />
        ))}
      </div>
    </div>
  );
}
