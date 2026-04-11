import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  Shield, Users, Truck, Database, AlertTriangle, ClipboardCheck,
  BarChart2, RefreshCw, CheckCircle2, XCircle,
} from 'lucide-react';

const API = 'http://localhost:8000/api/v1';

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
  const [loading, setLoading] = useState(true);

  const fetchAll = () => {
    setLoading(true);
    Promise.allSettled([
      axios.get(`${API}/employees/`).then(r => setEmployees(r.data)),
      axios.get(`${API}/trucks/`).then(r => setTrucks(r.data)),
      axios.get(`${API}/incidents/?resolved=false`).then(r => setIncidents(r.data)),
      axios.get(`${API}/training/daily/active`).then(r => setTrainingToday(r.data)),
    ]).finally(() => setLoading(false));
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
    axios.put(`${API}/employees/${id}/deactivate`).then(() => {
      setEmployees(prev => prev.map(e => e.id === id ? { ...e, is_active: false } : e));
    }).catch(console.error);
  };

  const handleDeactivateTruck = (id: string) => {
    if (!window.confirm('Deactivate this truck?')) return;
    axios.put(`${API}/trucks/${id}/deactivate`).then(() => {
      setTrucks(prev => prev.map(t => t.id === id ? { ...t, is_active: false } : t));
    }).catch(console.error);
  };

  const handleResolveIncident = (id: string) => {
    axios.patch(`${API}/incidents/${id}/resolve`).then(() => {
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
          <span className="ml-auto text-xs text-subtle">{employees.filter(e => e.is_active).length} active</span>
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
              {employees.map(e => (
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
