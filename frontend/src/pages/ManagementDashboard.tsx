import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import {
  AlertTriangle, BarChart2, ClipboardCheck, Star, Truck, Users,
  LayoutDashboard, RefreshCw, Package, TrendingUp,
} from 'lucide-react';
import type { ManagementDashboardSummary } from '../api/types';

export default function ManagementDashboard() {
  const { user } = useAuth();
  const greeting = new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening';
  const [summary, setSummary] = useState<ManagementDashboardSummary | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [period, setPeriod] = useState<'today' | 'week' | 'month'>('week');

  const loadDashboard = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const res = await axiosClient.get(`/dashboards/management/summary?period=${period}`);
      setSummary(res.data);
    } finally {
      setIsRefreshing(false);
    }
  }, [period]);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  if (!summary) return <div className="text-center py-10 text-subtle">Loading dashboard...</div>;

  const TrendIcon = ({ trend }: { trend: 'up' | 'down' | 'flat' }) => {
    if (trend === 'up') return <TrendingUp className="w-3 h-3 text-success" />;
    if (trend === 'down') return <TrendingUp className="w-3 h-3 text-danger rotate-180" />;
    return <div className="w-3 h-3 rounded-full bg-muted-foreground" />;
  };

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl gradient-primary shadow-sm shadow-primary/30">
            <LayoutDashboard className="w-4 h-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="page-title">Good {greeting}, {user?.firstName || user?.displayName || user?.username}</h1>
            <p className="text-subtle mt-0.5">Management dashboard · Week of {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value as any)}
            className="px-3 py-2 rounded-lg border border-border bg-bg-secondary text-sm"
          >
            <option value="today">Today</option>
            <option value="week">This Week</option>
            <option value="month">This Month</option>
          </select>
          <button
            onClick={loadDashboard}
            disabled={isRefreshing}
            className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40 p-2"
            title="Refresh dashboard"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          {
            label: 'Packages/Hour',
            value: summary.operational.packages_per_hour.toFixed(1),
            sub: summary.operational.trend_packages_per_hour,
            icon: Package,
            color: 'text-info',
          },
          {
            label: 'Delivery Success',
            value: `${summary.operational.delivery_success_rate_pct.toFixed(0)}%`,
            sub: summary.operational.trend_success_rate,
            icon: TrendingUp,
            color: 'text-success',
          },
          {
            label: 'Rework Rate',
            value: `${summary.operational.rework_rate_pct.toFixed(1)}%`,
            sub: `${summary.operational.total_rework_count} items`,
            icon: AlertTriangle,
            color: summary.operational.rework_rate_pct > 5 ? 'text-warning' : 'text-success',
          },
          {
            label: 'On-Time Completion',
            value: `${summary.operational.on_time_completion_rate_pct.toFixed(0)}%`,
            sub: `${summary.operational.routes_completed}/${summary.operational.routes_dispatched}`,
            icon: Truck,
            color: 'text-info',
          },
          {
            label: 'Active Trainees',
            value: summary.crew.active_trainees,
            sub: `${summary.crew.training_completion_pct.toFixed(0)}% complete`,
            icon: Users,
            color: 'text-info',
          },
          {
            label: 'Incidents (7d)',
            value: summary.incidents.total_7d,
            sub: `${summary.incidents.unresolved_count} unresolved`,
            icon: AlertTriangle,
            color: summary.incidents.unresolved_count > 0 ? 'text-danger' : 'text-success',
          },
          {
            label: 'Fleet Status',
            value: summary.fleet.fleet_active,
            sub: `${summary.fleet.fleet_completed} done · ${summary.fleet.fleet_pending} planned`,
            icon: Truck,
            color: 'text-warning',
          },
          {
            label: 'Crew Utilization',
            value: `${summary.operational.crew_utilization_pct.toFixed(0)}%`,
            sub: `${summary.operational.crews_deployed}/${summary.operational.crews_total}`,
            icon: Users,
            color: 'text-info',
          },
        ].map(stat => (
          <div key={stat.label} className="card-elevated flex items-center justify-between gap-3 p-4">
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{stat.label}</p>
              <p className="text-lg font-bold text-foreground">{stat.value}</p>
              <div className="flex items-center gap-1 mt-1">
                {typeof stat.sub === 'string' && stat.sub.match(/^(up|down|flat)$/) ? (
                  <>
                    <TrendIcon trend={stat.sub as any} />
                    <p className="text-xs text-subtle">
                      {stat.sub === 'up' ? 'Improving' : stat.sub === 'down' ? 'Declining' : 'Stable'}
                    </p>
                  </>
                ) : (
                  <p className="text-xs text-subtle">{stat.sub}</p>
                )}
              </div>
            </div>
            <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-accent shrink-0">
              <stat.icon className={`w-5 h-5 ${stat.color}`} />
            </div>
          </div>
        ))}
      </div>

      {/* Crew Performance Section */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* Top Performers */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <Star className="w-5 h-5 text-success" />
            <h2 className="text-base font-semibold text-foreground">Top Performers</h2>
          </div>
          {summary.crew.top_walkers.length === 0 ? (
            <p className="text-sm text-subtle text-center py-4">No data yet</p>
          ) : (
            <div className="space-y-2">
              {summary.crew.top_walkers.map((walker, i) => (
                <div key={i} className="flex items-center justify-between p-2 rounded-lg hover:bg-accent/20">
                  <span className="text-sm font-medium text-foreground">{walker.employee_name}</span>
                  <div className="text-right">
                    <p className="text-sm font-bold text-success">{walker.avg_rating.toFixed(1)} ★</p>
                    <p className="text-xs text-subtle">{walker.deliveries} deliveries</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Trouble Walkers */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <AlertTriangle className="w-5 h-5 text-warning" />
            <h2 className="text-base font-semibold text-foreground">Needs Attention</h2>
          </div>
          {summary.crew.trouble_walkers.length === 0 ? (
            <p className="text-sm text-subtle text-center py-4">All clear</p>
          ) : (
            <div className="space-y-2">
              {summary.crew.trouble_walkers.map((walker, i) => (
                <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-warning/10">
                  <span className="text-sm font-medium text-foreground">{walker.employee_name}</span>
                  <div className="text-right">
                    <p className="text-sm font-bold text-warning">{walker.no_show_count} no-shows</p>
                    <p className="text-xs text-subtle">{walker.avg_rating?.toFixed(1) || 'N/A'} ★</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Incidents */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <AlertTriangle className="w-5 h-5 text-danger" />
          <h2 className="text-base font-semibold text-foreground">Incident Summary (7d)</h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {Object.entries(summary.incidents.by_severity).map(([sev, count]) => (
            <div key={sev} className="p-3 rounded-lg bg-accent/20">
              <p className="text-xs text-muted-foreground uppercase tracking-wider capitalize">{sev}</p>
              <p className="text-2xl font-bold text-foreground mt-1">{count}</p>
            </div>
          ))}
        </div>
        {summary.incidents.unresolved_count > 0 && (
          <div className="mt-4 p-3 rounded-lg bg-danger/10 border-l-2 border-danger">
            <p className="text-sm font-semibold text-danger">{summary.incidents.unresolved_count} unresolved</p>
            {summary.incidents.oldest_unresolved_age_hours > 0 && (
              <p className="text-xs text-subtle mt-1">Oldest: {summary.incidents.oldest_unresolved_age_hours}h ago</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
