import { errorText } from '../utils/errorText';
import React, { useState, useEffect, useMemo } from 'react';
import Select from 'react-select';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { getSchedule, createOffDay } from '../api/preferences';
import { createTimeOffRequest } from '../api/timeOffRequests';
import { fmtDate } from '../utils/date';
import {
  CalendarDays, Clock, Users, CheckCircle2, XCircle, ClipboardCheck,
  ChevronLeft, ChevronRight, AlertTriangle, BarChart2, Calendar,
  RefreshCw, ArrowUpDown, Filter,
} from 'lucide-react';
import { MiniCalendar } from '../components/MiniCalendar';
import ErrorBanner from '../components/ui/ErrorBanner';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useConfirm } from '../hooks/useConfirm';

import type { CrewMember } from '../api/types';

interface ScheduleDay {
  date: string;
  status: string;
  truck_name: string | null;
  crew: CrewMember[] | null;
}

const selectStyles = {
  control: (base: any, state: any) => ({
    ...base,
    borderRadius: '0.75rem',
    borderColor: state.isFocused ? 'hsl(243 75% 59%)' : 'hsl(220 13% 91%)',
    boxShadow: state.isFocused ? '0 0 0 2px hsl(243 75% 59% / 0.15)' : 'none',
    padding: '2px 4px',
    fontSize: '0.875rem',
    '&:hover': { borderColor: 'hsl(243 75% 59%)' },
  }),
  option: (base: any, state: any) => ({
    ...base,
    fontSize: '0.875rem',
    backgroundColor: state.isSelected ? 'hsl(243 75% 59%)' : state.isFocused ? 'hsl(243 100% 97%)' : 'white',
    color: state.isSelected ? 'white' : 'hsl(224 30% 12%)',
  }),
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const isExpired = (dateStr: string) => {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const d = new Date(dateStr); d.setHours(0, 0, 0, 0);
  return d <= today;
};

const daysSince = (isoStr: string) => {
  const diff = Date.now() - new Date(isoStr).getTime();
  return Math.floor(diff / 86_400_000);
};

// ---------------------------------------------------------------------------
// Management / Admin view
// ---------------------------------------------------------------------------

type QueueFilter = 'all' | 'pto' | 'offday' | 'rework';

const TYPE_LABEL: Record<string, string> = {
  add_day:     'Add Working Days',
  drop_day:    'Drop Working Days',
  full_rework: 'Full Schedule Rework',
};

function AgeBadge({ createdAt }: { createdAt: string }) {
  const days = daysSince(createdAt);
  const cls = days >= 7 ? 'bg-danger/10 text-danger border-danger/20'
    : days >= 3 ? 'bg-warning/10 text-warning border-warning/20'
    : 'bg-accent text-muted-foreground border-border';
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${cls}`}>
      {days === 0 ? 'Today' : `${days}d ago`}
    </span>
  );
}

function ScheduleManagementView({ isAdmin }: { isAdmin: boolean }) {
  const { confirmState, confirm, cancelConfirm } = useConfirm();

  // Pending queues
  const [ptoPending, setPtoPending]       = useState<any[]>([]);
  const [offDayPending, setOffDayPending] = useState<any[]>([]);
  const [reworkPending, setReworkPending] = useState<any[]>([]);
  const [employees, setEmployees]         = useState<any[]>([]);
  const [error, setError]                 = useState<string | null>(null);

  // 4-week availability heatmap
  const [heatmapData, setHeatmapData]   = useState<Record<string, { driver: number; trainer: number; walker: number }>>({});
  const [heatmapLoading, setHeatmapLoading] = useState(true);

  // Queue filter + sort
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all');
  const [sortOldest, setSortOldest]   = useState(false);

  // Analytics (admin only — re-uses ScheduleChanges data shape)
  const [allReworks, setAllReworks] = useState<any[]>([]);

  useEffect(() => {
    axiosClient.get('/employees/').then(r => setEmployees(r.data)).catch((e) => { console.error('Failed to load employees:', e); });

    Promise.allSettled([
      axiosClient.get('/time-off-requests/')
        .then(r => setPtoPending(r.data.filter((x: any) => x.status === 'pending'))),
      axiosClient.get('/employee-off-days/')
        .then(r => setOffDayPending(r.data.filter((x: any) => x.status === 'pending'))),
      axiosClient.get('/schedule-change-requests/?status=pending')
        .then(r => setReworkPending(r.data)),
      ...(isAdmin ? [axiosClient.get('/schedule-change-requests/').then(r => setAllReworks(r.data))] : []),
    ]).then(results => {
      if (results.some(r => r.status === 'rejected')) {
        setError('Some schedule data failed to load. Please refresh.');
      }
    });

    // Build 4-week availability heatmap
    const today = new Date();
    const dates: string[] = [];
    for (let i = 0; i < 28; i++) {
      const d = new Date(today);
      d.setDate(today.getDate() + i);
      dates.push(fmtDate(d));
    }
    Promise.allSettled(
      dates.map(dt =>
        axiosClient.get(`/schedule/available/${dt}`).then(r => ({ dt, data: r.data }))
      )
    ).then(results => {
      const map: Record<string, { driver: number; trainer: number; walker: number }> = {};
      for (const res of results) {
        if (res.status === 'fulfilled') {
          const { dt, data } = res.value;
          map[dt] = {
            driver:  data.driver?.length  ?? 0,
            trainer: data.trainer?.length ?? 0,
            walker:  data.walker?.length  ?? 0,
          };
        }
      }
      setHeatmapData(map);
      setHeatmapLoading(false);
    });
  }, [isAdmin]);

  const empName = (id: string) => {
    const e = employees.find(x => x.id === id);
    return e ? (e.first_name || e.name) : 'Unknown';
  };
  const empRole = (id: string) => employees.find(x => x.id === id)?.role ?? '';

  // Approve / reject handlers
  const approvePTO = async (id: string) => {
    const ok = await confirm({ title: 'Approve PTO', message: 'Approve this time-off request?', confirmLabel: 'Approve', variant: 'default' });
    if (!ok) return;
    axiosClient.patch(`/time-off-requests/${id}/approve`).then(() => setPtoPending(p => p.filter(x => x.id !== id)));
  };
  const rejectPTO = async (id: string) => {
    const ok = await confirm({ title: 'Reject PTO', message: 'Reject this time-off request? The employee will be notified.', confirmLabel: 'Reject', variant: 'danger' });
    if (!ok) return;
    axiosClient.patch(`/time-off-requests/${id}/reject`).then(() => setPtoPending(p => p.filter(x => x.id !== id)));
  };

  const approveOffDay = async (id: string) => {
    const ok = await confirm({ title: 'Approve Off Day', message: 'Approve this off-day request?', confirmLabel: 'Approve', variant: 'default' });
    if (!ok) return;
    axiosClient.patch(`/employee-off-days/${id}/approve`).then(() => setOffDayPending(p => p.filter(x => x.id !== id)));
  };
  const rejectOffDay = async (id: string) => {
    const ok = await confirm({ title: 'Reject Off Day', message: 'Reject this off-day request? The employee will be notified.', confirmLabel: 'Reject', variant: 'danger' });
    if (!ok) return;
    axiosClient.patch(`/employee-off-days/${id}/reject`).then(() => setOffDayPending(p => p.filter(x => x.id !== id)));
  };

  const approveRework = async (id: string) => {
    const ok = await confirm({ title: 'Approve Schedule Change', message: 'Approve this permanent schedule change request?', confirmLabel: 'Approve', variant: 'default' });
    if (!ok) return;
    axiosClient.patch(`/schedule-change-requests/${id}/approve`).then(() => setReworkPending(p => p.filter(x => x.id !== id)));
  };
  const rejectRework = async (id: string) => {
    const ok = await confirm({ title: 'Reject Schedule Change', message: 'Reject this schedule change request?', confirmLabel: 'Reject', variant: 'danger' });
    if (!ok) return;
    axiosClient.patch(`/schedule-change-requests/${id}/reject`).then(() => setReworkPending(p => p.filter(x => x.id !== id)));
  };

  // Unified queue
  const unified = useMemo(() => {
    const items: any[] = [];
    if (queueFilter === 'all' || queueFilter === 'pto') {
      ptoPending.forEach(r => items.push({ ...r, _kind: 'pto' }));
    }
    if (queueFilter === 'all' || queueFilter === 'offday') {
      offDayPending.forEach(r => items.push({ ...r, _kind: 'offday' }));
    }
    if (queueFilter === 'all' || queueFilter === 'rework') {
      reworkPending.forEach(r => items.push({ ...r, _kind: 'rework' }));
    }
    const withTs = items.map(i => ({ ...i, _ts: new Date(i.created_at ?? 0).getTime() }));
    return sortOldest
      ? withTs.sort((a, b) => a._ts - b._ts)
      : withTs.sort((a, b) => b._ts - a._ts);
  }, [ptoPending, offDayPending, reworkPending, queueFilter, sortOldest]);

  const totalPending = ptoPending.length + offDayPending.length + reworkPending.length;

  // Heatmap helpers
  const heatmapDates = Object.keys(heatmapData).sort();
  const heatmapMax = useMemo(() => {
    let max = 0;
    for (const v of Object.values(heatmapData)) {
      max = Math.max(max, v.driver, v.trainer, v.walker);
    }
    return max || 1;
  }, [heatmapData]);

  const heatCell = (count: number) => {
    const intensity = count / heatmapMax;
    if (intensity === 0) return 'bg-accent/30 text-muted-foreground/60';
    if (intensity < 0.33) return 'bg-success/10 text-success/80';
    if (intensity < 0.66) return 'bg-success/25 text-success';
    return 'bg-success/45 text-success font-semibold';
  };

  // Group 28 dates into 4 weeks of 7
  const heatmapWeeks: string[][] = useMemo(() => {
    const weeks: string[][] = [];
    for (let i = 0; i < heatmapDates.length; i += 7) {
      weeks.push(heatmapDates.slice(i, i + 7));
    }
    return weeks;
  }, [heatmapDates]);

  // Analytics (admin)
  const reworkApproved = allReworks.filter(r => r.status === 'approved').length;
  const reworkRejected = allReworks.filter(r => r.status === 'rejected').length;
  const approvalRate = (reworkApproved + reworkRejected) > 0
    ? Math.round((reworkApproved / (reworkApproved + reworkRejected)) * 100)
    : null;

  const oldestPending = useMemo(() => {
    const all = [...ptoPending, ...offDayPending, ...reworkPending]
      .map(r => new Date(r.created_at ?? 0).getTime())
      .filter(Boolean);
    if (all.length === 0) return null;
    return daysSince(new Date(Math.min(...all)).toISOString());
  }, [ptoPending, offDayPending, reworkPending]);

  return (
    <div className="space-y-8 animate-slide-up">
      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl gradient-primary shadow-sm shadow-primary/30">
          <CalendarDays className="w-4 h-4 text-primary-foreground" />
        </div>
        <div>
          <h1 className="page-title">Schedule Management</h1>
          <p className="text-subtle mt-0.5">
            {isAdmin ? 'System-wide schedule oversight and approvals.' : 'Review and action pending schedule requests from field staff.'}
          </p>
        </div>
      </div>

      <ErrorBanner message={error} />

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          {
            label: 'Pending PTO',
            value: ptoPending.length,
            color: ptoPending.length > 0 ? 'text-warning' : 'text-subtle',
          },
          {
            label: 'Workday Changes',
            value: offDayPending.length,
            color: offDayPending.length > 0 ? 'text-warning' : 'text-subtle',
          },
          {
            label: 'Schedule Reworks',
            value: reworkPending.length,
            color: reworkPending.length > 0 ? 'text-warning' : 'text-subtle',
          },
          {
            label: 'Oldest Pending',
            value: oldestPending !== null ? `${oldestPending}d` : '—',
            color: oldestPending !== null && oldestPending >= 7 ? 'text-danger'
              : oldestPending !== null && oldestPending >= 3 ? 'text-warning'
              : 'text-subtle',
          },
        ].map(stat => (
          <div key={stat.label} className="card-elevated">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
            <p className={`text-2xl font-bold mt-1 ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Admin analytics strip */}
      {isAdmin && allReworks.length > 0 && (
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <BarChart2 className="w-5 h-5 text-primary" />
            <h2 className="text-base font-semibold text-foreground">Schedule Change Analytics</h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
            {[
              { label: 'Total Requests', value: allReworks.length, color: 'text-foreground' },
              { label: 'Approved',       value: reworkApproved,    color: 'text-success'   },
              { label: 'Rejected',       value: reworkRejected,    color: 'text-danger'    },
              { label: 'Approval Rate',  value: approvalRate !== null ? `${approvalRate}%` : '—', color: approvalRate !== null && approvalRate >= 70 ? 'text-success' : 'text-warning' },
            ].map(s => (
              <div key={s.label} className="p-3 rounded-xl bg-accent/40">
                <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
                <p className="text-xs text-subtle mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unified approvals queue */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4 flex-wrap gap-y-3">
          <ClipboardCheck className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">
            Pending Approvals
            {totalPending > 0 && (
              <span className="ml-2 text-xs font-bold text-warning bg-warning/10 border border-warning/20 px-2 py-0.5 rounded-full">
                {totalPending}
              </span>
            )}
          </h2>

          <div className="ml-auto flex items-center gap-2 flex-wrap">
            {/* Type filter */}
            <div className="flex items-center gap-1 bg-accent rounded-lg p-1 text-xs">
              {([
                { key: 'all',    label: 'All' },
                { key: 'pto',    label: `PTO (${ptoPending.length})` },
                { key: 'offday', label: `Workday (${offDayPending.length})` },
                { key: 'rework', label: `Rework (${reworkPending.length})` },
              ] as { key: QueueFilter; label: string }[]).map(f => (
                <button
                  key={f.key}
                  onClick={() => setQueueFilter(f.key)}
                  className={`px-2.5 py-1 rounded-md font-medium transition-colors ${queueFilter === f.key ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                >
                  {f.label}
                </button>
              ))}
            </div>
            {/* Sort toggle */}
            <button
              onClick={() => setSortOldest(p => !p)}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-border bg-background hover:bg-accent transition-colors text-muted-foreground"
              title={sortOldest ? 'Showing oldest first' : 'Showing newest first'}
            >
              <ArrowUpDown className="w-3.5 h-3.5" />
              {sortOldest ? 'Oldest first' : 'Newest first'}
            </button>
          </div>
        </div>

        {unified.length === 0 ? (
          <div className="text-center py-10 opacity-60">
            <CheckCircle2 className="w-10 h-10 mb-3 text-success mx-auto" />
            <p className="text-sm font-medium">No pending requests.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {unified.map(req => {
              if (req._kind === 'pto') {
                const expired = isExpired(req.date);
                return (
                  <div key={req.id} className={`p-4 border rounded-xl bg-background flex flex-col justify-between gap-3 shadow-sm ${expired ? 'opacity-60' : ''}`}>
                    <div>
                      <div className="flex justify-between items-start mb-1 gap-2">
                        <p className="font-semibold text-sm text-foreground">{empName(req.employee_id)}</p>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <AgeBadge createdAt={req.created_at} />
                          <span className={`px-2 py-0.5 rounded text-xs font-medium border ${expired ? 'bg-muted/10 text-muted border-muted/20' : 'bg-primary/10 text-primary border-primary/20'}`}>
                            {expired ? 'Expired PTO' : 'PTO Request'}
                          </span>
                        </div>
                      </div>
                      <p className="text-xs text-muted-foreground">{empRole(req.employee_id)} · Date: {req.date}</p>
                      {expired && <p className="text-xs text-danger mt-1">Request date is today or in the past.</p>}
                    </div>
                    {!expired && (
                      <div className="flex gap-2 mt-1">
                        <button onClick={() => approvePTO(req.id)} className="flex-1 bg-success/10 text-success hover:bg-success/20 border border-success/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Approve</button>
                        <button onClick={() => rejectPTO(req.id)}  className="flex-1 bg-danger/10 text-danger hover:bg-danger/20 border border-danger/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Reject</button>
                      </div>
                    )}
                  </div>
                );
              }

              if (req._kind === 'offday') {
                return (
                  <div key={req.id} className="p-4 border rounded-xl bg-background flex flex-col justify-between gap-3 shadow-sm">
                    <div>
                      <div className="flex justify-between items-start mb-1 gap-2">
                        <p className="font-semibold text-sm text-foreground">{empName(req.employee_id)}</p>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <AgeBadge createdAt={req.created_at} />
                          <span className="bg-warning/10 text-warning px-2 py-0.5 rounded text-xs font-medium border border-warning/20">Workday Change</span>
                        </div>
                      </div>
                      <p className="text-xs text-muted-foreground">{empRole(req.employee_id)} · Recurring: {req.day_of_week}</p>
                    </div>
                    <div className="flex gap-2 mt-1">
                      <button onClick={() => approveOffDay(req.id)} className="flex-1 bg-success/10 text-success hover:bg-success/20 border border-success/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Approve</button>
                      <button onClick={() => rejectOffDay(req.id)}  className="flex-1 bg-danger/10 text-danger hover:bg-danger/20 border border-danger/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Reject</button>
                    </div>
                  </div>
                );
              }

              // rework
              return (
                <div key={req.id} className="p-4 border rounded-xl bg-background flex flex-col justify-between gap-3 shadow-sm">
                  <div>
                    <div className="flex justify-between items-start mb-1 gap-2">
                      <p className="font-semibold text-sm text-foreground">{req.employee?.name ?? empName(req.employee_id)}</p>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <AgeBadge createdAt={req.created_at} />
                        <span className="bg-info/10 text-info px-2 py-0.5 rounded text-xs font-medium border border-info/20">
                          {TYPE_LABEL[req.request_type] ?? req.request_type}
                        </span>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground capitalize">{req.employee?.role ?? empRole(req.employee_id)}</p>
                    {req.days_to_add?.length > 0 && <p className="text-xs text-muted-foreground mt-1">Add: {req.days_to_add.join(', ')}</p>}
                    {req.days_to_drop?.length > 0 && <p className="text-xs text-muted-foreground mt-1">Drop: {req.days_to_drop.join(', ')}</p>}
                    {req.proposed_schedule?.length > 0 && <p className="text-xs text-muted-foreground mt-1">New schedule: {req.proposed_schedule.join(', ')}</p>}
                    {req.reason && <p className="text-xs text-subtle mt-1 italic">"{req.reason}"</p>}
                  </div>
                  <div className="flex gap-2 mt-1">
                    <button onClick={() => approveRework(req.id)} className="flex-1 bg-success/10 text-success hover:bg-success/20 border border-success/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Approve</button>
                    <button onClick={() => rejectRework(req.id)}  className="flex-1 bg-danger/10 text-danger hover:bg-danger/20 border border-danger/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Reject</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 4-Week Availability Heatmap */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <Users className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">4-Week Availability Heatmap</h2>
          <span className="ml-auto text-xs text-subtle">Available staff by role per day</span>
        </div>

        {heatmapLoading ? (
          <div className="flex h-32 items-center justify-center">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-3">
            {/* Day-of-week header */}
            <div className="grid grid-cols-7 gap-1 pl-0">
              {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => (
                <div key={d} className="text-center text-xs font-medium text-muted-foreground/70 pb-1">{d}</div>
              ))}
            </div>

            {/* 4 calendar weeks */}
            {heatmapWeeks.map((week, wi) => (
              <div key={wi} className="grid grid-cols-7 gap-1">
                {week.map(dt => {
                  const d = new Date(dt + 'T00:00:00');
                  const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                  const isToday = dt === fmtDate(new Date());
                  const day = heatmapData[dt];
                  return (
                    <div
                      key={dt}
                      className={`rounded-lg border p-1.5 space-y-1 ${
                        isToday ? 'border-primary/50 bg-primary/5' : 'border-border/50 bg-card'
                      } ${isWeekend ? 'opacity-50' : ''}`}
                    >
                      <div className={`text-center text-xs font-semibold ${isToday ? 'text-primary' : 'text-foreground'}`}>
                        {d.getDate()}
                        {isToday && <span className="ml-1 text-[10px] text-primary/70">today</span>}
                      </div>
                      {(['driver', 'trainer', 'walker'] as const).map(role => {
                        const count = day?.[role] ?? 0;
                        return (
                          <div
                            key={role}
                            className={`flex items-center justify-between px-1 py-0.5 rounded text-[10px] ${heatCell(count)}`}
                            title={`${dt} — ${count} ${role}s available`}
                          >
                            <span className="capitalize opacity-70">{role[0].toUpperCase()}</span>
                            <span className="font-semibold">{count}</span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            ))}

            <div className="flex items-center gap-4 pt-1 text-xs text-subtle flex-wrap">
              <span className="flex items-center gap-1.5"><span className="inline-block w-5 h-4 rounded bg-success/45" /> High</span>
              <span className="flex items-center gap-1.5"><span className="inline-block w-5 h-4 rounded bg-success/25" /> Moderate</span>
              <span className="flex items-center gap-1.5"><span className="inline-block w-5 h-4 rounded bg-success/10" /> Low</span>
              <span className="flex items-center gap-1.5"><span className="inline-block w-5 h-4 rounded bg-accent/30" /> None</span>
              <span className="ml-auto opacity-60 text-[11px]">D = Driver · T = Trainer · W = Walker</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field staff personal schedule view
// ---------------------------------------------------------------------------

const Schedule = () => {
  const { groups, user } = useAuth();
  const isAdmin      = groups.includes('admin');
  const isManagement = groups.includes('management');
  const isPrivileged = isAdmin || isManagement;

  // All hooks must be declared before any early return
  const { confirmState: workerConfirmState, confirm: workerConfirm, cancelConfirm: workerCancelConfirm } = useConfirm();
  const [employees, setEmployees] = useState<any[]>([]);
  const [myId, setMyId]           = useState<string>('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scheduleData, setScheduleData]     = useState<ScheduleDay[]>([]);
  const [currentMonth, setCurrentMonth]     = useState<Date>(new Date());
  const [selectedDate, setSelectedDate]     = useState<string>('');
  const [pendingRequests, setPendingRequests] = useState<any[]>([]);

  const todayStr = fmtDate(new Date());

  useEffect(() => {
    if (isPrivileged) return;
    setLoadError(null);
    Promise.all([
      axiosClient.get('/employees/me').then(res => setMyId(res.data.id)),
      axiosClient.get('/employees/').then(res => {
        const sorted = res.data.sort((a: any, b: any) =>
          (a.name || '').localeCompare(b.name || '')
        );
        setEmployees(sorted);
      }),
    ]).catch(() => setLoadError('Failed to load schedule data. Please refresh.'));
    setSelectedDate(todayStr);
  }, [isPrivileged]);

  const fetchSchedule = async (employeeId: string, monthDate: Date) => {
    if (!employeeId) return;
    const startDate = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
    const endDate   = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0);
    try {
      const data = await getSchedule(employeeId, fmtDate(startDate), fmtDate(endDate));
      setScheduleData(data);
      setLoadError(null);
    } catch (err: any) {
      setLoadError(errorText(err, 'Failed to load schedule.'));
    }
  };

  useEffect(() => {
    if (!isPrivileged) fetchSchedule(myId, currentMonth);
  }, [myId, currentMonth, isPrivileged]);

  useEffect(() => {
    if (isPrivileged || !myId) return;
    axiosClient.get(`/time-off-requests/${myId}`)
      .then(res => setPendingRequests(res.data.filter((r: any) => r.status === 'pending')))
      .catch((e) => { console.error('Failed to load pending time-off requests:', e); });
  }, [isPrivileged, myId]);

  // Early return for privileged roles — all hooks are above this line
  if (isPrivileged) {
    return <ScheduleManagementView isAdmin={isAdmin} />;
  }

  const getDayData    = (dateStr: string) => scheduleData.find(s => s.date === dateStr);
  const selectedDayData = selectedDate ? getDayData(selectedDate) : null;
  const isFutureDate  = selectedDate > todayStr;

  const getTileClass = (dateStr: string) => {
    const d = getDayData(dateStr);
    if (!d) return '';
    if (d.status === 'Assigned' || d.status === 'Available') return 'bg-success/20 text-success hover:bg-success/30 font-bold border-success/30 border';
    if (d.status.includes('Pending')) return 'bg-warning/20 text-warning hover:bg-warning/30 font-bold border-warning/30 border';
    if (d.status.includes('Off') || d.status === 'Time Off') return 'bg-danger/20 text-danger hover:bg-danger/30 font-bold border-danger/30 border';
    return '';
  };

  const getStatusBadge = (status: string) => {
    if (status === 'Off (Recurring)' || status === 'Time Off') return 'badge-danger';
    if (status === 'Pending Off (Recurring)' || status === 'Pending Time Off') return 'badge-warning';
    if (status === 'Assigned' || status === 'Available') return 'badge-success';
    return 'badge bg-accent text-muted-foreground';
  };

  const handleRequestSpecificPTO = async (dateStr: string) => {
    if (!myId) return;
    try {
      await createTimeOffRequest(myId, dateStr);
      await fetchSchedule(myId, currentMonth);
    } catch (err: any) {
      const alertText = errorText(err, ''); if (alertText) alert(alertText);
    }
  };

  const handleCancelPTO = async (dateStr: string) => {
    const ok = await workerConfirm({
      title: 'Cancel PTO Request',
      message: 'Are you sure you want to cancel this PTO request?',
      confirmLabel: 'Yes, Cancel It',
      variant: 'warning',
    });
    if (!ok) return;
    try {
      const normalize = (d: string) => d.split('T')[0];
      const req = pendingRequests.find(r => normalize(r.date) === normalize(dateStr));
      if (!req) return alert('No pending PTO request found for this date.');
      await axiosClient.delete(`/time-off-requests/${req.id}`);
      setPendingRequests(prev => prev.filter(r => r.id !== req.id));
      await fetchSchedule(myId, currentMonth);
    } catch {
      alert('Failed to cancel PTO request.');
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-slide-up">
      <ConfirmDialog {...workerConfirmState} onCancel={workerCancelConfirm} />
      <h1 className="page-title">My Schedule</h1>

      {loadError && (
        <div className="card border-danger/30 bg-danger/5 text-danger text-sm px-4 py-3 rounded-xl">{loadError}</div>
      )}


      {myId ? (
        <div className="flex flex-col gap-8 items-center max-w-2xl mx-auto w-full">
          <div className="flex flex-col w-full bg-background/50 p-6 rounded-2xl border border-border/50 shadow-sm items-center">
            <MiniCalendar
              selectedDate={selectedDate}
              onSelectDate={setSelectedDate}
              onMonthChange={setCurrentMonth}
              getTileClassName={getTileClass}
            />
            <div className="flex flex-col sm:flex-row flex-wrap items-center gap-4 mt-6 text-sm font-medium text-muted-foreground w-full justify-center">
              <span className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-success/30 border border-success" /> Scheduled Workday</span>
              <span className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-warning/30 border border-warning" /> Pending PTO</span>
              <span className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-danger/30 border border-danger" /> Scheduled Off</span>
            </div>
          </div>

          <div className="w-full">
            <div className="card h-full flex flex-col min-h-[300px]">
              <h2 className="section-title mb-4 flex items-center gap-2">
                <CalendarDays className="w-5 h-5 text-primary" />
                {selectedDate
                  ? new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
                  : 'Select a Date'}
              </h2>

              {!selectedDate ? (
                <div className="text-center py-10 opacity-60 flex-1 flex items-center justify-center">
                  <p className="text-sm">Click a date on the calendar to view details.</p>
                </div>
              ) : selectedDayData ? (
                <div className="space-y-4">
                  <span className={getStatusBadge(selectedDayData.status)}>{selectedDayData.status}</span>
                  {selectedDayData.status === 'Assigned' ? (
                    <div className="mt-4 p-4 rounded-xl bg-success/5 border border-success/20">
                      <div className="flex items-center gap-2 text-sm font-semibold text-foreground mb-3">
                        <Clock className="w-4 h-4 text-success" />
                        Assigned to: {selectedDayData.truck_name}
                      </div>
                      {selectedDayData.crew && selectedDayData.crew.length > 0 && (
                        <div className="flex items-start gap-2 mt-2 text-sm text-foreground">
                          <Users className="w-4 h-4 mt-0.5 text-success" />
                          <span>Crew: {selectedDayData.crew.map(c => `${c.role}: ${c.name}`).join(', ')}</span>
                        </div>
                      )}
                    </div>
                  ) : (selectedDayData.status === 'Pending Time Off' || selectedDayData.status === 'Pending Off (Recurring)') ? (
                    <div className="mt-4 p-6 rounded-xl bg-warning/5 border border-warning/20 flex flex-col items-center justify-center text-center space-y-2">
                      <XCircle className="w-8 h-8 text-warning/60 mb-2" />
                      <p className="text-sm font-medium text-foreground">Your PTO request is pending manager approval.</p>
                      <button onClick={() => handleCancelPTO(selectedDate)} className="btn-danger mt-2">Cancel Request</button>
                    </div>
                  ) : selectedDayData.status.includes('Off') ? (
                    <div className="mt-4 p-6 rounded-xl bg-danger/5 border border-danger/20 flex flex-col items-center justify-center text-center space-y-2">
                      <XCircle className="w-8 h-8 text-danger/60 mb-2" />
                      <p className="text-sm font-medium text-foreground">You are scheduled off for this day.</p>
                      <p className="text-xs text-subtle">Enjoy your rest!</p>
                    </div>
                  ) : (
                    <div className="mt-4">
                      {isFutureDate ? (
                        <div className="space-y-3">
                          <p className="text-sm text-subtle mb-4">You are currently listed as Available. You can request this day off.</p>
                          <button onClick={() => handleRequestSpecificPTO(selectedDate)} className="btn-primary w-full shadow py-3 text-sm">
                            Request PTO
                          </button>
                        </div>
                      ) : (
                        <div className="text-center py-6 text-subtle text-sm bg-accent/20 rounded-xl border border-border/50">
                          You were available but not dispatched on this day.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : isFutureDate ? (
                <div className="space-y-4">
                  <span className="badge bg-accent text-accent-foreground font-semibold">Available</span>
                  <div className="bg-background border border-border rounded-xl p-4 mt-4 text-center">
                    <p className="text-sm text-subtle mb-4">No assignments yet. You may request this day off.</p>
                    <button onClick={() => handleRequestSpecificPTO(selectedDate)} className="btn-primary w-full shadow py-3">Request PTO</button>
                  </div>
                </div>
              ) : (
                <div className="text-center py-10 opacity-60 flex-1 flex flex-col items-center justify-center bg-accent/20 rounded-xl border border-border/50">
                  <CalendarDays className="w-10 h-10 mb-2 text-muted-foreground/50" />
                  <p className="text-sm">No assignment data available for this date.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center py-12 flex flex-col items-center justify-center opacity-60 card bg-accent/20 border-dashed">
          <Users className="w-12 h-12 mb-4 text-muted-foreground/30" />
          <h3 className="text-base font-medium">No Employee Profile Found</h3>
          <p className="text-sm mt-1 max-w-sm">Could not resolve your employee record. Contact an admin if this persists.</p>
        </div>
      )}
    </div>
  );
};

export default Schedule;
