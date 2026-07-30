import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import { Users, RefreshCw, Star, AlertTriangle, CheckCircle2, TrendingUp } from 'lucide-react';
import type { TrainerDashboardSummary } from '../api/types';

export default function TrainerDashboard() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<TrainerDashboardSummary | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      const res = await axiosClient.get('/dashboards/trainer/summary');
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
          <div className="flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 rounded-lg sm:rounded-xl bg-info/20 flex-shrink-0">
            <Users className="w-4 h-4 sm:w-5 sm:h-5 text-info" />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg sm:text-2xl font-bold text-foreground">Trainer Hub</h1>
            <p className="text-xs sm:text-sm text-subtle mt-0.5">Trainee progress & performance</p>
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

      {/* Trainee Status */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
        {[
          {
            label: 'Active Trainees',
            value: summary.trainee_status.active_trainees,
            color: 'text-info',
          },
          {
            label: 'Phase 1',
            value: summary.trainee_status.by_phase[1],
            color: 'text-info',
          },
          {
            label: 'Phase 2',
            value: summary.trainee_status.by_phase[2],
            color: 'text-info',
          },
          {
            label: 'Phase 4 Ready',
            value: summary.performance.ready_for_solo_phase4.length,
            color: 'text-success',
          },
        ].map(stat => (
          <div key={stat.label} className="card-elevated flex flex-col gap-2 p-2.5 sm:p-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider truncate">{stat.label}</p>
            <p className={`text-lg sm:text-2xl font-bold ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Escalations */}
      {summary.trainee_status.escalated_count > 0 && (
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-warning flex-shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">Escalations ({summary.trainee_status.escalated_count})</h2>
          </div>
          <div className="space-y-2">
            {summary.performance.escalations.map((esc, i) => (
              <div key={i} className="p-2 sm:p-3 rounded-lg bg-warning/10 border border-warning/20">
                <p className="text-xs sm:text-sm font-semibold text-foreground">{esc.trainee_name}</p>
                <p className="text-xs text-subtle mt-1 capitalize">{esc.reason.replace(/_/g, ' ')}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stuck Trainees */}
      {summary.trainee_status.stuck_trainees.length > 0 && (
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-danger flex-shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">Stuck in Training</h2>
          </div>
          <div className="space-y-2">
            {summary.trainee_status.stuck_trainees.map((stuck, i) => (
              <div key={i} className="p-2 sm:p-3 rounded-lg bg-danger/10 border border-danger/20">
                <div className="flex items-center justify-between">
                  <p className="text-xs sm:text-sm font-semibold text-foreground truncate">{stuck.trainee_name}</p>
                  <span className="text-xs text-danger font-bold flex-shrink-0">{stuck.days_in_phase}d</span>
                </div>
                <p className="text-xs text-subtle mt-1">Phase {stuck.phase}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Ready for Solo */}
      {summary.performance.ready_for_solo_phase4.length > 0 && (
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5 text-success flex-shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">Ready for Phase 4 Solo</h2>
          </div>
          <div className="space-y-2">
            {summary.performance.ready_for_solo_phase4.map((trainee, i) => (
              <div key={i} className="p-2 sm:p-3 rounded-lg bg-success/10 border border-success/20">
                <p className="text-xs sm:text-sm font-semibold text-foreground">{trainee.trainee_name}</p>
                <p className="text-xs text-subtle mt-1">Approved {trainee.approval_date}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Training Overview */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <TrendingUp className="w-4 h-4 sm:w-5 sm:h-5 text-info flex-shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">Training Progress</h2>
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between p-2 sm:p-3 rounded-lg bg-accent/20">
            <span className="text-xs sm:text-sm text-foreground">Graduation Rate</span>
            <span className="text-sm sm:text-base font-bold text-foreground">{summary.trainee_status.graduation_completion_pct.toFixed(0)}%</span>
          </div>
          <div className="w-full bg-accent/20 rounded-full h-2 sm:h-3 overflow-hidden">
            <div
              className="bg-success h-full transition-all"
              style={{ width: `${summary.trainee_status.graduation_completion_pct}%` }}
            />
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[1, 2, 3].map(phase => (
              <div key={phase} className="p-2 rounded-lg bg-info/10">
                <p className="text-xs text-info font-semibold">Phase {phase}</p>
                <p className="text-sm font-bold text-foreground mt-1">{summary.trainee_status.by_phase[phase]}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
