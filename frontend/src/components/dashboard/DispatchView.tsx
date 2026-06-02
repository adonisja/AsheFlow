import React, { useEffect, useState } from 'react';
import axiosClient from '../../api/axiosClient';
import { useAuth } from '../../contexts/AuthContext';
import {
  Truck, ClipboardCheck, Calendar, Check, X, AlertTriangle, Package,
} from 'lucide-react';
import { getLocalYMD } from '../../utils/date';
import ConfirmDialog from '../ui/ConfirmDialog';
import { useConfirm } from '../../hooks/useConfirm';

export default function DispatchView() {
  const { confirmState, confirm, cancelConfirm } = useConfirm();
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');
  const today = getLocalYMD();

  const [pendingRequests, setPendingRequests]         = useState<any[]>([]);
  const [pendingOffDays, setPendingOffDays]           = useState<any[]>([]);
  const [pendingChangeRequests, setPendingChangeRequests] = useState<any[]>([]);
  const [urgentIncidents, setUrgentIncidents]         = useState<any[]>([]);
  const [fleetAssignments, setFleetAssignments]       = useState<any[]>([]);
  const [pendingRTS, setPendingRTS]                   = useState<any[]>([]);
  const [loadErrors, setLoadErrors]                   = useState<string[]>([]);
  const [actionError, setActionError]                 = useState<string | null>(null);

  useEffect(() => {
    const errors: string[] = [];
    const fetches = [
      axiosClient.get('/time-off-requests/').then(res =>
        setPendingRequests(res.data.filter((r: any) => r.status === 'pending'))
      ).catch(() => { errors.push('time-off requests'); }),

      axiosClient.get('/employee-off-days/').then(res =>
        setPendingOffDays(res.data.filter((r: any) => r.status === 'pending'))
      ).catch(() => { errors.push('off-day requests'); }),

      axiosClient.get('/assignment-change-requests/pending').then(res =>
        setPendingChangeRequests(res.data)
      ).catch(() => { errors.push('reassignment requests'); }),

      axiosClient.get('/incidents/unresolved-urgent').then(res =>
        setUrgentIncidents(res.data)
      ).catch(() => { errors.push('incidents'); }),

      // Fleet status from TruckAssignment status (wired since 2026-05-02)
      axiosClient.get(`/dispatch/${today}`).then(res => {
        const assignments = res.data?.truck_assignments ?? [];
        setFleetAssignments(assignments);
      }).catch(() => { errors.push('fleet status'); }),

      axiosClient.get('/shift-ops/rts-reports/pending').then(res =>
        setPendingRTS(res.data)
      ).catch(() => { errors.push('RTS requests'); }),
    ];
    Promise.allSettled(fetches).then(() => {
      if (errors.length > 0) setLoadErrors(errors);
    });
  }, []);

  const handleApprove = async (type: 'request' | 'offDay', id: string) => {
    const label = type === 'request' ? 'PTO request' : 'off-day request';
    const ok = await confirm({ title: 'Approve Request', message: `Approve this ${label}?`, confirmLabel: 'Approve', variant: 'default' });
    if (!ok) return;
    const url = type === 'request' ? `/time-off-requests/${id}/approve` : `/employee-off-days/${id}/approve`;
    try {
      await axiosClient.patch(url);
      if (type === 'request') setPendingRequests(p => p.filter(r => r.id !== id));
      else setPendingOffDays(p => p.filter(r => r.id !== id));
    } catch {
      setActionError(`Failed to approve ${label}. Please try again.`);
    }
  };

  const handleReject = async (type: 'request' | 'offDay', id: string) => {
    const label = type === 'request' ? 'PTO request' : 'off-day request';
    const ok = await confirm({ title: 'Reject Request', message: `Reject this ${label}? The employee will be notified.`, confirmLabel: 'Reject', variant: 'danger' });
    if (!ok) return;
    const url = type === 'request' ? `/time-off-requests/${id}/reject` : `/employee-off-days/${id}/reject`;
    try {
      await axiosClient.patch(url);
      if (type === 'request') setPendingRequests(p => p.filter(r => r.id !== id));
      else setPendingOffDays(p => p.filter(r => r.id !== id));
    } catch {
      setActionError(`Failed to reject ${label}. Please try again.`);
    }
  };

  const handleApproveChange = async (id: string) => {
    const ok = await confirm({ title: 'Approve Reassignment', message: 'Approve this truck reassignment request?', confirmLabel: 'Approve', variant: 'default' });
    if (!ok) return;
    try {
      await axiosClient.patch(`/assignment-change-requests/${id}/approve`);
      setPendingChangeRequests(p => p.filter(r => r.id !== id));
    } catch {
      setActionError('Failed to approve reassignment. Please try again.');
    }
  };

  const handleRejectChange = async (id: string) => {
    const ok = await confirm({ title: 'Reject Reassignment', message: 'Reject this reassignment request?', confirmLabel: 'Reject', variant: 'danger' });
    if (!ok) return;
    try {
      await axiosClient.patch(`/assignment-change-requests/${id}/reject`);
      setPendingChangeRequests(p => p.filter(r => r.id !== id));
    } catch {
      setActionError('Failed to reject reassignment. Please try again.');
    }
  };

  const handleApproveRTS = async (driverId: string, driverName: string) => {
    const ok = await confirm({ title: 'Approve RTS Return', message: `Approve ${driverName}'s return-to-station request? They will be cleared to leave the field.`, confirmLabel: 'Approve Return', variant: 'default' });
    if (!ok) return;
    try {
      await axiosClient.patch(`/shift-ops/rts-report/${driverId}`, { status: 'approved' });
      setPendingRTS(p => p.filter(r => r.driver_id !== driverId));
    } catch {
      setActionError(`Failed to approve RTS return for ${driverName}. Please try again.`);
    }
  };

  const handleRejectRTS = async (driverId: string, driverName: string) => {
    const ok = await confirm({ title: 'Reject RTS Return', message: `Reject ${driverName}'s return request? They will remain in the field.`, confirmLabel: 'Reject', variant: 'danger' });
    if (!ok) return;
    try {
      await axiosClient.patch(`/shift-ops/rts-report/${driverId}`, { status: 'rejected' });
      setPendingRTS(p => p.filter(r => r.driver_id !== driverId));
    } catch {
      setActionError(`Failed to reject RTS return for ${driverName}. Please try again.`);
    }
  };

  const quickLinks = [
    { icon: Truck,       label: 'Dispatch Center',   desc: 'Run daily algorithmic dispatch & manual overrides', href: '/dispatch' },
    { icon: AlertTriangle, label: 'Incidents',        desc: 'Review and resolve open field incident reports',    href: '/incidents' },
    { icon: Package,     label: 'Anchor Points',      desc: 'View today\'s AP submissions and confirm locations', href: '/anchor-points' },
  ];

  // Derive fleet counts from assignment statuses
  const activeCount    = fleetAssignments.filter((a: any) => a.status === 'active').length;
  const completedCount = fleetAssignments.filter((a: any) => a.status === 'completed').length;
  const totalCount     = fleetAssignments.length;

  return (
    <div className="space-y-6">
      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
      {loadErrors.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-warning/10 border border-warning/30 text-warning text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Some data failed to load: {loadErrors.join(', ')}. Refresh to retry.</span>
        </div>
      )}
      {actionError && (
        <div className="flex items-center justify-between gap-2 px-4 py-2 rounded-lg bg-danger/10 border border-danger/30 text-danger text-sm">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{actionError}</span>
          </div>
          <button onClick={() => setActionError(null)} className="text-danger/60 hover:text-danger shrink-0"><X className="w-4 h-4" /></button>
        </div>
      )}
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

      {/* Second row: Fleet status + RTS queue */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Fleet Status — from TruckAssignment.status */}
        <div className="card border-border/60">
          <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
            <Truck className="w-5 h-5 text-primary" />
            <h2 className="text-base font-semibold text-foreground">Fleet Status — Today</h2>
            <span className="ml-auto text-xs text-subtle">
              {completedCount} returned · {activeCount} out · {totalCount - activeCount - completedCount} planned
            </span>
          </div>
          {totalCount === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No trucks dispatched today.</p>
          ) : (
            <div className="grid grid-cols-3 gap-3 text-center mb-4">
              {[
                { label: 'Planned',   count: totalCount - activeCount - completedCount, cls: 'text-muted-foreground', bg: 'bg-accent/40' },
                { label: 'Out',       count: activeCount,    cls: 'text-warning',  bg: 'bg-warning/10 border border-warning/20' },
                { label: 'Returned',  count: completedCount, cls: 'text-success',  bg: 'bg-success/10 border border-success/20' },
              ].map(s => (
                <div key={s.label} className={`rounded-xl p-3 ${s.bg}`}>
                  <p className={`text-2xl font-bold ${s.cls}`}>{s.count}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* RTS Pending queue — drivers waiting for clearance to leave the field */}
        <div className="card border-border/60">
          <div className="flex items-center gap-2 border-b border-border/50 pb-3 mb-4">
            <Package className="w-5 h-5 text-warning" />
            <h2 className="text-base font-semibold text-foreground">RTS Return Requests</h2>
            {pendingRTS.length > 0 && (
              <span className="ml-auto badge badge-warning">{pendingRTS.length}</span>
            )}
          </div>
          {pendingRTS.length === 0 ? (
            <div className="text-center py-6 opacity-60">
              <Package className="w-8 h-8 mb-2 text-muted-foreground mx-auto" />
              <p className="text-sm font-medium">No pending RTS requests.</p>
              <p className="text-xs text-subtle mt-1">Drivers waiting for field clearance appear here.</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[240px] overflow-y-auto pr-1">
              {pendingRTS.map(r => (
                <div key={r.report_id} className="p-3 rounded-xl border border-warning/30 bg-warning/5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground">{r.driver_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {r.crew_confirmed} crew confirmed · {r.total_rts} RTS package{r.total_rts !== 1 ? 's' : ''}
                      </p>
                      {r.rts_packages?.length > 0 && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {r.rts_packages.map((p: any) => `${p.reason.replace(/_/g, ' ')} ×${p.count}`).join(', ')}
                        </p>
                      )}
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      <button
                        onClick={() => handleApproveRTS(r.driver_id, r.driver_name)}
                        className="p-1.5 rounded-lg bg-success/10 hover:bg-success/20 text-success transition-colors"
                        title="Clear to return"
                      >
                        <Check className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleRejectRTS(r.driver_id, r.driver_name)}
                        className="p-1.5 rounded-lg bg-danger/10 hover:bg-danger/20 text-danger transition-colors"
                        title="Hold — needs follow-up"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
