import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import { LayoutDashboard, RefreshCw, AlertTriangle, CheckCircle2, AlertCircle, Zap } from 'lucide-react';
import type { AdminDashboardSummary } from '../api/types';

export default function AdminDashboard() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<AdminDashboardSummary | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      const res = await axiosClient.get('/dashboards/admin/summary');
      setSummary(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to load dashboard');
      console.error('Dashboard error:', err);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  if (error) {
    return (
      <div className="text-center py-10 space-y-4">
        <p className="text-danger font-semibold">Error loading dashboard</p>
        <p className="text-subtle text-sm">{error}</p>
        <button onClick={loadDashboard} className="btn-primary text-sm">Retry</button>
      </div>
    );
  }

  if (!summary) return <div className="text-center py-10 text-subtle">Loading dashboard...</div>;

  return (
    <div className="space-y-4 sm:space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-start gap-2 sm:gap-3">
          <div className="flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 rounded-lg sm:rounded-xl bg-danger/20 flex-shrink-0">
            <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-danger" />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg sm:text-2xl font-bold text-foreground">Admin Dashboard</h1>
            <p className="text-xs sm:text-sm text-subtle mt-0.5">System health & compliance</p>
          </div>
        </div>
        <button
          onClick={loadDashboard}
          disabled={isRefreshing}
          className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40 p-1.5 sm:p-2"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* System Health */}
      <div className="card p-3 sm:p-4">
        <h2 className="text-sm sm:text-base font-semibold text-foreground mb-3 sm:mb-4">System Health</h2>
        <div className="space-y-2 sm:space-y-3">
          <div className="flex items-center justify-between p-2 sm:p-3 rounded-lg bg-accent/20">
            <span className="text-xs sm:text-sm text-foreground">ADP Sync Status</span>
            <span className={`text-xs sm:text-sm font-semibold ${
              summary.system_health.adp_status === 'connected' ? 'text-success' :
              summary.system_health.adp_status === 'stale' ? 'text-warning' : 'text-danger'
            }`}>
              {summary.system_health.adp_status === 'connected' ? '✓ Connected' :
               summary.system_health.adp_status === 'stale' ? '! Stale' : '✗ Error'}
            </span>
          </div>
          <div className="flex items-center justify-between p-2 sm:p-3 rounded-lg bg-accent/20">
            <span className="text-xs sm:text-sm text-foreground">Flex Manifest Age</span>
            <span className="text-xs sm:text-sm font-semibold text-info">{summary.system_health.flex_data_freshness_hours}h ago</span>
          </div>
          <div className="flex items-center justify-between p-2 sm:p-3 rounded-lg bg-accent/20">
            <span className="text-xs sm:text-sm text-foreground">Database Health</span>
            <span className="text-xs sm:text-sm font-semibold text-success">✓ Good</span>
          </div>
        </div>
      </div>

      {/* Compliance */}
      <div className="card p-3 sm:p-4">
        <h2 className="text-sm sm:text-base font-semibold text-foreground mb-3 sm:mb-4">Compliance Status</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3">
          <div className="p-2 sm:p-3 rounded-lg bg-success/10 border border-success/20">
            <p className="text-xs text-success font-semibold">{summary.compliance.training_completion_pct.toFixed(0)}%</p>
            <p className="text-xs text-subtle mt-1">Training Done</p>
          </div>
          <div className="p-2 sm:p-3 rounded-lg bg-info/10 border border-info/20">
            <p className="text-xs text-info font-semibold">{summary.compliance.vehicle_inspection_pass_rate_7d.toFixed(0)}%</p>
            <p className="text-xs text-subtle mt-1">Inspect Pass</p>
          </div>
          <div className={`p-2 sm:p-3 rounded-lg border ${
            summary.compliance.incident_7d_count > 5 ? 'bg-danger/10 border-danger/20' : 'bg-success/10 border-success/20'
          }`}>
            <p className={`text-xs font-semibold ${summary.compliance.incident_7d_count > 5 ? 'text-danger' : 'text-success'}`}>
              {summary.compliance.incident_7d_count}
            </p>
            <p className="text-xs text-subtle mt-1">Incidents (7d)</p>
          </div>
        </div>
      </div>

      {/* Alerts */}
      {summary.system_health.active_alerts.length > 0 && (
        <div className="card p-3 sm:p-4">
          <h2 className="text-sm sm:text-base font-semibold text-foreground mb-2 sm:mb-3 flex items-center gap-2">
            <Zap className="w-4 h-4 text-warning" />
            Active Alerts
          </h2>
          <div className="space-y-2">
            {summary.system_health.active_alerts.map((alert, i) => (
              <div key={i} className="p-2 sm:p-3 rounded-lg bg-warning/10 border-l-2 border-warning">
                <p className="text-xs sm:text-sm font-semibold text-warning">{alert.message}</p>
                <p className="text-xs text-subtle mt-1">{alert.severity}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
