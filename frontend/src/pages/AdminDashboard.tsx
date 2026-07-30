import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import {
  Shield, RefreshCw, AlertTriangle, CheckCircle2, Clock, PlugZap, ClipboardCheck,
} from 'lucide-react';
import type { AdminDashboardSummary } from '../api/types';
import { pct, count, hours, shortDate } from '../utils/metric';

/** ADP connection state → user-facing pill. */
function adpPill(status: string): { text: string; cls: string } {
  switch (status) {
    case 'connected':
      return { text: 'Connected', cls: 'bg-success/10 text-success border-success/20' };
    case 'stale':
      return { text: 'Stale (>24h)', cls: 'bg-warning/10 text-warning border-warning/20' };
    case 'never_synced':
      return { text: 'Never synced', cls: 'bg-warning/10 text-warning border-warning/20' };
    case 'disabled':
      return { text: 'Disabled', cls: 'bg-accent text-muted-foreground border-border' };
    default:
      return { text: 'Not configured', cls: 'bg-accent text-muted-foreground border-border' };
  }
}

export default function AdminDashboard() {
  const [summary, setSummary] = useState<AdminDashboardSummary | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      const res = await axiosClient.get('/dashboards/admin/summary');
      setSummary(res.data);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e.response?.data?.detail || e.message || 'Failed to load dashboard');
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (error) {
    return (
      <div className="text-center py-10 space-y-3">
        <p className="text-danger font-semibold">Could not load dashboard</p>
        <p className="text-subtle text-sm">{error}</p>
        <button onClick={loadDashboard} className="btn-primary text-sm">Retry</button>
      </div>
    );
  }

  if (!summary) {
    return <div className="text-center py-10 text-subtle">Loading dashboard…</div>;
  }

  const { system_health: sys, compliance: comp } = summary;
  const pill = adpPill(sys.adp_status);
  const flexStale = (sys.flex_data_freshness_hours ?? 0) > 24;

  return (
    <div className="space-y-4 sm:space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-start gap-2 sm:gap-3 min-w-0">
          <div className="flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 rounded-lg sm:rounded-xl bg-accent shrink-0">
            <Shield className="w-4 h-4 sm:w-5 sm:h-5 text-foreground" />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg sm:text-2xl font-bold text-foreground">Admin</h1>
            <p className="text-xs sm:text-sm text-subtle mt-0.5">
              Integration health &amp; compliance
            </p>
          </div>
        </div>
        <button
          onClick={loadDashboard}
          disabled={isRefreshing}
          className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40 p-1.5 sm:p-2 shrink-0"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Integrations */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <PlugZap className="w-4 h-4 sm:w-5 sm:h-5 text-info shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">Integrations</h2>
        </div>

        <div className="space-y-2 sm:space-y-3">
          {/* ADP */}
          <div className="p-2 sm:p-3 rounded-lg bg-accent/20 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs sm:text-sm font-medium text-foreground">ADP Workforce Now</span>
              <span
                className={`text-xs font-semibold px-2 py-0.5 rounded-full border shrink-0 ${pill.cls}`}
              >
                {pill.text}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-1 sm:gap-2 text-xs text-subtle">
              <span>Roster sync: {shortDate(sys.adp_last_employee_sync)}</span>
              <span>Timecard sync: {shortDate(sys.adp_last_timecard_sync)}</span>
              <span className="tabular-nums">
                {count(sys.adp_verified_employee_count)} verified employees
              </span>
            </div>
          </div>

          {/* Flex */}
          <div className="p-2 sm:p-3 rounded-lg bg-accent/20 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs sm:text-sm font-medium text-foreground">
                Flex timesheets &amp; manifests
              </span>
              <span
                className={`text-xs font-semibold px-2 py-0.5 rounded-full border shrink-0 ${
                  sys.flex_last_upload == null
                    ? 'bg-accent text-muted-foreground border-border'
                    : flexStale
                    ? 'bg-warning/10 text-warning border-warning/20'
                    : 'bg-success/10 text-success border-success/20'
                }`}
              >
                {sys.flex_last_upload == null
                  ? 'No uploads'
                  : flexStale
                  ? 'Stale'
                  : 'Fresh'}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-1 sm:gap-2 text-xs text-subtle">
              <span>Last upload: {shortDate(sys.flex_last_upload)}</span>
              <span className="tabular-nums">
                Age: {hours(sys.flex_data_freshness_hours)}
              </span>
              <span className="tabular-nums">
                {count(sys.manifest_count_today)} manifests today
              </span>
            </div>
          </div>

          {/* Misroutes */}
          <div className="flex items-center justify-between p-2 sm:p-3 rounded-lg bg-accent/20">
            <span className="text-xs sm:text-sm text-foreground">Unresolved misroutes</span>
            <span
              className={`text-sm font-bold tabular-nums ${
                sys.unresolved_misroute_count > 0 ? 'text-warning' : 'text-success'
              }`}
            >
              {count(sys.unresolved_misroute_count)}
            </span>
          </div>
        </div>
      </div>

      {/* Compliance */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <ClipboardCheck className="w-4 h-4 sm:w-5 sm:h-5 text-success shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">Compliance</h2>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
          {[
            {
              label: 'Graduation',
              value: pct(comp.graduation_completion_pct),
              note: `${count(comp.active_trainee_count)} active`,
              tone: 'text-info',
            },
            {
              label: 'Escalated',
              value: count(comp.escalated_trainee_count),
              note: 'trainees',
              tone: comp.escalated_trainee_count > 0 ? 'text-warning' : 'text-success',
            },
            {
              label: 'Inspect Pass',
              value: pct(comp.vehicle_inspection_pass_rate_7d),
              note: `${count(comp.inspections_submitted_7d)} in 7d`,
              tone: 'text-success',
            },
            {
              label: 'Incidents 7d',
              value: count(comp.incident_7d_count),
              note: `${count(comp.critical_incident_count)} critical open`,
              tone: comp.critical_incident_count > 0 ? 'text-danger' : 'text-success',
            },
          ].map((s) => (
            <div key={s.label} className="p-2 sm:p-3 rounded-lg bg-accent/20">
              <p className="text-xs text-muted-foreground uppercase tracking-wider truncate">
                {s.label}
              </p>
              <p className={`text-lg sm:text-2xl font-bold mt-0.5 tabular-nums ${s.tone}`}>
                {s.value}
              </p>
              <p className="text-xs text-subtle truncate">{s.note}</p>
            </div>
          ))}
        </div>

        {comp.days_since_last_training_record != null && (
          <p className="mt-3 text-xs text-subtle flex items-center gap-1">
            <Clock className="w-3 h-3" />
            Last training record {count(comp.days_since_last_training_record)} days ago
          </p>
        )}
      </div>

      {/* Failed inspection items — real JSONB scan, no longer hardcoded */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-warning shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">
            Failing Inspection Items (7d)
          </h2>
        </div>
        {comp.failed_items_trending.length === 0 ? (
          <p className="text-xs sm:text-sm text-subtle text-center py-4 flex items-center justify-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-success" />
            No failed inspection items
          </p>
        ) : (
          <div className="space-y-1.5">
            {comp.failed_items_trending.map((f) => (
              <div key={f.item_name} className="flex items-center justify-between gap-2">
                <span className="text-xs sm:text-sm text-foreground truncate">{f.item_name}</span>
                <span className="text-xs sm:text-sm font-semibold text-warning shrink-0 tabular-nums">
                  {count(f.failure_count)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 30-day incident trend — one GROUP BY on the backend */}
      {comp.incident_30d_trend.length > 0 && (
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-danger shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">
              Incident Trend (30d)
            </h2>
            <span className="ml-auto text-xs text-subtle tabular-nums">
              {count(comp.unresolved_incident_count)} unresolved
            </span>
          </div>
          <div className="flex items-end gap-1 h-24 overflow-x-auto">
            {(() => {
              const max = Math.max(...comp.incident_30d_trend.map((t) => t.count), 1);
              return comp.incident_30d_trend.map((t) => (
                <div
                  key={t.date}
                  className="flex-1 min-w-[6px] bg-danger/60 rounded-t hover:bg-danger transition-colors"
                  style={{ height: `${(t.count / max) * 100}%` }}
                  title={`${t.date}: ${t.count}`}
                />
              ));
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
