import { useCallback, useEffect, useMemo, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { RostersResponse, TruckRoster, RosterTote, ToteTransferOut } from '../api/types';
import {
  CheckCircle2, CheckCheck, ChevronDown, ChevronUp, Package, Printer,
  ArrowLeftRight, AlertTriangle, Loader2, Undo2, Search,
} from 'lucide-react';

/**
 * Station load finalization panel (ADR-174).
 *
 * mode="dispatch" — full check-off + transfer resolution for every truck.
 * mode="driver"   — the caller's own truck: load checklist plus incoming /
 *                   outgoing station transfers with counterpart truck+driver.
 *
 * Rows are click-to-check (dock gloves + tablets); manual transfers are only
 * offered on totes tier-1 flagged as stray/uncertain/misaligned — clean totes
 * sit where the balanced sort wants them, and the backend enforces the same.
 */

interface Props {
  date: string;
  mode: 'dispatch' | 'driver';
}

const CLASS_STYLES: Record<string, string> = {
  stray:       'bg-warning/10 text-warning',
  uncertain:   'bg-orange-500/10 text-orange-500',
  misaligned:  'bg-danger/10 text-danger',
  out_of_zone: 'bg-danger/20 text-danger',
};

function OvPills({ tote }: { tote: RosterTote }) {
  if (tote.ov_count === 0) return <span className="text-muted-foreground">—</span>;
  const details = tote.ov_details && tote.ov_details.length > 0
    ? tote.ov_details
    : tote.ov_sizes.map(s => ({ size: s, zone: null as string | null }));
  return (
    <span className="inline-flex flex-wrap gap-1">
      {details.map((d, i) => (
        <span key={i} className="px-1.5 py-0.5 rounded-md bg-accent text-[10px] font-semibold text-foreground whitespace-nowrap">
          {d.size.replace('OV_', '')}
          {d.zone && <span className="text-muted-foreground font-mono"> @{d.zone}</span>}
        </span>
      ))}
    </span>
  );
}

function TransferBadge({
  t, truckId, mode, busy, onUndo,
}: { t: ToteTransferOut; truckId: string; mode: 'dispatch' | 'driver'; busy: boolean; onUndo: (id: string) => void }) {
  const incoming = t.to_truck_id === truckId;
  const other = incoming ? t.from_truck_name : t.to_truck_name;
  const driver = incoming ? t.from_driver_name : t.to_driver_name;
  const label = t.status === 'kept'
    ? `kept (was → ${t.to_truck_name})`
    : `${incoming ? 'from' : 'to'} ${other}${driver ? ` · ${driver}` : ''}${t.status === 'suggested' ? ' (pending)' : ''}`;
  const undoable = mode === 'dispatch' && (t.status === 'confirmed' || t.status === 'kept');
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold ${
        t.status === 'suggested' ? 'bg-warning/10 text-warning'
        : t.status === 'kept' ? 'bg-accent text-muted-foreground'
        : 'bg-primary/10 text-primary'
      }`}>
        <ArrowLeftRight className="w-3 h-3" />
        {label}
      </span>
      {undoable && (
        <button
          disabled={busy}
          onClick={(e) => { e.stopPropagation(); onUndo(t.id); }}
          title="Undo this decision"
          className="p-0.5 rounded text-muted-foreground hover:text-foreground disabled:opacity-40"
        >
          <Undo2 className="w-3.5 h-3.5" />
        </button>
      )}
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
  tote, roster, allRosters, mode, busy, onCheck, onTransfer, onUndo,
}: {
  tote: RosterTote;
  roster: TruckRoster;
  allRosters: TruckRoster[];
  mode: 'dispatch' | 'driver';
  busy: boolean;
  onCheck: (bag: string, checked: boolean) => void;
  onTransfer: (bag: string, toTruckId: string) => void;
  onUndo: (id: string) => void;
}) {
  const [moveOpen, setMoveOpen] = useState(false);
  const cls = tote.classification ?? 'clean';
  const flagged = cls !== 'clean';
  const movable = mode === 'dispatch' && flagged && !tote.transfer;
  const primaryDock = tote.dock_tags[0];
  const extraDocks = tote.dock_tags.slice(1);

  return (
    <tr
      onClick={() => !busy && onCheck(tote.bag_id, !tote.checked)}
      className={`border-b border-border/40 last:border-0 cursor-pointer select-none transition-colors ${
        tote.checked ? 'bg-success/5 opacity-60' : 'hover:bg-accent/30'
      }`}
      title={tote.checked && tote.checked_by_name ? `Checked by ${tote.checked_by_name}` : 'Tap row to check off'}
    >
      <td className="px-3 py-2">
        <span className={`inline-flex items-center justify-center w-5 h-5 rounded-md border-2 ${
          tote.checked ? 'bg-success border-success text-white' : 'border-border'
        }`}>
          {tote.checked && <CheckCheck className="w-3.5 h-3.5" />}
        </span>
      </td>
      <td className="px-2 py-2">
        <span className={`font-mono text-xs font-semibold text-foreground ${tote.checked ? 'line-through' : ''}`}>
          {tote.bag_id}
        </span>
        {flagged && (
          <span className={`ml-1.5 px-1.5 py-0.5 rounded-md text-[9px] font-bold uppercase ${CLASS_STYLES[cls]}`}>
            {cls.replace('_', ' ')}
          </span>
        )}
        {(tote.pull_tbas?.length ?? 0) > 0 && (
          <span
            className="ml-1.5 px-1.5 py-0.5 rounded-md text-[9px] font-bold uppercase bg-danger text-white"
            title={`Out-of-zone packages to pull before loading: ${tote.pull_tbas!.join(', ')}`}
          >
            PULL {tote.pull_tbas!.length}
          </span>
        )}
      </td>
      <td className="px-2 py-2">
        <span className="font-mono text-sm font-bold text-foreground">{primaryDock ?? '—'}</span>
        {extraDocks.length > 0 && (
          <span className="font-mono text-[10px] text-muted-foreground ml-1" title="Misrouted packages carry their original bag's dock tag">
            +{extraDocks.join(', ')}
          </span>
        )}
      </td>
      <td className="px-2 py-2 text-right tabular-nums text-xs text-foreground">{tote.package_count}</td>
      <td className="px-2 py-2"><OvPills tote={tote} /></td>
      <td className="px-2 py-2" onClick={e => e.stopPropagation()}>
        {tote.transfer && (
          <TransferBadge t={tote.transfer} truckId={roster.truck_id} mode={mode} busy={busy} onUndo={onUndo} />
        )}
      </td>
      {mode === 'dispatch' && (
        <td className="px-2 py-2 text-right relative" onClick={e => e.stopPropagation()}>
          {movable && (
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
  roster, allRosters, mode, busy, onCheck, onCheckAll, onTransfer, onUndo,
}: {
  roster: TruckRoster;
  allRosters: TruckRoster[];
  mode: 'dispatch' | 'driver';
  busy: boolean;
  onCheck: (bag: string, checked: boolean) => void;
  onCheckAll: (truckId: string) => void;
  onTransfer: (bag: string, toTruckId: string) => void;
  onUndo: (id: string) => void;
}) {
  const [open, setOpen] = useState(mode === 'driver');
  const [filter, setFilter] = useState('');
  const [hideChecked, setHideChecked] = useState(false);

  const visible = useMemo(() => {
    const q = filter.trim().toUpperCase();
    return roster.totes.filter(t =>
      (!hideChecked || !t.checked) &&
      (!q || t.bag_id.toUpperCase().includes(q) || t.dock_tags.some(d => d.toUpperCase().includes(q))),
    );
  }, [roster.totes, filter, hideChecked]);

  const remaining = roster.totes.length - roster.checked_count;
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
        <>
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-card">
            <div className="relative flex-1 max-w-[220px]">
              <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                value={filter}
                onChange={e => setFilter(e.target.value)}
                placeholder="Filter bag or dock…"
                className="w-full pl-7 pr-2 py-1 text-xs bg-accent/40 border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer">
              <input type="checkbox" checked={hideChecked} onChange={e => setHideChecked(e.target.checked)} className="w-3 h-3" />
              Hide checked
            </label>
            <div className="flex-1" />
            {mode === 'dispatch' && remaining > 0 && (
              <button
                disabled={busy}
                onClick={() => onCheckAll(roster.truck_id)}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg border border-border hover:bg-accent text-foreground disabled:opacity-50"
              >
                <CheckCheck className="w-3.5 h-3.5" /> Check all ({remaining})
              </button>
            )}
          </div>
          <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-border bg-accent/60 backdrop-blur text-muted-foreground">
                  <th className="px-3 py-1.5 text-left w-10">✓</th>
                  <th className="px-2 py-1.5 text-left">Bag</th>
                  <th className="px-2 py-1.5 text-left">Dock</th>
                  <th className="px-2 py-1.5 text-right w-14">Pkgs</th>
                  <th className="px-2 py-1.5 text-left">OVs (size @ zone)</th>
                  <th className="px-2 py-1.5 text-left">Transfer</th>
                  {mode === 'dispatch' && <th className="px-2 py-1.5 w-16" />}
                </tr>
              </thead>
              <tbody>
                {visible.map(t => (
                  <ToteRow
                    key={t.bag_id}
                    tote={t}
                    roster={roster}
                    allRosters={allRosters}
                    mode={mode}
                    busy={busy}
                    onCheck={onCheck}
                    onTransfer={onTransfer}
                    onUndo={onUndo}
                  />
                ))}
                {visible.length === 0 && (
                  <tr><td colSpan={7} className="px-3 py-4 text-center text-muted-foreground text-xs">
                    {roster.totes.length === 0 ? 'No totes in this zone.' : 'No totes match the filter.'}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
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
  const onCheckAll = (truckId: string) =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/${date}/trucks/${truckId}/check-all`));
  const onResolve = (id: string, action: 'confirm' | 'keep') =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/transfers/${id}/resolve`, { action }));
  const onUndo = (id: string) =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/transfers/${id}/undo`));
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
            {data.unchecked_count} tote{data.unchecked_count === 1 ? '' : 's'} unchecked
            {(data.flagged_removal_count ?? 0) > 0 && (
              <>, {data.flagged_removal_count} out-of-zone removal{data.flagged_removal_count === 1 ? '' : 's'} pending</>
            )}.
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
            onCheckAll={onCheckAll}
            onTransfer={onTransfer}
            onUndo={onUndo}
          />
        ))}
      </div>
    </div>
  );
}
