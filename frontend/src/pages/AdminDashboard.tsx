import React, { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import {
  Shield, Users, Truck, Database, AlertTriangle, ClipboardCheck,
  BarChart2, RefreshCw, CheckCircle2, XCircle, MessageSquare, Bug, Lightbulb,
} from 'lucide-react';

type Feedback = {
  id: string;
  employee_id: string | null;
  type: 'bug' | 'feature_request' | 'general';
  message: string;
  status: 'new' | 'in_progress' | 'resolved';
  created_at: string;
};

type Employee = {
  id: string;
  name: string;
  role: string;
  discord_id: string;
  is_active: boolean;
};

type Truck = {
  id: string;
  name: string;
  is_active: boolean;
};

export default function AdminDashboard() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [trucks, setTrucks] = useState<Truck[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [trainingToday, setTrainingToday] = useState<any[]>([]);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [feedbackFilter, setFeedbackFilter] = useState<'all' | 'new' | 'in_progress' | 'resolved'>('all');
  const [loading, setLoading] = useState(true);
  const [rosterPage, setRosterPage] = useState(0);

  const ROSTER_PAGE_SIZE = 50;

  const fetchAll = () => {
    setLoading(true);
    Promise.allSettled([
      axiosClient.get('/employees/?include_inactive=true&limit=500').then(r => setEmployees(r.data)),
      axiosClient.get('/trucks/?include_inactive=true').then(r => setTrucks(r.data)),
      axiosClient.get('/incidents/?resolved=false').then(r => setIncidents(r.data)),
      axiosClient.get('/training/daily/active').then(r => setTrainingToday(r.data)),
      axiosClient.get('/feedback/?limit=200').then(r => setFeedback(r.data)),
    ]).finally(() => setLoading(false));
  };

  const handleUpdateFeedbackStatus = (id: string, newStatus: Feedback['status']) => {
    axiosClient.patch(`/feedback/${id}/status`, { status: newStatus })
      .then(r => setFeedback(prev => prev.map(f => f.id === id ? r.data : f)))
      .catch(console.error);
  };

  useEffect(() => { fetchAll(); }, []);

  const roleGroups = employees.reduce<Record<string, number>>((acc, e) => {
    acc[e.role] = (acc[e.role] || 0) + 1;
    return acc;
  }, {});

  const ROLE_ORDER = ['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin'];
  const roleRows = ROLE_ORDER
    .filter(r => roleGroups[r])
    .map(r => ({ role: r, count: roleGroups[r] }));

  const handleDeactivateEmployee = (id: string) => {
    if (!window.confirm('Deactivate this employee?')) return;
    axiosClient.put(`/employees/${id}/deactivate`).then(() => {
      setEmployees(prev => prev.map(e => e.id === id ? { ...e, is_active: false } : e));
    }).catch(console.error);
  };

  const handleDeactivateTruck = (id: string) => {
    if (!window.confirm('Deactivate this truck?')) return;
    axiosClient.put(`/trucks/${id}/deactivate`).then(() => {
      setTrucks(prev => prev.map(t => t.id === id ? { ...t, is_active: false } : t));
    }).catch(console.error);
  };

  const handleResolveIncident = (id: string) => {
    axiosClient.patch(`/incidents/${id}/resolve`).then(() => {
      setIncidents(prev => prev.filter(i => i.id !== id));
    }).catch(console.error);
  };

  if (loading) {
    return (
      <div className="flex h-60 items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-muted-foreground">Loading admin panel…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Shield className="w-6 h-6 text-primary" /> Admin Dashboard
          </h1>
          <p className="text-subtle mt-1">System overview — employees, trucks, incidents, and training.</p>
        </div>
        <button onClick={fetchAll} className="btn-ghost text-muted-foreground flex items-center gap-2 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Active Employees', value: employees.filter(e => e.is_active).length, icon: Users, color: 'text-info' },
          { label: 'Active Trucks', value: trucks.filter(t => t.is_active).length, icon: Truck, color: 'text-primary' },
          { label: 'Open Incidents', value: incidents.length, icon: AlertTriangle, color: incidents.length > 0 ? 'text-danger' : 'text-success' },
          { label: 'Training Today', value: trainingToday.length, icon: ClipboardCheck, color: 'text-info' },
        ].map(stat => (
          <div key={stat.label} className="card-elevated flex items-center gap-4">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-accent shrink-0">
              <stat.icon className={`w-5 h-5 ${stat.color}`} />
            </div>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
              <p className="text-2xl font-bold text-foreground mt-0.5">{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Workforce breakdown */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <BarChart2 className="w-5 h-5 text-primary" />
            <h2 className="text-base font-semibold text-foreground">Workforce Breakdown</h2>
          </div>
          <div className="space-y-2">
            {roleRows.map(({ role, count }) => (
              <div key={role} className="flex items-center justify-between">
                <span className="text-sm capitalize text-foreground">{role}</span>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 rounded-full bg-accent overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full"
                      style={{ width: `${Math.min((count / employees.length) * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-sm font-semibold text-foreground w-6 text-right">{count}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 pt-4 border-t border-border">
            <p className="text-xs text-subtle uppercase tracking-wider font-medium mb-2">Inactive Employees</p>
            {employees.filter(e => !e.is_active).length === 0 ? (
              <p className="text-sm text-subtle">None.</p>
            ) : (
              <div className="space-y-1">
                {employees.filter(e => !e.is_active).slice(0, 5).map(e => (
                  <p key={e.id} className="text-sm text-muted-foreground capitalize">{e.name} · {e.role}</p>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Open incidents */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <AlertTriangle className="w-5 h-5 text-danger" />
            <h2 className="text-base font-semibold text-foreground">Open Incidents</h2>
            {incidents.length > 0 && (
              <span className="ml-auto text-xs font-bold bg-danger text-white px-2 py-0.5 rounded-full">
                {incidents.length}
              </span>
            )}
          </div>
          {incidents.length === 0 ? (
            <div className="text-center py-8 opacity-60">
              <CheckCircle2 className="w-10 h-10 mb-3 text-success mx-auto" />
              <p className="text-sm font-medium">All incidents resolved.</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
              {incidents.map(inc => (
                <div key={inc.id} className={`p-3 rounded-xl border bg-background ${
                  inc.severity === 'critical' ? 'border-danger/40' : inc.severity === 'warning' ? 'border-warning/40' : 'border-border'
                }`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <span className={`text-xs font-bold uppercase tracking-wider ${
                        inc.severity === 'critical' ? 'text-danger' : inc.severity === 'warning' ? 'text-warning' : 'text-info'
                      }`}>{inc.severity}</span>
                      <p className="text-sm font-medium text-foreground mt-0.5">
                        {inc.category?.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                      </p>
                      <p className="text-xs text-subtle">{inc.reporter_name} · {inc.date}</p>
                    </div>
                    <button
                      onClick={() => handleResolveIncident(inc.id)}
                      className="shrink-0 p-1.5 rounded-lg bg-success/10 hover:bg-success/20 text-success transition-colors"
                      title="Mark resolved"
                    >
                      <CheckCircle2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Training today */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <ClipboardCheck className="w-5 h-5 text-info" />
            <h2 className="text-base font-semibold text-foreground">Training Sessions Today</h2>
          </div>
          {trainingToday.length === 0 ? (
            <div className="text-center py-8 opacity-60">
              <Database className="w-10 h-10 mb-3 text-muted-foreground mx-auto" />
              <p className="text-sm font-medium">No training sessions today.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
              {trainingToday.map((t: any) => (
                <div key={t.record?.id} className="p-3 rounded-xl border border-border bg-background">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">
                        {t.trainee?.name ?? 'Unknown trainee'}
                      </p>
                      <p className="text-xs text-subtle">
                        Trainer: {t.trainer?.name ?? 'Unassigned'}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs font-semibold text-foreground">
                        {t.progress?.completed}/{t.progress?.total}
                      </p>
                      <p className="text-xs text-subtle">tasks done</p>
                    </div>
                  </div>
                  {t.progress?.total > 0 && (
                    <div className="mt-2 h-1.5 rounded-full bg-accent overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all"
                        style={{ width: `${(t.progress.completed / t.progress.total) * 100}%` }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Employee roster */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <Users className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Employee Roster</h2>
          <span className="ml-auto text-xs text-subtle">{employees.filter(e => e.is_active).length} active · {employees.length} total</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <th className="pb-2 pr-4">Name</th>
                <th className="pb-2 pr-4">Role</th>
                <th className="pb-2 pr-4">Discord ID</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {employees.slice(rosterPage * ROSTER_PAGE_SIZE, (rosterPage + 1) * ROSTER_PAGE_SIZE).map(e => (
                <tr key={e.id} className={`${!e.is_active ? 'opacity-40' : ''}`}>
                  <td className="py-2 pr-4 font-medium text-foreground">{e.name}</td>
                  <td className="py-2 pr-4 capitalize text-muted-foreground">{e.role}</td>
                  <td className="py-2 pr-4 text-muted-foreground font-mono text-xs">{e.discord_id || '—'}</td>
                  <td className="py-2 pr-4">
                    {e.is_active ? (
                      <span className="inline-flex items-center gap-1 text-success text-xs font-medium">
                        <CheckCircle2 className="w-3 h-3" /> Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-muted-foreground text-xs font-medium">
                        <XCircle className="w-3 h-3" /> Inactive
                      </span>
                    )}
                  </td>
                  <td className="py-2">
                    {e.is_active && (
                      <button
                        onClick={() => handleDeactivateEmployee(e.id)}
                        className="text-xs text-danger hover:underline"
                      >
                        Deactivate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Pagination controls */}
        {employees.length > ROSTER_PAGE_SIZE && (
          <div className="flex items-center justify-between pt-4 mt-2 border-t border-border">
            <p className="text-xs text-subtle">
              {rosterPage * ROSTER_PAGE_SIZE + 1}–{Math.min((rosterPage + 1) * ROSTER_PAGE_SIZE, employees.length)} of {employees.length} employees
            </p>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setRosterPage(p => p - 1)}
                disabled={rosterPage === 0}
                className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>
              {Array.from({ length: Math.ceil(employees.length / ROSTER_PAGE_SIZE) }).map((_, i) => (
                <button
                  key={i}
                  onClick={() => setRosterPage(i)}
                  className={`w-7 h-7 text-xs rounded-lg border transition-colors ${
                    i === rosterPage
                      ? 'bg-primary text-white border-primary'
                      : 'border-border hover:bg-accent'
                  }`}
                >
                  {i + 1}
                </button>
              ))}
              <button
                onClick={() => setRosterPage(p => p + 1)}
                disabled={rosterPage >= Math.ceil(employees.length / ROSTER_PAGE_SIZE) - 1}
                className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Feedback Inbox */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4 flex-wrap">
          <MessageSquare className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Feedback Inbox</h2>
          <span className="ml-1 text-xs text-subtle">
            {feedback.filter(f => f.status === 'new').length} new
          </span>
          <div className="ml-auto flex items-center gap-1 flex-wrap">
            {(['all', 'new', 'in_progress', 'resolved'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFeedbackFilter(f)}
                className={`px-2.5 py-1 text-xs rounded-lg border transition-colors capitalize ${
                  feedbackFilter === f
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'border-border hover:bg-accent text-muted-foreground'
                }`}
              >
                {f.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>

        {feedback.length === 0 ? (
          <div className="text-center py-8 opacity-60">
            <MessageSquare className="w-10 h-10 mb-3 text-muted-foreground mx-auto" />
            <p className="text-sm font-medium">No feedback submitted yet.</p>
          </div>
        ) : (() => {
          const visible = feedback.filter(f => feedbackFilter === 'all' || f.status === feedbackFilter);
          if (visible.length === 0) {
            return <p className="text-sm text-subtle text-center py-6">No feedback matching this filter.</p>;
          }
          return (
            <div className="space-y-3 max-h-[480px] overflow-y-auto pr-1">
              {visible.map(f => {
                const typeIcon = f.type === 'bug'
                  ? <Bug className="w-3.5 h-3.5" />
                  : f.type === 'feature_request'
                    ? <Lightbulb className="w-3.5 h-3.5" />
                    : <MessageSquare className="w-3.5 h-3.5" />;

                const typeLabel: Record<string, string> = {
                  bug: 'Bug Report',
                  feature_request: 'Feature Request',
                  general: 'General',
                };

                const statusColors: Record<string, string> = {
                  new: 'bg-info/10 text-info',
                  in_progress: 'bg-warning/10 text-warning',
                  resolved: 'bg-success/10 text-success',
                };

                const daysSince = Math.floor(
                  (Date.now() - new Date(f.created_at).getTime()) / 86_400_000
                );
                const ageCls = daysSince >= 7
                  ? 'bg-danger/10 text-danger'
                  : daysSince >= 3
                    ? 'bg-warning/10 text-warning'
                    : 'bg-accent text-muted-foreground';

                return (
                  <div key={f.id} className="p-3 rounded-xl border border-border bg-background space-y-2">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-accent text-foreground capitalize">
                          {typeIcon}{typeLabel[f.type] ?? f.type}
                        </span>
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${statusColors[f.status] ?? 'bg-accent text-muted-foreground'}`}>
                          {f.status.replace('_', ' ')}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${ageCls}`}>
                          {daysSince === 0 ? 'today' : `${daysSince}d ago`}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 ml-auto">
                        {f.status !== 'in_progress' && (
                          <button
                            onClick={() => handleUpdateFeedbackStatus(f.id, 'in_progress')}
                            className="text-xs px-2 py-1 rounded-lg border border-warning/40 text-warning hover:bg-warning/10 transition-colors"
                          >
                            In Progress
                          </button>
                        )}
                        {f.status !== 'resolved' && (
                          <button
                            onClick={() => handleUpdateFeedbackStatus(f.id, 'resolved')}
                            className="text-xs px-2 py-1 rounded-lg border border-success/40 text-success hover:bg-success/10 transition-colors"
                          >
                            Resolve
                          </button>
                        )}
                        {f.status === 'resolved' && (
                          <button
                            onClick={() => handleUpdateFeedbackStatus(f.id, 'new')}
                            className="text-xs px-2 py-1 rounded-lg border border-border text-muted-foreground hover:bg-accent transition-colors"
                          >
                            Reopen
                          </button>
                        )}
                      </div>
                    </div>
                    <p className="text-sm text-foreground leading-relaxed">{f.message}</p>
                    {f.employee_id && (
                      <p className="text-xs text-subtle">Submitted by employee ID: {f.employee_id}</p>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })()}
      </div>

      {/* Truck roster */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <Truck className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Truck Fleet</h2>
          <span className="ml-auto text-xs text-subtle">{trucks.filter(t => t.is_active).length} active</span>
        </div>
        {trucks.length === 0 ? (
          <p className="text-sm text-subtle text-center py-6">No trucks found.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {trucks.map(t => (
              <div key={t.id} className={`p-3 rounded-xl border text-center space-y-1 ${
                t.is_active ? 'border-border bg-background' : 'border-border/30 bg-accent/20 opacity-50'
              }`}>
                <p className="text-sm font-semibold text-foreground">{t.name}</p>
                <p className={`text-xs font-medium ${t.is_active ? 'text-success' : 'text-muted-foreground'}`}>
                  {t.is_active ? 'Active' : 'Inactive'}
                </p>
                {t.is_active && (
                  <button
                    onClick={() => handleDeactivateTruck(t.id)}
                    className="text-xs text-danger hover:underline block mx-auto"
                  >
                    Deactivate
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
