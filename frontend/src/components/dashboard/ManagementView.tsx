import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../../api/axiosClient';
import { useAuth } from '../../contexts/AuthContext';
import {
  AlertTriangle, BarChart2, ClipboardCheck, Star, Truck, Users, ShieldAlert, CheckCircle2,
  LayoutDashboard, RefreshCw, Package, MapPin, LogIn,
} from 'lucide-react';

export default function ManagementView() {
  const { user } = useAuth();
  const greeting = new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening';
  const [incidentSummary, setIncidentSummary] = useState<any>(null);
  const [walkerStats, setWalkerStats] = useState<any[]>([]);
  const [noShows, setNoShows] = useState<any[]>([]);
  const [trainingPipeline, setTrainingPipeline] = useState<any>(null);
  const [inspectionFailures, setInspectionFailures] = useState<any>(null);
  const [todayInspections, setTodayInspections]     = useState<any[]>([]);
  const [truckStatuses, setTruckStatuses] = useState<{ truck_id: string; status: string }[]>([]);
  const [checkInSummary, setCheckInSummary]   = useState<any>(null);
  const [handoffSummary, setHandoffSummary]   = useState<any>(null);
  const [pendingRTS, setPendingRTS]           = useState<any[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const loadAll = useCallback(async () => {
    setIsRefreshing(true);
    const today = new Date().toISOString().slice(0, 10);
    await Promise.allSettled([
      axiosClient.get('/incidents/summary?days=7').then(r => setIncidentSummary(r.data)),
      axiosClient.get('/field-ops/walker-stats').then(r => setWalkerStats(r.data)),
      axiosClient.get('/field-ops/no-shows').then(r => setNoShows(r.data)),
      axiosClient.get('/training/pipeline-summary').then(r => setTrainingPipeline(r.data)),
      axiosClient.get('/field-ops/inspection-failures/summary?days=7').then(r => setInspectionFailures(r.data)),
      axiosClient.get('/field-ops/inspections/summary').then(r => setTodayInspections(r.data)),
      axiosClient.get(`/dispatch/${today}`).then(r => setTruckStatuses(r.data.truck_assignments ?? [])).catch(() => {}),
      axiosClient.get('/shift-ops/check-ins/summary').then(r => setCheckInSummary(r.data)).catch(() => {}),
      axiosClient.get('/shift-ops/station-handoffs/summary').then(r => setHandoffSummary(r.data)).catch(() => {}),
      axiosClient.get('/shift-ops/rts-reports/pending').then(r => setPendingRTS(r.data)).catch(() => {}),
    ]);
    setIsRefreshing(false);
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const plannedCount   = truckStatuses.filter(t => t.status === 'planned').length;
  const activeCount    = truckStatuses.filter(t => t.status === 'active').length;
  const completedCount = truckStatuses.filter(t => t.status === 'completed').length;

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl gradient-primary shadow-sm shadow-primary/30">
            <LayoutDashboard className="w-4 h-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="page-title">Good {greeting}, {user?.displayName || user?.username}</h1>
            <p className="text-subtle mt-0.5">Management overview for {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}.</p>
          </div>
        </div>
        <button
          onClick={loadAll}
          disabled={isRefreshing}
          className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40"
          title="Refresh dashboard"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          {
            label: 'Active Trainees',
            value: trainingPipeline?.active_trainees ?? '—',
            sub: `${trainingPipeline?.training_sessions_today ?? 0} sessions today`,
            icon: Users,
            color: 'text-info',
          },
          {
            label: 'Incidents (7d)',
            value: incidentSummary?.total ?? '—',
            sub: `${incidentSummary?.unresolved ?? 0} unresolved`,
            icon: AlertTriangle,
            color: (incidentSummary?.unresolved ?? 0) > 0 ? 'text-danger' : 'text-success',
          },
          {
            label: 'Fleet Today',
            value: truckStatuses.length === 0 ? '—' : `${activeCount + completedCount}/${truckStatuses.length}`,
            sub: truckStatuses.length === 0
              ? 'dispatch not run yet'
              : `${activeCount} out · ${completedCount} returned · ${plannedCount} pending`,
            icon: Truck,
            color: activeCount > 0 ? 'text-warning' : completedCount > 0 ? 'text-success' : 'text-muted-foreground',
          },
          {
            label: 'Escalated Trainees',
            value: trainingPipeline?.escalated_count ?? '—',
            sub: 'need manager review',
            icon: ClipboardCheck,
            color: (trainingPipeline?.escalated_count ?? 0) > 0 ? 'text-warning' : 'text-success',
          },
        ].map(stat => (
          <div key={stat.label} className="card-elevated flex items-center gap-4">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-accent shrink-0">
              <stat.icon className={`w-5 h-5 ${stat.color}`} />
            </div>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
              <p className="text-lg font-bold text-foreground mt-0.5">{stat.value}</p>
              <p className="text-xs text-subtle">{stat.sub}</p>
            </div>
          </div>
        ))}
      </div>

      {/* 3-column reporting panels */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Incident trend */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <BarChart2 className="w-5 h-5 text-warning" />
            <h2 className="text-base font-semibold text-foreground">Incident Trend (7d)</h2>
          </div>
          {!incidentSummary ? (
            <p className="text-sm text-subtle text-center py-6">Loading…</p>
          ) : (
            <div className="space-y-3">
              {/* Severity breakdown */}
              <div className="grid grid-cols-3 gap-2 text-center">
                {[
                  { key: 'critical', label: 'Critical', color: 'text-danger' },
                  { key: 'warning', label: 'Warning', color: 'text-warning' },
                  { key: 'info', label: 'Info', color: 'text-info' },
                ].map(s => (
                  <div key={s.key} className="p-2 rounded-lg bg-accent/30">
                    <p className={`text-xl font-bold ${s.color}`}>{incidentSummary.by_severity[s.key] ?? 0}</p>
                    <p className="text-xs text-subtle">{s.label}</p>
                  </div>
                ))}
              </div>
              {/* Top categories */}
              {incidentSummary.by_category.length > 0 ? (
                <div className="space-y-2 pt-1">
                  <p className="text-xs text-subtle uppercase tracking-wider font-medium">By Category</p>
                  {incidentSummary.by_category.slice(0, 5).map((c: any) => (
                    <div key={c.category} className="flex items-center justify-between">
                      <span className="text-sm text-foreground truncate">{c.label}</span>
                      <span className="text-sm font-semibold text-foreground ml-2">{c.count}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-subtle text-center pt-4">No incidents in the last 7 days.</p>
              )}
              <a href="/incidents" className="block text-center text-xs text-primary hover:underline pt-1">View all →</a>
            </div>
          )}
        </div>

        {/* Walker performance */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <Star className="w-5 h-5 text-primary" />
            <h2 className="text-base font-semibold text-foreground">Walker Performance (This Week)</h2>
          </div>
          {noShows.length > 0 && (
            <div className="mb-3 p-2 rounded-lg bg-danger/10 border border-danger/20">
              <p className="text-xs font-bold text-danger uppercase tracking-wider mb-1">Today's No-Shows</p>
              {noShows.map(ns => (
                <p key={ns.walker_id} className="text-sm text-foreground">
                  {ns.walker_name} <span className="text-subtle">· {ns.driver_name}</span>
                </p>
              ))}
            </div>
          )}
          {walkerStats.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No walker data this week.</p>
          ) : (
            <div className="space-y-2 max-h-[220px] overflow-y-auto">
              {walkerStats.map(w => (
                <div key={w.walker_id} className="flex items-center justify-between gap-2 p-2 rounded-lg hover:bg-accent/30 transition-colors">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{w.walker_name}</p>
                    <p className="text-xs text-subtle">{w.presence_rate}% present · {w.no_show_count} absent</p>
                  </div>
                  <div className="text-right shrink-0">
                    {w.avg_stars != null ? (
                      <p className="text-sm font-bold text-foreground">{w.avg_stars.toFixed(1)} ★</p>
                    ) : (
                      <p className="text-xs text-subtle">N/A</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          <a href="/walker-performance" className="block text-center text-xs text-primary hover:underline pt-3">View all-time grades & history →</a>
        </div>

        {/* Training pipeline */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <ClipboardCheck className="w-5 h-5 text-info" />
            <h2 className="text-base font-semibold text-foreground">Training Pipeline</h2>
          </div>
          {!trainingPipeline ? (
            <p className="text-sm text-subtle text-center py-6">Loading…</p>
          ) : (
            <div className="space-y-4">
              {trainingPipeline.escalated_count > 0 && (
                <div className="p-2 rounded-lg bg-warning/10 border border-warning/20">
                  <p className="text-xs font-bold text-warning uppercase tracking-wider">
                    {trainingPipeline.escalated_count} escalated trainee{trainingPipeline.escalated_count !== 1 ? 's' : ''}
                  </p>
                  <p className="text-xs text-subtle mt-0.5">Review required in Trainee Hub</p>
                </div>
              )}
              {trainingPipeline.trainer_loads.length === 0 ? (
                <p className="text-sm text-subtle text-center py-4">No training sessions today.</p>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-subtle uppercase tracking-wider font-medium">Trainer Load Today</p>
                  {trainingPipeline.trainer_loads.map((t: any) => (
                    <div key={t.trainer_id} className="flex items-center justify-between">
                      <span className="text-sm text-foreground truncate">{t.trainer_name}</span>
                      <span className="text-xs font-semibold text-foreground bg-accent px-2 py-0.5 rounded-full">
                        {t.trainee_count} trainee{t.trainee_count !== 1 ? 's' : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <a href="/trainee-management" className="block text-center text-xs text-primary hover:underline pt-1">Trainee Hub →</a>
            </div>
          )}
        </div>
      </div>

      {/* Today's inspection results */}
      <div className="card border-border/60">
        <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
          <ShieldAlert className="w-5 h-5 text-warning" />
          <h2 className="text-base font-semibold text-foreground">Vehicle Inspections — Today</h2>
          {todayInspections.length > 0 && (
            <span className="ml-auto text-xs text-subtle">
              {todayInspections.filter((i: any) => i.has_failures).length} failed ·{' '}
              {todayInspections.filter((i: any) => !i.has_failures).length} passed
            </span>
          )}
        </div>

        {todayInspections.length === 0 ? (
          <p className="text-sm text-subtle text-center py-6">No inspections submitted today.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-4">Driver</th>
                  <th className="pb-2 pr-4">Truck</th>
                  <th className="pb-2 pr-4">Type</th>
                  <th className="pb-2 pr-4">Submitted</th>
                  <th className="pb-2 pr-4">Result</th>
                  <th className="pb-2">Failed Items</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {todayInspections.map((insp: any) => (
                  <tr key={insp.inspection_id} className={insp.has_failures ? 'bg-danger/5' : ''}>
                    <td className="py-2 pr-4 font-medium text-foreground whitespace-nowrap">{insp.driver_name}</td>
                    <td className="py-2 pr-4 text-muted-foreground whitespace-nowrap">{insp.truck_name ?? '—'}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        insp.inspection_type === 'eod'
                          ? 'bg-info/10 text-info'
                          : 'bg-primary/10 text-primary'
                      }`}>
                        {insp.inspection_type === 'eod' ? 'EOD' : 'Pre-Trip'}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-muted-foreground whitespace-nowrap text-xs">
                      {insp.submitted_at
                        ? new Date(insp.submitted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        : '—'}
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      {insp.has_failures ? (
                        <span className="inline-flex items-center gap-1 text-danger text-xs font-semibold">
                          <AlertTriangle className="w-3 h-3" /> Failed
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-success text-xs font-semibold">
                          <CheckCircle2 className="w-3 h-3" /> Passed
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-xs text-danger">
                      {insp.has_failures && insp.failed_items?.length > 0
                        ? insp.failed_items.map((item: string) =>
                            item.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())
                          ).join(', ')
                        : <span className="text-subtle">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Shift ops summary — check-ins, handoffs, RTS */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Driver check-ins */}
        <div className="card border-border/60">
          <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
            <LogIn className="w-5 h-5 text-info" />
            <h2 className="text-base font-semibold text-foreground">Driver Check-Ins Today</h2>
          </div>
          {!checkInSummary ? (
            <p className="text-sm text-subtle text-center py-6">No check-in data yet.</p>
          ) : checkInSummary.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No check-ins submitted today.</p>
          ) : (
            <div className="space-y-2 max-h-[200px] overflow-y-auto">
              {checkInSummary.map((ci: any) => (
                <div key={ci.driver_id} className="flex items-center justify-between gap-2 p-2 rounded-lg hover:bg-accent/30 transition-colors">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{ci.driver_name}</p>
                    <p className="text-xs text-subtle">Check-in #{ci.latest_check_in} · {ci.routes_remaining} routes left</p>
                  </div>
                  {ci.help_requested && (
                    <span className="text-xs font-semibold text-danger shrink-0">Help</span>
                  )}
                </div>
              ))}
            </div>
          )}
          <a href="/field-ops" className="block text-center text-xs text-primary hover:underline pt-3">Field Ops →</a>
        </div>

        {/* RTS pending queue */}
        <div className="card border-border/60">
          <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
            <Package className="w-5 h-5 text-warning" />
            <h2 className="text-base font-semibold text-foreground">RTS Return Requests</h2>
            {pendingRTS.length > 0 && (
              <span className="ml-auto inline-flex items-center justify-center w-5 h-5 rounded-full bg-warning text-warning-foreground text-xs font-bold">
                {pendingRTS.length}
              </span>
            )}
          </div>
          {pendingRTS.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No pending RTS requests.</p>
          ) : (
            <div className="space-y-2 max-h-[200px] overflow-y-auto">
              {pendingRTS.map((r: any) => (
                <div key={r.driver_id} className="p-2 rounded-lg border border-warning/20 bg-warning/5">
                  <p className="text-sm font-medium text-foreground">{r.driver_name}</p>
                  <p className="text-xs text-subtle">
                    {r.crew_confirmed} crew confirmed · {r.total_rts} RTS packages
                  </p>
                </div>
              ))}
            </div>
          )}
          <a href="/dispatch" className="block text-center text-xs text-primary hover:underline pt-3">Manage in Dispatch →</a>
        </div>

        {/* Station handoffs */}
        <div className="card border-border/60">
          <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
            <MapPin className="w-5 h-5 text-success" />
            <h2 className="text-base font-semibold text-foreground">Station Handoffs Today</h2>
            {handoffSummary?.drivers?.length > 0 && (
              <span className="ml-auto text-xs text-subtle">
                {handoffSummary.total_totes_returned}T · {handoffSummary.total_rts_returned} RTS
              </span>
            )}
          </div>
          {!handoffSummary || handoffSummary.drivers?.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No handoffs completed today.</p>
          ) : (
            <div className="space-y-2 max-h-[200px] overflow-y-auto">
              {handoffSummary.drivers.map((h: any) => (
                <div key={h.driver_id} className="flex items-center justify-between gap-2 p-2 rounded-lg hover:bg-accent/30 transition-colors">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{h.driver_name}</p>
                    <p className="text-xs text-subtle">{h.totes_returned} totes · {h.rts_count} RTS</p>
                  </div>
                  <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Inspection failure patterns */}
      <div className="card border-border/60">
        <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
          <Truck className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Inspection Failure Patterns (7d)</h2>
          {inspectionFailures && (
            <span className="ml-auto text-xs text-subtle">
              {inspectionFailures.total_inspections} inspection{inspectionFailures.total_inspections !== 1 ? 's' : ''} submitted
            </span>
          )}
        </div>
        {!inspectionFailures ? (
          <p className="text-sm text-subtle text-center py-6">Loading…</p>
        ) : inspectionFailures.failures.length === 0 ? (
          <p className="text-sm text-subtle text-center py-6">No inspection failures in the last 7 days.</p>
        ) : (
          <>
            <p className="text-xs text-subtle mb-4">
              How many inspections flagged each item as failed across all drivers and trucks this week.
              A high fail rate signals a recurring mechanical issue — visit <a href="/vehicle-compliance" className="text-primary hover:underline">Vehicle Compliance</a> to see which trucks and drivers are responsible.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {inspectionFailures.failures.map((f: any) => (
                <div key={f.item} className="p-3 rounded-xl border border-danger/20 bg-danger/5 text-center">
                  <p className="text-lg font-bold text-danger">{f.failure_count}</p>
                  <p className="text-xs font-medium text-foreground mt-0.5 leading-tight">{f.label}</p>
                  <p className="text-xs text-subtle mt-0.5">{f.failure_rate}% of inspections</p>
                </div>
              ))}
            </div>
            <a href="/vehicle-compliance" className="block text-center text-xs text-primary hover:underline pt-4">View full compliance report →</a>
          </>
        )}
      </div>
    </div>
  );
}
