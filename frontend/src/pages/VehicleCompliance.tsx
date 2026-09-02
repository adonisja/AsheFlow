import React, { useState, useEffect, useMemo } from 'react';
import axiosClient from '../api/axiosClient';
import {
  ShieldAlert, CheckCircle2, AlertTriangle, XCircle, ChevronDown, ChevronUp,
  Truck, Users, BarChart2,
} from 'lucide-react';
import ErrorBanner from '../components/ui/ErrorBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Inspection {
  inspection_id: string;
  driver_id: string;
  driver_name: string;
  truck_id: string | null;
  truck_name: string | null;
  date: string;
  submitted_at: string | null;
  has_failures: boolean;
  failed_items: string[];
  passed_items: string[];
  notes: string | null;
}

interface FailureSummary {
  days: number;
  since: string;
  total_inspections: number;
  failures: { item: string; label: string; failure_count: number; failure_rate: number }[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmtItem = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

const fmtTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';

const DAYS_OPTIONS = [7, 14, 30, 60, 90];

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------

function KpiCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="card-elevated">
      <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color ?? 'text-foreground'}`}>{value}</p>
      {sub && <p className="text-xs text-subtle mt-0.5">{sub}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Failure Pattern Heatmap — item × truck
// ---------------------------------------------------------------------------

function FailureHeatmap({ inspections }: { inspections: Inspection[] }) {
  const [axis, setAxis] = useState<'truck' | 'driver'>('truck');

  const failed = inspections.filter(i => i.has_failures);

  // Collect unique items and groups (trucks or drivers)
  const items = useMemo(() => {
    const s = new Set<string>();
    failed.forEach(i => i.failed_items.forEach(f => s.add(f)));
    return Array.from(s).sort();
  }, [failed]);

  const groups = useMemo(() => {
    const m = new Map<string, string>(); // id → label
    failed.forEach(i => {
      const id  = axis === 'truck' ? (i.truck_id  ?? 'no-truck')  : i.driver_id;
      const lbl = axis === 'truck' ? (i.truck_name ?? 'No Truck') : i.driver_name;
      m.set(id, lbl);
    });
    return Array.from(m.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [failed, axis]);

  // matrix[groupId][item] = count
  const matrix = useMemo(() => {
    const m: Record<string, Record<string, number>> = {};
    for (const [id] of groups) m[id] = {};
    for (const insp of failed) {
      const id = axis === 'truck' ? (insp.truck_id ?? 'no-truck') : insp.driver_id;
      for (const fi of insp.failed_items) {
        m[id][fi] = (m[id][fi] ?? 0) + 1;
      }
    }
    return m;
  }, [failed, groups, axis]);

  const matrixMax = useMemo(() => {
    let max = 0;
    for (const row of Object.values(matrix))
      for (const v of Object.values(row)) if (v > max) max = v;
    return max || 1;
  }, [matrix]);

  if (items.length === 0) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <BarChart2 className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Failure Pattern Heatmap</h2>
        </div>
        <p className="text-sm text-subtle text-center py-8">No failures in this period.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="flex items-center gap-2 border-b border-border pb-3 mb-4 flex-wrap gap-y-2">
        <BarChart2 className="w-5 h-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground">Failure Pattern Heatmap</h2>
        <p className="text-xs text-subtle ml-1">Row = inspection item · Column = {axis}</p>
        <div className="ml-auto flex items-center gap-1 bg-accent rounded-lg p-1 text-xs">
          {(['truck', 'driver'] as const).map(t => (
            <button
              key={t}
              onClick={() => setAxis(t)}
              className={`px-2.5 py-1 rounded-md font-medium capitalize transition-colors ${axis === t ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
            >
              By {t}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="pb-2 pr-4 text-left text-muted-foreground uppercase tracking-wider w-36">Item</th>
              {groups.map(([id, lbl]) => (
                <th key={id} className="pb-2 px-2 text-center text-muted-foreground font-medium" style={{ minWidth: '5rem' }}>
                  <span className="block truncate max-w-[5rem]" title={lbl}>{lbl}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {items.map(item => (
              <tr key={item}>
                <td className="py-2 pr-4 font-medium text-foreground capitalize">{fmtItem(item)}</td>
                {groups.map(([id]) => {
                  const count = matrix[id]?.[item] ?? 0;
                  const intensity = count / matrixMax;
                  const bg = count > 0 ? `rgba(239,68,68,${0.1 + intensity * 0.4})` : 'transparent';
                  return (
                    <td key={id} className="py-2 px-2 text-center">
                      <span
                        className={`inline-flex items-center justify-center w-10 h-7 rounded text-xs font-bold ${count > 0 ? 'text-danger' : 'text-muted-foreground/30'}`}
                        style={{ background: bg }}
                        title={`${count} failure${count !== 1 ? 's' : ''}`}
                      >
                        {count > 0 ? count : '·'}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center gap-4 mt-4 text-xs text-subtle flex-wrap">
          <span className="flex items-center gap-1.5"><span className="inline-block w-5 h-4 rounded" style={{ background: 'rgba(239,68,68,0.5)' }} /> High frequency</span>
          <span className="flex items-center gap-1.5"><span className="inline-block w-5 h-4 rounded" style={{ background: 'rgba(239,68,68,0.2)' }} /> Low frequency</span>
          <span className="flex items-center gap-1.5"><span className="text-muted-foreground/30">·</span> No failures</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inspection History Table
// ---------------------------------------------------------------------------

function InspectionHistory({
  inspections,
  drivers,
  trucks,
  filterDriver,
  filterTruck,
  filterFailed,
  onFilterDriver,
  onFilterTruck,
  onFilterFailed,
}: {
  inspections: Inspection[];
  drivers: { id: string; name: string }[];
  trucks: { id: string; name: string }[];
  filterDriver: string;
  filterTruck: string;
  filterFailed: string;
  onFilterDriver: (v: string) => void;
  onFilterTruck: (v: string) => void;
  onFilterFailed: (v: string) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const visible = useMemo(() => {
    return inspections.filter(i => {
      if (filterDriver && i.driver_id !== filterDriver) return false;
      if (filterTruck && i.truck_id !== filterTruck) return false;
      if (filterFailed === 'true' && !i.has_failures) return false;
      if (filterFailed === 'false' && i.has_failures) return false;
      return true;
    });
  }, [inspections, filterDriver, filterTruck, filterFailed]);

  return (
    <div className="card">
      <div className="flex items-center gap-2 border-b border-border pb-3 mb-4 flex-wrap gap-y-2">
        <ShieldAlert className="w-5 h-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground">Inspection History</h2>
        <span className="ml-auto text-xs text-subtle">{visible.length} record{visible.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={filterDriver}
          onChange={e => onFilterDriver(e.target.value)}
          className="flex-1 min-w-[140px] p-2 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="">All Drivers</option>
          {drivers.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select
          value={filterTruck}
          onChange={e => onFilterTruck(e.target.value)}
          className="flex-1 min-w-[140px] p-2 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="">All Trucks</option>
          {trucks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select
          value={filterFailed}
          onChange={e => onFilterFailed(e.target.value)}
          className="flex-1 min-w-[120px] p-2 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="">All Results</option>
          <option value="true">Failed Only</option>
          <option value="false">Passed Only</option>
        </select>
      </div>

      {visible.length === 0 ? (
        <div className="text-center py-10 opacity-60">
          <CheckCircle2 className="w-10 h-10 mb-3 text-success mx-auto" />
          <p className="text-sm font-medium">No inspections match the selected filters.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {visible.map(insp => (
            <div
              key={insp.inspection_id}
              className={`rounded-xl border overflow-hidden ${insp.has_failures ? 'border-danger/30' : 'border-border'}`}
            >
              <button
                onClick={() => setExpanded(expanded === insp.inspection_id ? null : insp.inspection_id)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/20 transition-colors"
              >
                {/* Pass/Fail indicator */}
                {insp.has_failures
                  ? <XCircle className="w-4 h-4 text-danger shrink-0" />
                  : <CheckCircle2 className="w-4 h-4 text-success shrink-0" />}

                {/* Driver */}
                <span className="text-sm font-semibold text-foreground w-32 truncate shrink-0">{insp.driver_name}</span>

                {/* Truck */}
                <span className="text-sm text-muted-foreground w-24 truncate shrink-0">
                  {insp.truck_name ?? <span className="italic text-subtle">No truck</span>}
                </span>

                {/* Date */}
                <span className="text-xs text-subtle shrink-0">{insp.date}</span>

                {/* Submitted time */}
                <span className="text-xs text-subtle shrink-0 hidden sm:inline">{fmtTime(insp.submitted_at)}</span>

                {/* Result badge */}
                <span className="ml-auto shrink-0">
                  {insp.has_failures ? (
                    <span className="inline-flex items-center gap-1 text-xs font-bold text-danger bg-danger/10 border border-danger/20 px-2 py-0.5 rounded-full">
                      <AlertTriangle className="w-3 h-3" />
                      {insp.failed_items.length} failed
                    </span>
                  ) : (
                    <span className="text-xs font-bold text-success bg-success/10 border border-success/20 px-2 py-0.5 rounded-full">Passed</span>
                  )}
                </span>

                {expanded === insp.inspection_id
                  ? <ChevronUp className="w-4 h-4 text-subtle shrink-0" />
                  : <ChevronDown className="w-4 h-4 text-subtle shrink-0" />}
              </button>

              {expanded === insp.inspection_id && (
                <div className="px-4 pb-4 pt-3 border-t border-border/50 bg-accent/5 space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {/* Failed items */}
                    {insp.failed_items.length > 0 && (
                      <div className="col-span-full sm:col-span-1">
                        <p className="text-xs font-bold text-danger uppercase tracking-wider mb-2">Failed</p>
                        <div className="flex flex-wrap gap-1.5">
                          {insp.failed_items.map(f => (
                            <span key={f} className="text-xs px-2 py-0.5 rounded-full bg-danger/10 text-danger border border-danger/20 font-medium">
                              {fmtItem(f)}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {/* Passed items */}
                    <div className="col-span-full sm:col-span-2">
                      <p className="text-xs font-bold text-success uppercase tracking-wider mb-2">Passed</p>
                      <div className="flex flex-wrap gap-1.5">
                        {insp.passed_items.map(p => (
                          <span key={p} className="text-xs px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/20 font-medium">
                            {fmtItem(p)}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                  {insp.notes && (
                    <p className="text-xs text-subtle italic border-t border-border/50 pt-3">Notes: {insp.notes}</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function VehicleCompliance() {
  const [days, setDays]             = useState(30);
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [failureSummary, setFailureSummary] = useState<FailureSummary | null>(null);
  const [drivers, setDrivers]       = useState<{ id: string; name: string }[]>([]);
  const [trucks, setTrucks]         = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);

  // Filter state — managed here, passed down to InspectionHistory
  const [filterDriver, setFilterDriver] = useState('');
  const [filterTruck, setFilterTruck]   = useState('');
  const [filterFailed, setFilterFailed] = useState('');

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.allSettled([
      axiosClient.get(`/field-ops/inspections/history?days=${days}`)
        .then(r => setInspections(r.data)),
      axiosClient.get(`/field-ops/inspection-failures/summary?days=${days}`)
        .then(r => setFailureSummary(r.data)),
      axiosClient.get('/employees/?limit=500')
        .then(r => {
          const ds = r.data
            .filter((e: any) => e.role === 'driver')
            .map((e: any) => ({ id: e.id, name: e.name }))
            .sort((a: any, b: any) => a.name.localeCompare(b.name));
          setDrivers(ds);
        }),
      axiosClient.get('/trucks/')
        .then(r => {
          const ts = r.data
            .map((t: any) => ({ id: t.id, name: t.name }))
            .sort((a: any, b: any) => a.name.localeCompare(b.name));
          setTrucks(ts);
        }),
    ]).then(results => {
      if (results.some(r => r.status === 'rejected')) {
        setError('Some compliance data failed to load. Please refresh.');
      }
    }).finally(() => setLoading(false));
  }, [days]);

  // KPI derivations
  const totalInspections = inspections.length;
  const failedInspections = inspections.filter(i => i.has_failures).length;
  const passRate = totalInspections > 0
    ? Math.round(((totalInspections - failedInspections) / totalInspections) * 100)
    : null;

  // Trucks with ≥2 failed inspections in period
  const truckFailureCounts = useMemo(() => {
    const m: Record<string, { name: string; count: number }> = {};
    for (const i of inspections.filter(x => x.has_failures)) {
      const id = i.truck_id ?? 'none';
      if (!m[id]) m[id] = { name: i.truck_name ?? 'No truck', count: 0 };
      m[id].count++;
    }
    return Object.values(m).filter(v => v.count >= 2).sort((a, b) => b.count - a.count);
  }, [inspections]);

  // Drivers with ≥2 failed inspections
  const driverFailureCounts = useMemo(() => {
    const m: Record<string, { name: string; count: number }> = {};
    for (const i of inspections.filter(x => x.has_failures)) {
      if (!m[i.driver_id]) m[i.driver_id] = { name: i.driver_name, count: 0 };
      m[i.driver_id].count++;
    }
    return Object.values(m).filter(v => v.count >= 2).sort((a, b) => b.count - a.count);
  }, [inspections]);

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl gradient-primary shadow-sm shadow-primary/30">
            <ShieldAlert className="w-4 h-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="page-title">Vehicle Compliance</h1>
            <p className="text-subtle mt-0.5">Pre-trip inspection history, failure patterns, and driver accountability.</p>
          </div>
        </div>

        {/* Period selector */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Period:</span>
          <div className="flex items-center gap-1 bg-accent rounded-lg p-1 text-xs">
            {DAYS_OPTIONS.map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-2.5 py-1 rounded-md font-medium transition-colors ${days === d ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      <ErrorBanner message={error} />

      {loading ? (
        <div className="flex h-60 items-center justify-center">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <KpiCard
              label="Total Inspections"
              value={totalInspections}
              sub={`last ${days} days`}
            />
            <KpiCard
              label="Pass Rate"
              value={passRate !== null ? `${passRate}%` : '—'}
              sub={`${totalInspections - failedInspections} passed · ${failedInspections} failed`}
              color={passRate !== null && passRate < 80 ? 'text-danger' : passRate !== null && passRate < 95 ? 'text-warning' : 'text-success'}
            />
            <KpiCard
              label="Trucks w/ Repeat Failures"
              value={truckFailureCounts.length}
              sub={truckFailureCounts.length > 0 ? truckFailureCounts.map(t => t.name).join(', ') : 'none in period'}
              color={truckFailureCounts.length > 0 ? 'text-danger' : 'text-subtle'}
            />
            <KpiCard
              label="Drivers w/ Repeat Failures"
              value={driverFailureCounts.length}
              sub={driverFailureCounts.length > 0 ? driverFailureCounts.map(d => d.name).join(', ') : 'none in period'}
              color={driverFailureCounts.length > 0 ? 'text-warning' : 'text-subtle'}
            />
          </div>

          {/* Top failure items */}
          {failureSummary && failureSummary.failures.length > 0 && (
            <div className="card">
              <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
                <AlertTriangle className="w-5 h-5 text-danger" />
                <h2 className="text-base font-semibold text-foreground">Most Frequently Failed Items</h2>
                <span className="ml-auto text-xs text-subtle">
                  {failureSummary.total_inspections} inspection{failureSummary.total_inspections !== 1 ? 's' : ''} · since {failureSummary.since}
                </span>
              </div>
              <p className="text-xs text-subtle mb-4">
                Each count shows how many pre-trip inspections flagged that item as failed, across all drivers and trucks, in the selected period. A high failure rate on a specific item (e.g. "Brakes — 5 failures, 25% fail rate") means 25% of all inspections submitted this period reported a brake issue, not that one truck has a brake problem. Use the heatmap below to identify which specific truck or driver the failures are concentrated on.
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {failureSummary.failures.map(f => (
                  <div key={f.item} className="p-3 rounded-xl border border-danger/20 bg-danger/5 text-center">
                    <p className="text-xl font-bold text-danger">{f.failure_count}</p>
                    <p className="text-xs font-semibold text-foreground mt-0.5 leading-tight">{f.label}</p>
                    <p className="text-xs text-subtle mt-0.5">{f.failure_rate}% of inspections</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Heatmap */}
          <FailureHeatmap inspections={inspections} />

          {/* Two-column repeat offenders */}
          {(truckFailureCounts.length > 0 || driverFailureCounts.length > 0) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Trucks */}
              <div className="card">
                <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
                  <Truck className="w-5 h-5 text-danger" />
                  <h2 className="text-base font-semibold text-foreground">Trucks with Repeat Failures</h2>
                </div>
                {truckFailureCounts.length === 0 ? (
                  <p className="text-sm text-subtle text-center py-4">No trucks with ≥2 failed inspections.</p>
                ) : (
                  <div className="space-y-2">
                    {truckFailureCounts.map(t => (
                      <div key={t.name} className="flex items-center justify-between px-3 py-2.5 rounded-xl bg-danger/5 border border-danger/15">
                        <span className="text-sm font-medium text-foreground">{t.name}</span>
                        <span className="text-sm font-bold text-danger">{t.count} failed inspection{t.count !== 1 ? 's' : ''}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Drivers */}
              <div className="card">
                <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
                  <Users className="w-5 h-5 text-warning" />
                  <h2 className="text-base font-semibold text-foreground">Drivers with Repeat Failures</h2>
                </div>
                {driverFailureCounts.length === 0 ? (
                  <p className="text-sm text-subtle text-center py-4">No drivers with ≥2 failed inspections.</p>
                ) : (
                  <div className="space-y-2">
                    {driverFailureCounts.map(d => (
                      <div key={d.name} className="flex items-center justify-between px-3 py-2.5 rounded-xl bg-warning/5 border border-warning/15">
                        <span className="text-sm font-medium text-foreground">{d.name}</span>
                        <span className="text-sm font-bold text-warning">{d.count} failed inspection{d.count !== 1 ? 's' : ''}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Full inspection history */}
          <InspectionHistory
            inspections={inspections}
            drivers={drivers}
            trucks={trucks}
            filterDriver={filterDriver}
            filterTruck={filterTruck}
            filterFailed={filterFailed}
            onFilterDriver={v => setFilterDriver(v)}
            onFilterTruck={v => setFilterTruck(v)}
            onFilterFailed={v => setFilterFailed(v)}
          />
        </>
      )}
    </div>
  );
}
