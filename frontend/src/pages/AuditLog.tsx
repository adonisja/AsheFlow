import React, { useState, useEffect, useCallback } from 'react';
import { Shield, ChevronLeft, ChevronRight, RefreshCw, Filter, X, ChevronDown, ChevronUp } from 'lucide-react';
import axiosClient from '../api/axiosClient';

interface AuditEntry {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action_type: string;
  target_table: string;
  target_id: string;
  before_snapshot: Record<string, unknown> | null;
  after_snapshot: Record<string, unknown> | null;
  created_at: string;
}

const ACTION_TYPE_PREFIXES = [
  { value: '', label: 'All actions' },
  { value: 'pto', label: 'PTO' },
  { value: 'incident', label: 'Incidents' },
  { value: 'dispatch', label: 'Dispatch' },
  { value: 'employee', label: 'Employees' },
  { value: 'training', label: 'Training' },
  { value: 'schedule', label: 'Schedule' },
  { value: 'gear', label: 'Gear' },
];

const PAGE_SIZE = 25;

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}

function actionBadgeClass(type: string) {
  if (type.includes('approved') || type.includes('graduated') || type.includes('created')) return 'bg-success/10 text-success border-success/20';
  if (type.includes('rejected') || type.includes('removed') || type.includes('deleted')) return 'bg-danger/10 text-danger border-danger/20';
  if (type.includes('override') || type.includes('escalat')) return 'bg-warning/10 text-warning border-warning/20';
  return 'bg-primary/10 text-primary border-primary/20';
}

function SnapshotViewer({ before, after }: { before: Record<string, unknown> | null; after: Record<string, unknown> | null }) {
  const [open, setOpen] = useState(false);
  if (!before && !after) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {open ? 'Hide' : 'Show'} snapshot
      </button>
      {open && (
        <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
          {before && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Before</p>
              <pre className="text-[10px] bg-surface rounded-lg p-2 overflow-x-auto border border-border/50 text-foreground/80 max-h-40">
                {JSON.stringify(before, null, 2)}
              </pre>
            </div>
          )}
          {after && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">After</p>
              <pre className="text-[10px] bg-surface rounded-lg p-2 overflow-x-auto border border-border/50 text-foreground/80 max-h-40">
                {JSON.stringify(after, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AuditLog() {
  const [entries, setEntries]   = useState<AuditEntry[]>([]);
  const [loading, setLoading]   = useState(true);
  const [page, setPage]         = useState(0);
  const [hasMore, setHasMore]   = useState(false);

  const [actionType, setActionType] = useState('');
  const [targetTable, setTargetTable] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  const load = useCallback(async (pg: number) => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { skip: pg * PAGE_SIZE, limit: PAGE_SIZE + 1 };
      if (actionType)  params.action_type  = actionType;
      if (targetTable) params.target_table = targetTable;
      if (startDate)   params.start_date   = startDate;
      if (endDate)     params.end_date     = endDate;

      const res = await axiosClient.get<AuditEntry[]>('/audit/', { params });
      const rows = res.data;
      setHasMore(rows.length > PAGE_SIZE);
      setEntries(rows.slice(0, PAGE_SIZE));
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [actionType, targetTable, startDate, endDate]);

  useEffect(() => {
    setPage(0);
  }, [actionType, targetTable, startDate, endDate]);

  useEffect(() => {
    load(page);
  }, [page, load]);

  const clearFilters = () => {
    setActionType('');
    setTargetTable('');
    setStartDate('');
    setEndDate('');
  };

  const hasFilters = actionType || targetTable || startDate || endDate;

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Shield className="w-6 h-6 text-primary" />
            Audit Log
          </h1>
          <p className="text-subtle mt-1">Immutable record of all privileged actions.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => load(page)}
            disabled={loading}
            className="btn-ghost text-xs flex items-center gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={() => setShowFilters(o => !o)}
            className={`btn-ghost text-xs flex items-center gap-1.5 ${hasFilters ? 'text-primary' : ''}`}
          >
            <Filter className="w-3.5 h-3.5" />
            Filters
            {hasFilters && (
              <span className="flex items-center justify-center w-4 h-4 rounded-full bg-primary text-primary-foreground text-[10px] font-bold">
                {[actionType, targetTable, startDate, endDate].filter(Boolean).length}
              </span>
            )}
          </button>
        </div>
      </div>

      {showFilters && (
        <div className="card p-4 space-y-4 animate-slide-up">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="label mb-1">Action type</label>
              <select
                value={actionType}
                onChange={e => setActionType(e.target.value)}
                className="input w-full text-sm"
              >
                {ACTION_TYPE_PREFIXES.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label mb-1">Target table</label>
              <input
                type="text"
                value={targetTable}
                onChange={e => setTargetTable(e.target.value)}
                placeholder="e.g. employees"
                className="input w-full text-sm"
              />
            </div>
            <div>
              <label className="label mb-1">From date</label>
              <input
                type="date"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                className="input w-full text-sm"
              />
            </div>
            <div>
              <label className="label mb-1">To date</label>
              <input
                type="date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                className="input w-full text-sm"
              />
            </div>
          </div>
          {hasFilters && (
            <button onClick={clearFilters} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
              <X className="w-3.5 h-3.5" /> Clear all filters
            </button>
          )}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : entries.length === 0 ? (
        <div className="card text-center py-12">
          <Shield className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
          <p className="text-muted-foreground text-sm">No audit entries found.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map(entry => (
            <div key={entry.id} className="card p-4">
              <div className="flex items-start gap-3 flex-wrap">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold border shrink-0 ${actionBadgeClass(entry.action_type)}`}>
                  {entry.action_type}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-foreground">
                      {entry.actor_name ?? <span className="text-muted-foreground italic">system</span>}
                    </span>
                    <span className="text-xs text-muted-foreground">→ {entry.target_table}</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-0.5 font-mono truncate">{entry.target_id}</p>
                </div>
                <span className="text-xs text-muted-foreground shrink-0">{fmtDate(entry.created_at)}</span>
              </div>
              <SnapshotViewer before={entry.before_snapshot} after={entry.after_snapshot} />
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {(page > 0 || hasMore) && (
        <div className="flex items-center justify-between">
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
