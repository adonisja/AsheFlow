import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import {
  AlertTriangle, Star, Truck, Users, LayoutDashboard, RefreshCw, Package,
  TrendingUp, TrendingDown, Minus, MapPin,
} from 'lucide-react';
import type { ManagementDashboardSummary } from '../api/types';
import { pct, metric, count, stars, hours, trendLabel } from '../utils/metric';

type Period = 'today' | 'week' | 'month';

/** Trend arrow. A null trend means no prior-period data — shown as a neutral dash. */
function Trend({ dir }: { dir?: string | null }) {
  const cls = 'w-3 h-3 shrink-0';
  if (dir === 'up') return <TrendingUp className={`${cls} text-success`} />;
  if (dir === 'down') return <TrendingDown className={`${cls} text-danger`} />;
  if (dir === 'flat') return <Minus className={`${cls} text-muted-foreground`} />;
  return <Minus className={`${cls} text-muted-foreground/40`} />;
}

export default function ManagementDashboard() {
  const { user } = useAuth();
  const greeting =
    new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening';

  const [summary, setSummary] = useState<ManagementDashboardSummary | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>('week');

  const loadDashboard = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      const res = await axiosClient.get(`/dashboards/management/summary?period=${period}`);
      setSummary(res.data);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e.response?.data?.detail || e.message || 'Failed to load dashboard');
    } finally {
      setIsRefreshing(false);
    }
  }, [period]);

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

  const { operational: op, crew, incidents, fleet } = summary;

  const kpis = [
    {
      label: 'Packages/Hour',
      value: metric(op.packages_per_hour),
      trend: op.trend_packages_per_hour,
      note: op.prior_packages_per_hour != null
        ? `was ${metric(op.prior_packages_per_hour)}`
        : trendLabel(op.trend_packages_per_hour).label,
      icon: Package,
      tone: 'text-info',
    },
    {
      label: 'Delivery Success',
      value: pct(op.delivery_success_rate_pct),
      trend: op.trend_success_rate,
      note: op.prior_success_rate_pct != null
        ? `was ${pct(op.prior_success_rate_pct)}`
        : trendLabel(op.trend_success_rate).label,
      icon: TrendingUp,
      tone: 'text-success',
    },
    {
      label: 'Rework Rate',
      value: pct(op.rework_rate_pct, 1),
      note: `${count(op.total_rework_count)} packages`,
      icon: AlertTriangle,
      tone: (op.rework_rate_pct ?? 0) > 5 ? 'text-warning' : 'text-success',
    },
    {
      // Distinct from completion: needs CompanyConfig.shift_end, else null.
      label: 'On-Time',
      value: pct(op.on_time_rate_pct),
      note: op.on_time_reference
        ? `vs ${op.on_time_reference}`
        : 'shift end not configured',
      icon: Truck,
      tone: 'text-info',
    },
    {
      label: 'Route Completion',
      value: pct(op.completion_rate_pct),
      note: `${count(op.routes_completed)}/${count(op.routes_dispatched)} routes`,
      icon: Truck,
      tone: 'text-info',
    },
    {
      label: 'Incidents',
      value: count(incidents.total_period),
      note: `${count(incidents.unresolved_count)} unresolved`,
      icon: AlertTriangle,
      tone: incidents.unresolved_count > 0 ? 'text-danger' : 'text-success',
    },
    {
      label: 'Trainees',
      value: count(crew.active_trainees),
      note: `${count(crew.escalated_trainees)} escalated`,
      icon: Users,
      tone: crew.escalated_trainees > 0 ? 'text-warning' : 'text-success',
    },
    {
      label: 'Crew Utilization',
      value: pct(op.crew_utilization_pct),
      note: `${count(op.crews_deployed)}/${count(op.crews_total)} deployed`,
      icon: Users,
      tone: 'text-info',
    },
  ];

  return (
    <div className="space-y-4 sm:space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-start gap-2 sm:gap-3 min-w-0">
          <div className="flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 rounded-lg sm:rounded-xl gradient-primary shadow-sm shadow-primary/30 shrink-0">
            <LayoutDashboard className="w-4 h-4 text-primary-foreground" />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg sm:text-2xl font-bold text-foreground truncate">
              Good {greeting}, {user?.firstName || user?.displayName || user?.username}
            </h1>
            <p className="text-xs sm:text-sm text-subtle mt-0.5">
              {op.period_start} → {op.period_end}
              {op.paid_hours_source === 'none' && (
                <span className="ml-1 text-warning">· no payroll hours in range</span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 sm:gap-2 shrink-0">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value as Period)}
            className="px-2 sm:px-3 py-1.5 sm:py-2 rounded-lg border border-border bg-bg-secondary text-xs sm:text-sm"
            aria-label="Reporting period"
          >
            <option value="today">Today</option>
            <option value="week">Week</option>
            <option value="month">Month</option>
          </select>
          <button
            onClick={loadDashboard}
            disabled={isRefreshing}
            className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40 p-1.5 sm:p-2"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
        {kpis.map((k) => (
          <div key={k.label} className="card-elevated flex flex-col gap-2 p-2.5 sm:p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground uppercase tracking-wider truncate">
                  {k.label}
                </p>
                <p className="text-xl sm:text-2xl font-bold text-foreground mt-0.5 tabular-nums">
                  {k.value}
                </p>
              </div>
              <div className="flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 rounded-lg bg-accent shrink-0">
                <k.icon className={`w-4 h-4 sm:w-5 sm:h-5 ${k.tone}`} />
              </div>
            </div>
            <div className="flex items-center gap-1 min-w-0">
              {'trend' in k && <Trend dir={k.trend} />}
              <p className="text-xs text-subtle truncate">{k.note}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Crew */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-6">
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <Star className="w-4 h-4 sm:w-5 sm:h-5 text-success shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">Top Performers</h2>
          </div>
          {crew.top_walkers.length === 0 ? (
            <p className="text-xs sm:text-sm text-subtle text-center py-4">No ratings this period</p>
          ) : (
            <div className="space-y-1.5 sm:space-y-2">
              {crew.top_walkers.map((w) => (
                <div
                  key={w.employee_name}
                  className="flex items-center justify-between gap-2 p-2 sm:p-3 rounded-lg hover:bg-accent/20 transition-colors"
                >
                  <span className="text-xs sm:text-sm font-medium text-foreground truncate">
                    {w.employee_name}
                  </span>
                  <div className="text-right shrink-0">
                    <p className="text-xs sm:text-sm font-bold text-success tabular-nums">
                      {stars(w.avg_rating)}
                    </p>
                    <p className="text-xs text-subtle tabular-nums">
                      {count(w.packages_delivered)} pkgs · {count(w.rating_count)} ratings
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-warning shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">Needs Attention</h2>
          </div>
          {crew.trouble_walkers.length === 0 ? (
            <p className="text-xs sm:text-sm text-subtle text-center py-4">
              No attendance issues this period
            </p>
          ) : (
            <div className="space-y-1.5 sm:space-y-2">
              {crew.trouble_walkers.map((w) => (
                <div
                  key={w.employee_name}
                  className="flex items-center justify-between gap-2 p-2 sm:p-3 rounded-lg bg-warning/10 border border-warning/20"
                >
                  <span className="text-xs sm:text-sm font-medium text-foreground truncate">
                    {w.employee_name}
                  </span>
                  <div className="text-right shrink-0 tabular-nums">
                    <p className="text-xs sm:text-sm font-bold text-warning">
                      {count(w.ncns_count)} no-show · {count(w.late_count)} late
                    </p>
                    <p className="text-xs text-subtle">{stars(w.avg_rating)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Incidents */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-danger shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">Incidents</h2>
          <span className="ml-auto text-xs text-subtle tabular-nums">
            {count(incidents.rts_pending_count)} RTS pending
          </span>
        </div>

        {Object.keys(incidents.by_severity).length === 0 ? (
          <p className="text-xs sm:text-sm text-subtle text-center py-4">
            No incidents this period
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            {(['critical', 'warning', 'info'] as const).map((sev) => (
              <div key={sev} className="p-2 sm:p-3 rounded-lg bg-accent/20">
                <p className="text-xs text-muted-foreground uppercase tracking-wider">{sev}</p>
                <p
                  className={`text-lg sm:text-2xl font-bold mt-0.5 tabular-nums ${
                    sev === 'critical'
                      ? 'text-danger'
                      : sev === 'warning'
                      ? 'text-warning'
                      : 'text-info'
                  }`}
                >
                  {count(incidents.by_severity[sev] ?? 0)}
                </p>
              </div>
            ))}
          </div>
        )}

        {incidents.by_category.length > 0 && (
          <div className="mt-3 sm:mt-4 space-y-1.5">
            <p className="text-xs text-subtle uppercase tracking-wider">By category</p>
            {incidents.by_category.slice(0, 5).map((c) => (
              <div key={c.category} className="flex items-center justify-between gap-2">
                <span className="text-xs sm:text-sm text-foreground truncate capitalize">
                  {c.category.replace(/_/g, ' ')}
                </span>
                <span className="text-xs sm:text-sm text-foreground shrink-0 tabular-nums">
                  {count(c.count)}
                  <span className="text-subtle ml-1">
                    (30d avg {metric(c.avg_per_week_30d)})
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}

        {incidents.unresolved_count > 0 && (
          <div className="mt-3 sm:mt-4 p-2 sm:p-3 rounded-lg bg-danger/10 border-l-2 border-danger">
            <p className="text-xs sm:text-sm font-semibold text-danger">
              {count(incidents.unresolved_count)} unresolved
            </p>
            {incidents.oldest_unresolved_age_hours != null && (
              <p className="text-xs text-subtle mt-0.5">
                Oldest open {hours(incidents.oldest_unresolved_age_hours, 0)}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Fleet */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <Truck className="w-4 h-4 sm:w-5 sm:h-5 text-info shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">Fleet &amp; Routing</h2>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
          {[
            { label: 'Planned', value: fleet.fleet_planned, tone: 'text-muted-foreground' },
            { label: 'Active', value: fleet.fleet_active, tone: 'text-warning' },
            { label: 'Completed', value: fleet.fleet_completed, tone: 'text-success' },
            { label: 'Misroutes', value: fleet.misrouted_count, tone: 'text-danger' },
          ].map((s) => (
            <div key={s.label} className="p-2 sm:p-3 rounded-lg bg-accent/20">
              <p className="text-xs text-muted-foreground uppercase tracking-wider truncate">
                {s.label}
              </p>
              <p className={`text-lg sm:text-2xl font-bold mt-0.5 tabular-nums ${s.tone}`}>
                {count(s.value)}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-3 sm:mt-4 grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 text-xs sm:text-sm">
          <div className="flex items-center justify-between p-2 rounded-lg bg-accent/10">
            <span className="text-subtle">Avg route duration</span>
            <span className="font-semibold text-foreground tabular-nums">
              {hours(fleet.route_avg_duration_hours)}
              {fleet.routes_with_timing > 0 && (
                <span className="text-subtle ml-1">({fleet.routes_with_timing} timed)</span>
              )}
            </span>
          </div>
          <div className="flex items-center justify-between p-2 rounded-lg bg-accent/10">
            <span className="text-subtle">Misroute rate</span>
            <span className="font-semibold text-foreground tabular-nums">
              {pct(fleet.misrouted_pct_of_packages, 2)}
              <span className="text-subtle ml-1">
                ({count(fleet.misrouted_unresolved)} open)
              </span>
            </span>
          </div>
        </div>

        {fleet.misrouted_hotspots.length > 0 && (
          <div className="mt-3 sm:mt-4 space-y-1.5">
            <p className="text-xs text-subtle uppercase tracking-wider flex items-center gap-1">
              <MapPin className="w-3 h-3" /> Misroute hotspots
            </p>
            {fleet.misrouted_hotspots.map((h) => (
              <div key={h.block_key} className="flex items-center justify-between gap-2">
                <span className="text-xs sm:text-sm text-foreground truncate font-mono">
                  {h.block_key}
                </span>
                <span className="text-xs sm:text-sm font-semibold text-foreground shrink-0 tabular-nums">
                  {count(h.count)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
