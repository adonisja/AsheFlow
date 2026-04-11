import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  AlertTriangle, BarChart2, ClipboardCheck, Star, Truck, Users,
} from 'lucide-react';

const API = 'http://localhost:8000/api/v1';

export default function ManagementView() {
  const [incidentSummary, setIncidentSummary] = useState<any>(null);
  const [walkerStats, setWalkerStats] = useState<any[]>([]);
  const [noShows, setNoShows] = useState<any[]>([]);
  const [trainingPipeline, setTrainingPipeline] = useState<any>(null);
  const [inspectionFailures, setInspectionFailures] = useState<any>(null);
  const [fleetStatus, setFleetStatus] = useState<any[]>([]);

  useEffect(() => {
    axios.get(`${API}/incidents/summary?days=7`).then(r => setIncidentSummary(r.data)).catch(console.error);
    axios.get(`${API}/field-ops/walker-stats`).then(r => setWalkerStats(r.data)).catch(console.error);
    axios.get(`${API}/field-ops/no-shows`).then(r => setNoShows(r.data)).catch(console.error);
    axios.get(`${API}/training/pipeline-summary`).then(r => setTrainingPipeline(r.data)).catch(console.error);
    axios.get(`${API}/field-ops/inspection-failures/summary?days=7`).then(r => setInspectionFailures(r.data)).catch(console.error);
    axios.get(`${API}/field-ops/returns/summary`).then(r => setFleetStatus(r.data)).catch(console.error);
  }, []);

  const returnedCount = fleetStatus.filter(d => d.status === 'returned').length;
  const outCount = fleetStatus.length - returnedCount;

  return (
    <div className="space-y-6">
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
            value: `${returnedCount}/${fleetStatus.length}`,
            sub: `${outCount} still out`,
            icon: Truck,
            color: outCount > 0 ? 'text-warning' : 'text-success',
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
            <div className="space-y-2 max-h-[260px] overflow-y-auto">
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

      {/* Vehicle compliance */}
      <div className="card border-border/60">
        <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
          <Truck className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Vehicle Compliance (7d)</h2>
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
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {inspectionFailures.failures.map((f: any) => (
              <div key={f.item} className="p-3 rounded-xl border border-danger/20 bg-danger/5 text-center">
                <p className="text-lg font-bold text-danger">{f.failure_count}</p>
                <p className="text-xs font-medium text-foreground mt-0.5 leading-tight">{f.label}</p>
                <p className="text-xs text-subtle mt-0.5">{f.failure_rate}% fail rate</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
