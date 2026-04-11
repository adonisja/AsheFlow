import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../../contexts/AuthContext';
import {
  Truck, ClipboardCheck, Calendar, Check, X, AlertTriangle,
} from 'lucide-react';

const API = 'http://localhost:8000/api/v1';

export default function DispatchView() {
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');

  const [pendingRequests, setPendingRequests] = useState<any[]>([]);
  const [pendingOffDays, setPendingOffDays] = useState<any[]>([]);
  const [pendingChangeRequests, setPendingChangeRequests] = useState<any[]>([]);
  const [urgentIncidents, setUrgentIncidents] = useState<any[]>([]);
  const [fleetStatus, setFleetStatus] = useState<any[]>([]);

  useEffect(() => {
    axios.get(`${API}/time-off-requests/`).then(res =>
      setPendingRequests(res.data.filter((r: any) => r.status === 'pending'))
    ).catch(console.error);

    axios.get(`${API}/employee-off-days/`).then(res =>
      setPendingOffDays(res.data.filter((r: any) => r.status === 'pending'))
    ).catch(console.error);

    axios.get(`${API}/assignment-change-requests/pending`).then(res =>
      setPendingChangeRequests(res.data)
    ).catch(console.error);

    axios.get(`${API}/incidents/unresolved-urgent`).then(res =>
      setUrgentIncidents(res.data)
    ).catch(console.error);

    axios.get(`${API}/field-ops/returns/summary`).then(res =>
      setFleetStatus(res.data)
    ).catch(console.error);
  }, []);

  const handleApprove = (type: 'request' | 'offDay', id: string) => {
    const url = type === 'request'
      ? `${API}/time-off-requests/${id}/approve`
      : `${API}/employee-off-days/${id}/approve`;
    axios.patch(url).then(() => {
      if (type === 'request') setPendingRequests(p => p.filter(r => r.id !== id));
      else setPendingOffDays(p => p.filter(r => r.id !== id));
    }).catch(console.error);
  };

  const handleReject = (type: 'request' | 'offDay', id: string) => {
    const url = type === 'request'
      ? `${API}/time-off-requests/${id}/reject`
      : `${API}/employee-off-days/${id}/reject`;
    axios.patch(url).then(() => {
      if (type === 'request') setPendingRequests(p => p.filter(r => r.id !== id));
      else setPendingOffDays(p => p.filter(r => r.id !== id));
    }).catch(console.error);
  };

  const handleApproveChange = (id: string) => {
    axios.patch(`${API}/assignment-change-requests/${id}/approve`).then(() =>
      setPendingChangeRequests(p => p.filter(r => r.id !== id))
    ).catch(console.error);
  };

  const handleRejectChange = (id: string) => {
    axios.patch(`${API}/assignment-change-requests/${id}/reject`).then(() =>
      setPendingChangeRequests(p => p.filter(r => r.id !== id))
    ).catch(console.error);
  };

  const quickLinks = [
    { icon: Truck, label: 'Dispatch Center', desc: 'Run daily algorithmic dispatch & manual overrides', href: '/dispatch' },
    { icon: AlertTriangle, label: 'Incidents', desc: 'Review and resolve open field incident reports', href: '/incidents' },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Quick links */}
        <div className="card h-full">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <Truck className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold text-foreground">Dispatch Portal</h2>
          </div>
          <p className="text-sm text-subtle leading-relaxed mb-4">
            Operational hub — run dispatch, manage assignments, and coordinate daily field activity.
          </p>
          <div className="grid grid-cols-1 gap-3">
            {quickLinks.map(link => (
              <a key={link.label} href={link.href}
                className="flex text-left items-start gap-4 p-3 rounded-lg hover:bg-accent/50 border border-transparent hover:border-border transition-colors group">
                <div className="flex items-center justify-center w-10 h-10 shrink-0 rounded-lg bg-primary/10 group-hover:bg-primary/20 transition-colors">
                  <link.icon className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <p className="font-semibold text-foreground text-sm">{link.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{link.desc}</p>
                </div>
              </a>
            ))}
          </div>
        </div>

        {/* Pending approvals */}
        <div className="card bg-accent/20 border-primary/20 h-full">
          <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
            <ClipboardCheck className="w-5 h-5 text-info" />
            <h2 className="text-lg font-semibold text-foreground">Pending Approvals</h2>
            {(pendingRequests.length + pendingOffDays.length + pendingChangeRequests.length) > 0 && (
              <span className="ml-auto text-xs font-bold bg-primary text-white px-2 py-0.5 rounded-full">
                {pendingRequests.length + pendingOffDays.length + pendingChangeRequests.length}
              </span>
            )}
          </div>
          {pendingRequests.length === 0 && pendingOffDays.length === 0 && pendingChangeRequests.length === 0 ? (
            <div className="text-center py-8 opacity-60">
              <Calendar className="w-10 h-10 mb-3 text-muted-foreground mx-auto" />
              <p className="text-sm font-medium">No pending requests.</p>
              <p className="text-xs text-subtle mt-1">Worker requests will appear here for review.</p>
            </div>
          ) : (
            <div className="space-y-4 max-h-[340px] overflow-y-auto pr-1">
              {pendingRequests.map(r => (
                <div key={r.id} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-background border border-border">
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className="text-xs font-bold text-subtle uppercase tracking-wider">Time Off</span>
                    <span className="text-sm font-medium text-foreground truncate">{r.employee_name || r.employee_id}</span>
                    <span className="text-xs text-subtle">{r.date}</span>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button onClick={() => handleApprove('request', r.id)} className="p-1.5 rounded-lg bg-success/10 hover:bg-success/20 text-success transition-colors"><Check className="w-4 h-4" /></button>
                    <button onClick={() => handleReject('request', r.id)} className="p-1.5 rounded-lg bg-danger/10 hover:bg-danger/20 text-danger transition-colors"><X className="w-4 h-4" /></button>
                  </div>
                </div>
              ))}
              {pendingOffDays.map(r => (
                <div key={r.id} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-background border border-border">
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className="text-xs font-bold text-subtle uppercase tracking-wider">Day Off</span>
                    <span className="text-sm font-medium text-foreground truncate">{r.employee_name || r.employee_id}</span>
                    <span className="text-xs text-subtle">{r.day_of_week}</span>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button onClick={() => handleApprove('offDay', r.id)} className="p-1.5 rounded-lg bg-success/10 hover:bg-success/20 text-success transition-colors"><Check className="w-4 h-4" /></button>
                    <button onClick={() => handleReject('offDay', r.id)} className="p-1.5 rounded-lg bg-danger/10 hover:bg-danger/20 text-danger transition-colors"><X className="w-4 h-4" /></button>
                  </div>
                </div>
              ))}
              {pendingChangeRequests.map(r => (
                <div key={r.id} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-background border border-border">
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className="text-xs font-bold text-subtle uppercase tracking-wider">Reassignment</span>
                    <span className="text-sm font-medium text-foreground truncate">{r.employee?.name || r.employee_id}</span>
                    <span className="text-xs text-subtle">{r.requested_date}{r.reason ? ` · ${r.reason}` : ''}</span>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button onClick={() => handleApproveChange(r.id)} className="p-1.5 rounded-lg bg-success/10 hover:bg-success/20 text-success transition-colors"><Check className="w-4 h-4" /></button>
                    <button onClick={() => handleRejectChange(r.id)} className="p-1.5 rounded-lg bg-danger/10 hover:bg-danger/20 text-danger transition-colors"><X className="w-4 h-4" /></button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Active incidents */}
        <div className="card bg-danger/5 border-danger/20 h-full">
          <div className="flex items-center justify-between border-b border-border/50 pb-3 mb-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-danger" />
              <h2 className="text-lg font-semibold text-foreground">Active Incidents</h2>
            </div>
            {urgentIncidents.length > 0 && (
              <span className="text-xs font-bold bg-danger text-white px-2 py-0.5 rounded-full">
                {urgentIncidents.length}
              </span>
            )}
          </div>
          {urgentIncidents.length === 0 ? (
            <div className="text-center py-8 opacity-60">
              <AlertTriangle className="w-10 h-10 mb-3 text-muted-foreground mx-auto" />
              <p className="text-sm font-medium">No active incidents.</p>
              <p className="text-xs text-subtle mt-1">Unresolved warnings and critical reports appear here.</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[340px] overflow-y-auto pr-1">
              {urgentIncidents.map(inc => (
                <div key={inc.id} className={`p-3 rounded-xl border bg-background ${inc.severity === 'critical' ? 'border-danger/40' : 'border-warning/40'}`}>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className={`text-xs font-bold uppercase tracking-wider ${inc.severity === 'critical' ? 'text-danger' : 'text-warning'}`}>
                      {inc.severity}
                    </span>
                    <span className="text-xs text-subtle">{inc.date}</span>
                  </div>
                  <p className="text-sm font-medium text-foreground">
                    {inc.category.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                  </p>
                  <p className="text-xs text-subtle mt-0.5">{inc.reporter_name}{inc.truck_name ? ` · ${inc.truck_name}` : ''}</p>
                  <p className="text-xs text-foreground/70 mt-1 line-clamp-2">{inc.description}</p>
                </div>
              ))}
              <a href="/incidents" className="block text-center text-xs text-primary hover:underline pt-1">View all incidents →</a>
            </div>
          )}
        </div>
      </div>

      {/* Fleet Return Status */}
      <div className="card border-border/60">
        <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
          <Truck className="w-5 h-5 text-primary" />
          <h2 className="text-lg font-semibold text-foreground">Fleet Return Status — Today</h2>
          <span className="ml-auto text-xs text-subtle">
            {fleetStatus.filter((d: any) => d.status === 'returned').length} / {fleetStatus.length} returned
          </span>
        </div>
        {fleetStatus.length === 0 ? (
          <p className="text-sm text-subtle text-center py-6">No departures recorded today.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
            {fleetStatus.map((d: any) => (
              <div key={d.employee_id} className={`p-3 rounded-xl border text-center space-y-1 ${d.status === 'returned' ? 'border-success/30 bg-success/5' : 'border-warning/30 bg-warning/5'}`}>
                <p className="text-sm font-semibold text-foreground truncate">{d.driver_name}</p>
                <p className={`text-xs font-bold uppercase tracking-wider ${d.status === 'returned' ? 'text-success' : 'text-warning'}`}>
                  {d.status === 'returned' ? 'Returned' : 'Out'}
                </p>
                {d.duration_minutes != null ? (
                  <p className="text-xs text-subtle">{Math.floor(d.duration_minutes / 60)}h {d.duration_minutes % 60}m</p>
                ) : d.departed_at ? (
                  <p className="text-xs text-subtle">
                    Departed {new Date(d.departed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
