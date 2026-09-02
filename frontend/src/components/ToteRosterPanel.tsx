import { errorText } from '../utils/errorText';
import { useCallback, useEffect, useMemo, useState } from 'react';
import axiosClient from '../api/axiosClient';
import type { RostersResponse, TruckRoster, RosterTote, ToteTransferOut, AddFreightResponse, LooseFreightIn } from '../api/types';
import { useNotificationContext } from '../contexts/NotificationContext';
import {
  CheckCircle2, CheckCheck, ChevronDown, ChevronUp, Package, Printer,
  ArrowLeftRight, AlertTriangle, Loader2, Undo2, Search, Plus,
} from 'lucide-react';

// ADR-184: mid-day freight add — dispatch pastes loose packages (TBA + address),
// the backend best-fits each to a truck by location. Unroutable items come back
// for manual handling; confirmed trucks reject adds until reopened.
function AddFreightForm({ date, busy, onDone }: {
  date: string;
  busy: boolean;
  onDone: (res: AddFreightResponse) => void;
}) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<LooseFreightIn[]>([{ tba: '', address: '', size: '' }]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (i: number, patch: Partial<LooseFreightIn>) =>
    setRows(rs => rs.map((r, idx) => idx === i ? { ...r, ...patch } : r));
  const addRow = () => setRows(rs => [...rs, { tba: '', address: '', size: '' }]);
  const removeRow = (i: number) => setRows(rs => rs.filter((_, idx) => idx !== i));

  const submit = async () => {
    const loose = rows
      .map(r => ({ tba: r.tba.trim(), address: r.address.trim(), size: r.size?.trim() || undefined }))
      .filter(r => r.tba && r.address);
    if (loose.length === 0) { setError('Add at least one package (TBA + address).'); return; }
    setSubmitting(true);
    setError(null);
    try {
      const res = await axiosClient.post<AddFreightResponse>(`/sort/${date}/add-freight`, { loose });
      onDone(res.data);
      setRows([{ tba: '', address: '', size: '' }]);
      setOpen(false);
    } catch (e: unknown) {
      setError(errorText(e, 'Add failed.'));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <Plus className="w-3.5 h-3.5" /> Add freight
      </button>
    );
  }

  return (
    <div className="w-full border border-border rounded-xl p-3 space-y-2 bg-card">
      <div className="flex items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Add mid-day freight</p>
        <span className="text-[11px] text-muted-foreground">Routed to the best-fit truck by address</span>
      </div>
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            value={r.tba} onChange={e => update(i, { tba: e.target.value })}
            placeholder="TBA / tracking #"
            className="flex-1 min-w-0 px-2 py-1 text-xs bg-accent/40 border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <input
            value={r.address} onChange={e => update(i, { address: e.target.value })}
            placeholder="Delivery address"
            className="flex-[2] min-w-0 px-2 py-1 text-xs bg-accent/40 border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <select
            value={r.size ?? ''} onChange={e => update(i, { size: e.target.value })}
            className="px-2 py-1 text-xs bg-accent/40 border border-border rounded-lg text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">OV size…</option>
            <option value="OV_S">OV_S</option>
            <option value="OV_M">OV_M</option>
            <option value="OV_L">OV_L</option>
            <option value="OV_XL">OV_XL</option>
          </select>
          {rows.length > 1 && (
            <button onClick={() => removeRow(i)} className="text-muted-foreground hover:text-danger text-xs px-1">✕</button>
          )}
        </div>
      ))}
      {error && <p className="text-xs text-danger">{error}</p>}
      <div className="flex items-center gap-2">
        <button onClick={addRow} className="text-[11px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
          <Plus className="w-3 h-3" /> Another
        </button>
        <div className="flex-1" />
        <button onClick={() => { setOpen(false); setError(null); }} className="text-[11px] px-2.5 py-1 rounded-lg border border-border hover:bg-accent text-foreground">
          Cancel
        </button>
        <button
          disabled={submitting || busy}
          onClick={submit}
          className="btn-primary text-[11px] px-3 py-1 disabled:opacity-50"
        >
          {submitting ? 'Adding…' : 'Add & route'}
        </button>
      </div>
    </div>
  );
}

/**
 * Station load finalization panel (ADR-174).
 *
 * mode="dispatch" — full check-off + transfer resolution for every truck.
 * mode="driver"   — the caller's own truck: load checklist plus incoming /
 *                   outgoing station transfers with counterpart truck+driver.
 *
 * Rows are click-to-check (dock gloves + tablets). Manual transfers are
 * dispatch judgment — audited, undoable, re-applied across re-runs (ADR-177).
 */

interface Props {
  date: string;
  mode: 'dispatch' | 'driver';
}

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
  tote, roster, allRosters, mode, busy, locked, onCheck, onTransfer, onUndo,
}: {
  tote: RosterTote;
  roster: TruckRoster;
  allRosters: TruckRoster[];
  mode: 'dispatch' | 'driver';
  busy: boolean;
  locked: boolean;
  onCheck: (bag: string, checked: boolean) => void;
  onTransfer: (bag: string, toTruckId: string) => void;
  onUndo: (id: string) => void;
}) {
  const [moveOpen, setMoveOpen] = useState(false);
  const movable = mode === 'dispatch' && !tote.transfer && !locked;
  const primaryDock = tote.dock_tags[0];
  const extraDocks = tote.dock_tags.slice(1);

  return (
    <tr
      onClick={() => !busy && !locked && onCheck(tote.bag_id, !tote.checked)}
      className={`border-b border-border/40 last:border-0 select-none transition-colors ${
        locked ? 'cursor-default' : 'cursor-pointer'
      } ${tote.checked ? 'bg-success/5 opacity-60' : locked ? '' : 'hover:bg-accent/30'}`}
      title={
        locked
          ? 'Loading confirmed, check-off is locked'
          : tote.checked && tote.checked_by_name ? `Checked by ${tote.checked_by_name}` : 'Tap row to check off'
      }
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
        {(tote.pull_tbas?.length ?? 0) > 0 && (
          <span
            className="ml-1.5 px-1.5 py-0.5 rounded-md text-[9px] font-bold uppercase bg-danger text-white"
            title={`Out-of-zone packages in this tote, pulled and returned at the AP: ${tote.pull_tbas!.join(', ')}`}
          >
            AP RETURN {tote.pull_tbas!.length}
          </span>
        )}
        {(tote.rider_count ?? 0) > 0 && (
          <span
            className="ml-1.5 px-1.5 py-0.5 rounded-md text-[9px] font-bold uppercase bg-accent text-muted-foreground"
            title="Packages off this tote's home block. Expected cross-walker handoffs at the AP."
          >
            {tote.rider_count} AP handoff{tote.rider_count === 1 ? '' : 's'}
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
  roster, allRosters, mode, busy, onCheck, onCheckAll, onTransfer, onUndo, onConfirmLoad, onUnconfirmLoad,
}: {
  roster: TruckRoster;
  allRosters: TruckRoster[];
  mode: 'dispatch' | 'driver';
  busy: boolean;
  onCheck: (bag: string, checked: boolean) => void;
  onCheckAll: (truckId: string) => void;
  onTransfer: (bag: string, toTruckId: string) => void;
  onUndo: (id: string) => void;
  onConfirmLoad: (truckId: string) => void;
  onUnconfirmLoad: (truckId: string) => void;
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
        {roster.load_confirmed && (
          <span
            className="inline-flex items-center gap-1 text-[10px] font-semibold text-success"
            title={`Driver confirmed${roster.confirmed_by_name ? ` by ${roster.confirmed_by_name}` : ''}${roster.short_count ? ` — ${roster.short_count} short` : ''}`}
          >
            <CheckCheck className="w-3.5 h-3.5" /> Confirmed
            {roster.short_count ? <span className="text-warning">({roster.short_count} short)</span> : null}
          </span>
        )}
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
            {mode === 'dispatch' && remaining > 0 && !roster.load_confirmed && (
              <button
                disabled={busy}
                onClick={() => onCheckAll(roster.truck_id)}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg border border-border hover:bg-accent text-foreground disabled:opacity-50"
              >
                <CheckCheck className="w-3.5 h-3.5" /> Check all ({remaining})
              </button>
            )}
            {mode === 'dispatch' && roster.load_confirmed && (
              <>
                <span className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-success">
                  <CheckCheck className="w-3.5 h-3.5" /> Loading locked
                </span>
                <button
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm('Reopen this truck’s loading? Check-off unlocks so the crew can add a late tote or clear a missing one.')) {
                      onUnconfirmLoad(roster.truck_id);
                    }
                  }}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg border border-border hover:bg-accent text-foreground disabled:opacity-50"
                >
                  <Undo2 className="w-3.5 h-3.5" /> Reopen
                </button>
              </>
            )}
            {mode === 'driver' && !roster.load_confirmed && (
              <button
                disabled={busy}
                onClick={() => {
                  if (remaining > 0 && !window.confirm(
                    `${remaining} tote${remaining === 1 ? '' : 's'} still unchecked. Confirm loading anyway? ` +
                    `The unchecked totes will be reported to dispatch as short/missing.`,
                  )) return;
                  onConfirmLoad(roster.truck_id);
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-success/10 border border-success/40 hover:bg-success/20 text-success disabled:opacity-50"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                {remaining > 0 ? `Confirm loading (${remaining} short)` : 'Confirm loading complete'}
              </button>
            )}
            {mode === 'driver' && roster.load_confirmed && (
              <>
                <span className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-success">
                  <CheckCheck className="w-3.5 h-3.5" /> Loading confirmed, handed off to dispatch
                </span>
                <button
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm('Reopen loading? This unlocks check-off so you can add a late tote or fix a missing one, and notifies dispatch.')) {
                      onUnconfirmLoad(roster.truck_id);
                    }
                  }}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg border border-border hover:bg-accent text-foreground disabled:opacity-50"
                >
                  <Undo2 className="w-3.5 h-3.5" /> Reopen
                </button>
              </>
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
                    locked={!!roster.load_confirmed}
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
  const { setOnNotification } = useNotificationContext();
  const [data, setData] = useState<RostersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unrouted, setUnrouted] = useState<AddFreightResponse['unrouted']>([]);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<RostersResponse>(`/sort/${date}/rosters`, {
        params: mode === 'driver' ? { mine: true } : {},
      });
      setData(res.data);
    } catch {
      if (!silent) setError('Could not load tote rosters.');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [date, mode]);

  useEffect(() => { load(); }, [load]);

  // Dispatch view: keep the roster fresh as drivers check off / confirm loading
  // remotely (ADR-181, SSE per ADR-179). Refetch on a load_confirmed push;
  // a slow visibility-gated fallback poll covers a dropped event and interim
  // check-off progress. Driver mode doesn't need this — it mutates its own truck.
  useEffect(() => {
    if (mode !== 'dispatch') return;
    setOnNotification((type: string) => {
      if (type === 'load_confirmed' || type === 'tote_checked') load(true);
    });
    const tick = () => { if (document.visibilityState === 'visible') load(true); };
    const interval = setInterval(tick, 45_000);
    window.addEventListener('focus', tick);
    return () => {
      setOnNotification(null);
      clearInterval(interval);
      window.removeEventListener('focus', tick);
    };
  }, [mode, setOnNotification, load]);

  const mutate = async (fn: () => Promise<{ data: RostersResponse }>) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      setData(res.data);
    } catch (e: unknown) {
      const detail = errorText(e, '') || undefined;
      setError(detail ?? 'Action failed. Refresh and try again.');
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
  const onConfirmAll = () =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/${date}/transfers/confirm-all`));
  const onUndo = (id: string) =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/transfers/${id}/undo`));
  const onTransfer = (bag: string, toTruckId: string) =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/${date}/totes/${encodeURIComponent(bag)}/transfer`, { to_truck_id: toTruckId }));
  const onConfirmLoad = (truckId: string) =>
    mutate(() => axiosClient.post<RostersResponse>(`/sort/${date}/trucks/${truckId}/confirm-load`));
  const onUnconfirmLoad = (truckId: string) =>
    mutate(() => axiosClient.delete<RostersResponse>(`/sort/${date}/trucks/${truckId}/confirm-load`));

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
        persistence show counts only). A hub's totes come from its own manifest
        instead. Upload it on Station Sort and they appear here without a sort run.
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
          <span className="text-muted-foreground">Every tote checked, no pending transfers. AP Sort is working from physical truth.</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 p-3 bg-warning/5 border border-warning/20 rounded-xl text-sm">
          <AlertTriangle className="w-4 h-4 text-warning shrink-0" />
          <span className="text-foreground font-medium">Loading not finalized</span>
          <span className="text-muted-foreground">
            — {data.pending_transfer_count} pending transfer{data.pending_transfer_count === 1 ? '' : 's'},{' '}
            {data.unchecked_count} tote{data.unchecked_count === 1 ? '' : 's'} unchecked
            {(data.flagged_removal_count ?? 0) > 0 && (
              <>, {data.flagged_removal_count} station removal{data.flagged_removal_count === 1 ? '' : 's'} pending</>
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
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              Pending transfers: confirm the move or keep in place
            </p>
            <div className="flex-1" />
            {pending.size > 1 && (
              <button
                disabled={busy}
                onClick={onConfirmAll}
                title="Keep any exceptions first. This confirms every remaining suggestion."
                className="btn-primary text-xs px-3 py-1.5 disabled:opacity-50"
              >
                Confirm all {pending.size} moves
              </button>
            )}
          </div>
          {[...pending.values()].map(t => (
            <PendingTransferCard key={t.id} t={t} busy={busy} onResolve={onResolve} />
          ))}
        </div>
      )}

      {mode === 'dispatch' && (
        <div className="flex items-center gap-4 justify-end">
          <AddFreightForm
            date={date}
            busy={busy}
            onDone={(res) => {
              setData(res);
              setUnrouted(res.unrouted ?? []);
            }}
          />
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

      {mode === 'dispatch' && unrouted.length > 0 && (
        <div className="p-3 rounded-xl bg-warning/5 border border-warning/20 text-xs space-y-1">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-warning shrink-0" />
            <span className="text-foreground font-medium">
              {unrouted.length} package{unrouted.length === 1 ? '' : 's'} not routed · assign manually
            </span>
            <div className="flex-1" />
            <button onClick={() => setUnrouted([])} className="text-muted-foreground hover:text-foreground text-[11px]">Dismiss</button>
          </div>
          <ul className="pl-6 space-y-0.5 text-muted-foreground">
            {unrouted.map(u => (
              <li key={u.tba} className="font-mono">
                {u.tba} — {u.reason === 'truck_confirmed' ? 'target truck confirmed (reopen it first)'
                  : u.reason === 'geocode_failed' ? 'address could not be located'
                  : 'no matching truck'}
              </li>
            ))}
          </ul>
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
            onConfirmLoad={onConfirmLoad}
            onUnconfirmLoad={onUnconfirmLoad}
          />
        ))}
      </div>
    </div>
  );
}
