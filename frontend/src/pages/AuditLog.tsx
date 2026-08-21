import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Shield, ChevronLeft, ChevronRight, RefreshCw, X, ChevronDown, ChevronUp, User, Search, Check } from 'lucide-react';
import axiosClient from '../api/axiosClient';

interface AuditEntry {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action_type: string;
  target_table: string;
  target_id: string;
  before_snapshot: Record<string, unknown> | null;
  after_snapshot:  Record<string, unknown> | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

const ACTION_CATEGORIES = [
  { value: '',                  label: 'All actions' },
  { value: 'employee',          label: 'Employees' },
  { value: 'dispatch',          label: 'Dispatch' },
  { value: 'pto',               label: 'PTO' },
  { value: 'off_day',           label: 'Off days' },
  { value: 'schedule_change',   label: 'Schedule changes' },
  { value: 'incident',          label: 'Incidents' },
  { value: 'training',          label: 'Training' },
  { value: 'roll_call',         label: 'Roll call' },
  { value: 'route',             label: 'Routes' },
  { value: 'route_handoff',     label: 'Route handoffs' },
  { value: 'rts_package',       label: 'RTS packages' },
  { value: 'fuel_log',          label: 'Fuel logs' },
  { value: 'shift_session',     label: 'Shift sessions' },
  { value: 'truck',             label: 'Trucks' },
  { value: 'assignment_change', label: 'Assignment changes' },
];

const ACTION_LABELS: Record<string, string> = {
  'employee.create':                       'Created employee',
  'employee.bulk_create':                  'Bulk-created employees',
  'employee.update':                       'Updated employee',
  'employee.promoted':                     'Promoted employee',
  'employee.demoted':                      'Demoted employee',
  'employee.deactivated':                  'Deactivated employee',
  'employee.reactivated':                  'Reactivated employee',
  'employee.deleted':                      'Deleted employee',
  'employee.injury_status_updated':        'Updated injury status',
  'employee_relationship.deleted':         'Removed employee relationship',
  'credentials.sent':                      'Sent login credentials',
  'dispatch.cleared':                      'Cleared dispatch',
  'pto.created':                           'Submitted PTO request',
  'pto.approved':                          'Approved PTO',
  'pto.rejected':                          'Rejected PTO',
  'pto.deleted':                           'Deleted PTO request',
  'off_day.approved':                      'Approved off day',
  'off_day.rejected':                      'Rejected off day',
  'off_day.deleted':                       'Deleted off day',
  'off_day.bulk_deleted':                  'Bulk-deleted off days',
  'schedule_change.approved':              'Approved schedule change',
  'schedule_change.rejected':              'Rejected schedule change',
  'incident.submitted':                    'Filed incident report',
  'incident.resolved':                     'Resolved incident',
  'roll_call.submit':                      'Submitted roll call',
  'roll_call.override':                    'Overrode roll call entry',
  'roll_call.confirm':                     'Confirmed roll call',
  'route.arrival_confirm':                 'Confirmed route arrival',
  'route_handoff.confirm':                 'Confirmed route handoff',
  'route_handoff.back_at_truck':           'Marked back at truck',
  'route_handoff.resolve_discrepancy':     'Resolved handoff discrepancy',
  'rts_package.create':                    'Created RTS package',
  'fuel_log.created':                      'Logged fuel entry',
  'fuel_log.updated':                      'Updated fuel log',
  'shift_session.started':                 'Started shift session',
  'shift_session.gate_advanced':           'Advanced shift gate',
  'shift_session.gate_skipped':            'Skipped shift gate',
  'shift_session.abandoned':               'Abandoned shift session',
  'shift_session.wiped':                   'Wiped shift session',
  'truck.deactivated':                     'Deactivated truck',
  'truck.deleted':                         'Deleted truck',
  'assignment_change.approved':            'Approved assignment change',
  'assignment_change.rejected':            'Rejected assignment change',
  'anchor_point.submitted':                'Submitted anchor point',
  'delivery_stop.create':                  'Created delivery stop',
  'delivery_stop.reconcile':              'Reconciled delivery stop',
  'missing_package.create':               'Reported missing package',
  'missing_package.resolve':              'Resolved missing package',
  'reattempt_assignment.create':          'Created reattempt assignment',
  'reattempt_assignment.update':          'Updated reattempt assignment',
  'timecard_adjustment.employee_signed_off': 'Employee signed off timecard',
  'timecard_adjustment.manager_approval':    'Manager approved timecard',
  'timecard_adjustments.reject':             'Rejected timecard adjustment',
};

const TABLE_LABELS: Record<string, string> = {
  employees:                  'Employee',
  time_off_requests:          'PTO',
  off_days:                   'Off day',
  schedule_change_requests:   'Schedule change',
  incidents:                  'Incident',
  shift_roll_calls:           'Roll call',
  routes:                     'Route',
  route_handoffs:             'Route handoff',
  rts_packages:               'RTS package',
  fuel_mileage_logs:          'Fuel log',
  shift_sessions:             'Shift session',
  trucks:                     'Truck',
  assignment_change_requests: 'Assignment change',
  truck_assignments:          'Dispatch',
  anchor_points:              'Anchor point',
  delivery_stops:             'Delivery stop',
  missing_packages:           'Missing package',
  reattempt_assignments:      'Reattempt',
  timecard_adjustments:       'Timecard',
};

type BadgeVariant = 'success' | 'danger' | 'warning' | 'info' | 'default';

function getBadgeVariant(actionType: string): BadgeVariant {
  const verb = actionType.split('.')[1] ?? '';
  if (['approved', 'created', 'reactivated', 'confirmed', 'resolved', 'graduated', 'started', 'create'].includes(verb)) return 'success';
  if (['rejected', 'deleted', 'deactivated', 'wiped', 'abandoned'].includes(verb)) return 'danger';
  if (['override', 'escalat', 'skipped', 'cleared'].some(s => actionType.includes(s))) return 'warning';
  if (['updated', 'submitted', 'sent', 'signed_off', 'update', 'submit'].some(s => actionType.includes(s))) return 'info';
  return 'default';
}

const BADGE_CLASSES: Record<BadgeVariant, string> = {
  success: 'bg-success/10 text-success border-success/20',
  danger:  'bg-danger/10 text-danger border-danger/20',
  warning: 'bg-warning/10 text-warning border-warning/20',
  info:    'bg-primary/10 text-primary border-primary/20',
  default: 'bg-surface text-muted-foreground border-border',
};

const LEFT_BORDER_CLASSES: Record<BadgeVariant, string> = {
  success: 'border-l-success/50',
  danger:  'border-l-danger/50',
  warning: 'border-l-warning/50',
  info:    'border-l-primary/40',
  default: 'border-l-border',
};

// ---------------------------------------------------------------------------
// Custom dropdown (avoids browser-native select styling)
// ---------------------------------------------------------------------------

function CategoryDropdown({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = options.find(o => o.value === value) ?? options[0];

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="input w-full text-sm flex items-center justify-between gap-2 text-left"
      >
        <span className="truncate">{selected.label}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-lg border border-border bg-card shadow-lg overflow-hidden">
          <div className="max-h-64 overflow-y-auto py-1">
            {options.map(o => (
              <button
                key={o.value}
                type="button"
                onClick={() => { onChange(o.value); setOpen(false); }}
                className={`w-full flex items-center justify-between px-3 py-2 text-sm text-left transition-colors
                  ${o.value === value
                    ? 'bg-primary/10 text-primary font-medium'
                    : 'text-foreground hover:bg-surface'
                  }`}
              >
                {o.label}
                {o.value === value && <Check className="w-3.5 h-3.5 shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Snapshot / diff viewer
// ---------------------------------------------------------------------------

function diffKeys(before: Record<string, unknown> | null, after: Record<string, unknown> | null): Set<string> {
  const changedKeys = new Set<string>();
  if (before && after) {
    const allKeys = new Set([...Object.keys(before), ...Object.keys(after)]);
    for (const k of allKeys) {
      if (JSON.stringify(before[k]) !== JSON.stringify(after[k])) changedKeys.add(k);
    }
  }
  return changedKeys;
}

/** Expanded details body — the row itself is the toggle now. */
function SnapshotBody({
  before, after,
}: {
  before: Record<string, unknown> | null;
  after:  Record<string, unknown> | null;
}) {
  if (!before && !after) {
    return <p className="text-xs text-muted-foreground italic mt-2">No snapshot recorded for this action.</p>;
  }
  const changedKeys = diffKeys(before, after);
  const hasDiff = changedKeys.size > 0;

  return (
      (
        <div className="mt-3 space-y-3">
          {before && after && hasDiff ? (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Changes</p>
              <div className="rounded-lg border border-border/50 overflow-hidden divide-y divide-border/30">
                {Array.from(changedKeys).map(key => (
                  <div key={key} className="grid grid-cols-[1fr_auto_1fr] items-start text-[11px]">
                    <div className="bg-danger/5 px-3 py-2">
                      <span className="text-[9px] text-muted-foreground uppercase tracking-wider block mb-0.5">{key}</span>
                      <span className="text-danger/90 font-mono break-all">{JSON.stringify(before[key])}</span>
                    </div>
                    <div className="flex items-center justify-center px-2 bg-surface text-muted-foreground text-[10px]">→</div>
                    <div className="bg-success/5 px-3 py-2">
                      <span className="text-[9px] text-muted-foreground uppercase tracking-wider block mb-0.5">&nbsp;</span>
                      <span className="text-success/90 font-mono break-all">{JSON.stringify(after[key])}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {before && (
                <div>
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Before</p>
                  <pre className="text-[10px] bg-surface rounded-lg p-2 overflow-x-auto border border-border/50 text-foreground/80 max-h-48">
                    {JSON.stringify(before, null, 2)}
                  </pre>
                </div>
              )}
              {after && (
                <div>
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    {before ? 'After' : 'Snapshot'}
                  </p>
                  <pre className="text-[10px] bg-surface rounded-lg p-2 overflow-x-auto border border-border/50 text-foreground/80 max-h-48">
                    {JSON.stringify(after, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )
  );
}

/** Humanize unmapped action types: "route_sort.wave_distributed" →
 * "Route sort — wave distributed". Mapped labels take precedence. */
function prettyAction(actionType: string): string {
  const mapped = ACTION_LABELS[actionType];
  if (mapped) return mapped;
  const [cat, ...rest] = actionType.split('.');
  const humanize = (s: string) => s.replace(/_/g, ' ');
  const catH = humanize(cat ?? '');
  const restH = humanize(rest.join('.'));
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  return restH ? `${cap(catH)} — ${restH}` : cap(catH);
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(d);  day.setHours(0, 0, 0, 0);
  const diff = Math.round((today.getTime() - day.getTime()) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/** One compact row — possibly a RUN of consecutive identical actions
 * (same action + actor + table), collapsed with a ×N count. The whole row
 * toggles details; repeated one-per-card noise was burying real signal. */
function EntryCard({ group }: { group: AuditEntry[] }) {
  const [open, setOpen] = useState(false);
  const entry   = group[0];
  const variant = getBadgeVariant(entry.action_type);
  const label   = prettyAction(entry.action_type);
  const table   = TABLE_LABELS[entry.target_table] ?? entry.target_table;
  const changed = diffKeys(entry.before_snapshot, entry.after_snapshot);

  return (
    <div className={`card border-l-4 ${LEFT_BORDER_CLASSES[variant]} overflow-hidden`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-accent/30 transition-colors"
      >
        <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold border shrink-0 ${BADGE_CLASSES[variant]}`}>
          {label}
        </span>
        {group.length > 1 && (
          <span className="text-[10px] font-bold text-muted-foreground bg-muted px-1.5 py-0.5 rounded-full shrink-0">
            ×{group.length}
          </span>
        )}
        <span className="text-sm font-medium text-foreground truncate">
          {entry.actor_name ?? <span className="text-muted-foreground italic text-xs">system</span>}
        </span>
        <span className="text-xs text-muted-foreground truncate">{table}</span>
        {changed.size > 0 && !open && (
          <span className="px-1.5 py-0.5 rounded bg-warning/10 text-warning text-[10px] font-semibold border border-warning/20 shrink-0">
            {changed.size} change{changed.size !== 1 ? 's' : ''}
          </span>
        )}
        <span className="ml-auto text-xs text-muted-foreground shrink-0 tabular-nums">
          {group.length > 1
            ? `${fmtTime(group[group.length - 1].created_at)}–${fmtTime(entry.created_at)}`
            : fmtTime(entry.created_at)}
        </span>
        {open ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground shrink-0" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />}
      </button>

      {open && (
        <div className="px-3 pb-3 border-t border-border/30">
          {group.length === 1 ? (
            <SnapshotBody before={entry.before_snapshot} after={entry.after_snapshot} />
          ) : (
            <div className="mt-2 space-y-2">
              {group.map(e => (
                <div key={e.id} className="rounded-lg border border-border/40 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground tabular-nums mb-1">{fmtTime(e.created_at)}</p>
                  <SnapshotBody before={e.before_snapshot} after={e.after_snapshot} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25;

export default function AuditLog() {
  const [entries, setEntries]       = useState<AuditEntry[]>([]);
  const [loading, setLoading]       = useState(true);
  const [page, setPage]             = useState(0);
  const [hasMore, setHasMore]       = useState(false);

  const [category, setCategory]       = useState('');
  const [actorSearch, setActorSearch] = useState('');
  const [startDate, setStartDate]     = useState('');
  const [endDate, setEndDate]         = useState('');

  const load = useCallback(async (pg: number) => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { skip: pg * PAGE_SIZE, limit: PAGE_SIZE + 1 };
      if (category)  params.action_type = category;
      if (startDate) params.start_date  = startDate;
      if (endDate)   params.end_date    = endDate;

      const res = await axiosClient.get<AuditEntry[]>('/audit/', { params });
      let rows = res.data;

      if (actorSearch.trim()) {
        const q = actorSearch.trim().toLowerCase();
        rows = rows.filter(e => e.actor_name?.toLowerCase().includes(q));
      }

      setHasMore(rows.length > PAGE_SIZE);
      setEntries(rows.slice(0, PAGE_SIZE));
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [category, actorSearch, startDate, endDate]);

  useEffect(() => { setPage(0); }, [category, actorSearch, startDate, endDate]);
  useEffect(() => { load(page); }, [page, load]);

  const clearFilters = () => {
    setCategory('');
    setActorSearch('');
    setStartDate('');
    setEndDate('');
  };

  const activeFilters = [category, actorSearch, startDate, endDate].filter(Boolean).length;

  return (
    <div className="space-y-5 animate-slide-up">

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Shield className="w-6 h-6 text-primary" />
            Audit Log
          </h1>
          <p className="text-subtle mt-1">Immutable record of all privileged actions.</p>
        </div>
        <button
          onClick={() => load(page)}
          disabled={loading}
          className="btn-ghost text-xs flex items-center gap-1.5"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Always-visible filter bar */}
      <div className="card p-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Category */}
          <div>
            <label className="label mb-1 text-xs">Category</label>
            <CategoryDropdown
              value={category}
              onChange={setCategory}
              options={ACTION_CATEGORIES}
            />
          </div>

          {/* Actor search */}
          <div>
            <label className="label mb-1 text-xs">Actor</label>
            <div className="relative">
              <User className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                value={actorSearch}
                onChange={e => setActorSearch(e.target.value)}
                placeholder="Search by name…"
                className="input w-full text-sm pl-8"
              />
            </div>
          </div>

          {/* Date range */}
          <div>
            <label className="label mb-1 text-xs">From</label>
            <input
              type="date"
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              className="input w-full text-sm"
            />
          </div>
          <div>
            <label className="label mb-1 text-xs">To</label>
            <div className="relative">
              <input
                type="date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                className="input w-full text-sm"
              />
              {activeFilters > 0 && (
                <button
                  onClick={clearFilters}
                  title="Clear filters"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Entries */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : entries.length === 0 ? (
        <div className="card text-center py-16">
          <Search className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium text-foreground">No entries found</p>
          <p className="text-xs text-muted-foreground mt-1">Try adjusting your filters.</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {(() => {
            // Collapse consecutive identical actions (same action + actor +
            // table) into one ×N row, and insert day separators — five
            // sort.removal_confirmed cards in a row carry one bit of signal.
            const groups: AuditEntry[][] = [];
            for (const e of entries) {
              const last = groups[groups.length - 1];
              if (
                last &&
                last[0].action_type === e.action_type &&
                last[0].actor_name === e.actor_name &&
                last[0].target_table === e.target_table
              ) {
                last.push(e);
              } else {
                groups.push([e]);
              }
            }
            let lastDay = '';
            return groups.map(group => {
              const day = dayLabel(group[0].created_at);
              const separator = day !== lastDay;
              lastDay = day;
              return (
                <React.Fragment key={group[0].id}>
                  {separator && (
                    <div className="flex items-center gap-2 pt-3 pb-1 first:pt-0">
                      <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{day}</span>
                      <div className="h-px bg-border/60 flex-1" />
                    </div>
                  )}
                  <EntryCard group={group} />
                </React.Fragment>
              );
            });
          })()}
        </div>
      )}

      {/* Pagination */}
      {(page > 0 || hasMore) && (
        <div className="flex items-center justify-between pt-1">
          <button
            onClick={() => setPage(p => p - 1)}
            disabled={page === 0}
            className="btn-ghost text-xs flex items-center gap-1 disabled:opacity-40"
          >
            <ChevronLeft className="w-3.5 h-3.5" /> Previous
          </button>
          <span className="text-xs text-muted-foreground">Page {page + 1}</span>
          <button
            onClick={() => setPage(p => p + 1)}
            disabled={!hasMore}
            className="btn-ghost text-xs flex items-center gap-1 disabled:opacity-40"
          >
            Next <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
