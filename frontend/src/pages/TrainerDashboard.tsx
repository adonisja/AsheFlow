import React, { useEffect, useState, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import {
  Users, RefreshCw, AlertTriangle, CheckCircle2, GraduationCap, MessageSquare, Flag,
} from 'lucide-react';
import type { TrainerDashboardSummary } from '../api/types';
import { pct, count, stars, shortDate } from '../utils/metric';

export default function TrainerDashboard() {
  const [summary, setSummary] = useState<TrainerDashboardSummary | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      const res = await axiosClient.get('/dashboards/trainer/summary');
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

  const { trainee_status: st, performance: perf } = summary;

  return (
    <div className="space-y-4 sm:space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-start gap-2 sm:gap-3 min-w-0">
          <div className="flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 rounded-lg sm:rounded-xl bg-info/20 shrink-0">
            <Users className="w-4 h-4 sm:w-5 sm:h-5 text-info" />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg sm:text-2xl font-bold text-foreground">Trainer Hub</h1>
            <p className="text-xs sm:text-sm text-subtle mt-0.5">My trainees &amp; training signals</p>
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

      {/* Roster KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
        {[
          { label: 'My Trainees', value: count(st.active_trainees), tone: 'text-info' },
          {
            label: 'Escalated',
            value: count(st.escalated_count),
            tone: st.escalated_count > 0 ? 'text-warning' : 'text-success',
          },
          {
            label: "Today's Records",
            value: `${count(st.records_today_submitted)}/${count(st.records_today_total)}`,
            tone: st.records_today_open > 0 ? 'text-warning' : 'text-success',
            note: `${count(st.records_today_open)} open`,
          },
          {
            label: 'Ready for Solo',
            value: count(perf.ready_for_solo.length),
            tone: 'text-success',
          },
        ].map((s) => (
          <div key={s.label} className="card-elevated flex flex-col gap-1 p-2.5 sm:p-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider truncate">
              {s.label}
            </p>
            <p className={`text-lg sm:text-2xl font-bold tabular-nums ${s.tone}`}>{s.value}</p>
            {s.note && <p className="text-xs text-subtle">{s.note}</p>}
          </div>
        ))}
      </div>

      {/* Phase distribution — rows, not a fixed 1..4 map. Phase 5 is the quiz
          and 6+ are remediation, which a {1..4} shape silently dropped. */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <GraduationCap className="w-4 h-4 sm:w-5 sm:h-5 text-info shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">Phase Distribution</h2>
          <span className="ml-auto text-xs text-subtle tabular-nums">
            {pct(st.graduation_completion_pct)} graduated
          </span>
        </div>
        {st.phases.length === 0 ? (
          <p className="text-xs sm:text-sm text-subtle text-center py-4">No active trainees</p>
        ) : (
          <div className="space-y-1.5 sm:space-y-2">
            {st.phases.map((p) => (
              <div key={p.phase} className="flex items-center gap-2">
                <span className="text-xs sm:text-sm text-foreground w-40 sm:w-52 truncate">
                  {p.label}
                </span>
                <div className="flex-1 bg-accent/20 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-info h-full"
                    style={{
                      width: `${
                        (p.trainee_count / Math.max(st.active_trainees, 1)) * 100
                      }%`,
                    }}
                  />
                </div>
                <span className="text-xs sm:text-sm font-semibold text-foreground w-8 text-right tabular-nums">
                  {count(p.trainee_count)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Stuck trainees */}
      {st.stuck_trainees.length > 0 && (
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <AlertTriangle className="w-4 h-4 sm:w-5 sm:h-5 text-danger shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">
              Stuck in Phase (&gt;21 days)
            </h2>
          </div>
          <div className="space-y-1.5 sm:space-y-2">
            {st.stuck_trainees.map((s) => (
              <div
                key={`${s.trainee_name}-${s.phase}`}
                className="flex items-center justify-between gap-2 p-2 sm:p-3 rounded-lg bg-danger/10 border border-danger/20"
              >
                <span className="text-xs sm:text-sm font-medium text-foreground truncate">
                  {s.trainee_name}
                </span>
                <span className="text-xs text-subtle shrink-0 tabular-nums">
                  Phase {s.phase} · {count(s.days_in_phase)}d
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Problem areas — real TrainingTask signals, replacing the hardcoded
          'incomplete_training' reason the previous version showed. */}
      <div className="card p-3 sm:p-4">
        <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
          <Flag className="w-4 h-4 sm:w-5 sm:h-5 text-warning shrink-0" />
          <h2 className="text-sm sm:text-base font-semibold text-foreground">Problem Areas</h2>
        </div>
        {perf.problem_areas.length === 0 ? (
          <p className="text-xs sm:text-sm text-subtle text-center py-4 flex items-center justify-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-success" />
            No escalated, late, or debt tasks
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs sm:text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-3">Topic</th>
                  <th className="pb-2 pr-3 text-right">Escalated</th>
                  <th className="pb-2 pr-3 text-right">Late</th>
                  <th className="pb-2 text-right">Debt</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {perf.problem_areas.map((p) => (
                  <tr key={p.topic_title}>
                    <td className="py-2 pr-3 text-foreground">{p.topic_title}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-warning font-semibold">
                      {count(p.escalated_count)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                      {count(p.late_count)}
                    </td>
                    <td className="py-2 text-right tabular-nums text-muted-foreground">
                      {count(p.debt_count)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Phase 4 results */}
      {perf.phase4_results.length > 0 && (
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <GraduationCap className="w-4 h-4 sm:w-5 sm:h-5 text-success shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">
              Phase 4 Evaluations
            </h2>
          </div>
          <div className="space-y-1.5 sm:space-y-2">
            {perf.phase4_results.map((r, i) => (
              <div
                key={`${r.trainee_name}-${r.record_date}-${i}`}
                className={`flex items-center justify-between gap-2 p-2 sm:p-3 rounded-lg border ${
                  r.passed === true
                    ? 'bg-success/10 border-success/20'
                    : r.passed === false
                    ? 'bg-danger/10 border-danger/20'
                    : 'bg-accent/20 border-border'
                }`}
              >
                <div className="min-w-0">
                  <p className="text-xs sm:text-sm font-medium text-foreground truncate">
                    {r.trainee_name}
                  </p>
                  <p className="text-xs text-subtle">{shortDate(r.record_date)}</p>
                </div>
                <div className="text-right shrink-0 tabular-nums">
                  <p className="text-xs sm:text-sm font-bold text-foreground">
                    {r.score != null ? r.score.toFixed(1) : '—'}
                  </p>
                  <p
                    className={`text-xs font-semibold ${
                      r.passed === true
                        ? 'text-success'
                        : r.passed === false
                        ? 'text-danger'
                        : 'text-subtle'
                    }`}
                  >
                    {r.passed === true ? 'Passed' : r.passed === false ? 'Failed' : 'Pending'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Ready for solo — names only. The previous version invented an
          approval_date (today's date) for every row. */}
      {perf.ready_for_solo.length > 0 && (
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5 text-success shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">
              Ready for Phase 4 Solo
            </h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {perf.ready_for_solo.map((name) => (
              <span
                key={name}
                className="text-xs sm:text-sm px-2 py-1 rounded-full bg-success/10 text-success border border-success/20"
              >
                {name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Feedback ABOUT the trainer — direction made explicit. The old
          weekly_rating_distribution presented this as trainee performance. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-6">
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <MessageSquare className="w-4 h-4 sm:w-5 sm:h-5 text-info shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">
              How My Trainees Rate Me
            </h2>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-foreground tabular-nums">
              {stars(perf.trainee_feedback_about_me.avg_rating)}
            </span>
            <span className="text-xs text-subtle tabular-nums">
              from {count(perf.trainee_feedback_about_me.rating_count)} ratings
            </span>
          </div>
          {perf.trainee_feedback_about_me.recent_comments.length > 0 && (
            <div className="mt-3 space-y-1.5">
              {perf.trainee_feedback_about_me.recent_comments.map((c, i) => (
                <p
                  key={i}
                  className="text-xs sm:text-sm text-muted-foreground italic border-l-2 border-border pl-2"
                >
                  “{c}”
                </p>
              ))}
            </div>
          )}
        </div>

        {/* Marks are demerits against the TRAINER, not the trainee. */}
        <div className="card p-3 sm:p-4">
          <div className="flex items-center gap-2 border-b border-border pb-2 sm:pb-3 mb-3 sm:mb-4">
            <Flag className="w-4 h-4 sm:w-5 sm:h-5 text-warning shrink-0" />
            <h2 className="text-sm sm:text-base font-semibold text-foreground">My Marks</h2>
            <span className="ml-auto text-xs text-subtle tabular-nums">
              {count(perf.my_marks.total_marks)} total
            </span>
          </div>
          {perf.my_marks.total_marks === 0 ? (
            <p className="text-xs sm:text-sm text-subtle text-center py-4 flex items-center justify-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-success" />
              No marks on record
            </p>
          ) : (
            <div className="space-y-1.5">
              {Object.entries(perf.my_marks.by_reason).map(([reason, n]) => (
                <div key={reason} className="flex items-center justify-between gap-2">
                  <span className="text-xs sm:text-sm text-foreground capitalize truncate">
                    {reason.replace(/_/g, ' ')}
                  </span>
                  <span className="text-xs sm:text-sm font-semibold text-warning shrink-0 tabular-nums">
                    {count(n)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
