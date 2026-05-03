import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import {
  Truck, Users, CheckCircle2, Clock, XCircle, AlertTriangle,
  RefreshCw, ArrowRight, ClipboardCheck, CalendarClock, Package, Check, X,
} from 'lucide-react';
import SectionHeader from '../components/ui/SectionHeader';
import StatCard from '../components/ui/StatCard';
import MotionCard from '../components/ui/MotionCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import type { CrewMember, UnavailableStaff } from '../api/types';
import { getLocalYMD } from '../utils/date';

interface ScheduleChangeRequest {
  id: string;
  employee_id: string;
  employee_name?: string;
  requested_date: string;
  reason?: string;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
}

interface ConfirmationMap {
  [employeeId: string]: 'confirmed' | 'declined' | 'pending';
}

interface DispatchData {
  date: string;
  assigned_crews: Record<string, CrewMember[]>;
  warnings: { type?: string; message?: string }[];
}

export default function DispatchHome() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const today = getLocalYMD();

  const [dispatch, setDispatch] = useState<DispatchData | null>(null);
  const [truckNameMap, setTruckNameMap] = useState<Record<string, string>>({});
  const [confirmations, setConfirmations] = useState<ConfirmationMap>({});
  const [unavailable, setUnavailable] = useState<UnavailableStaff[]>([]);
  const [changeRequests, setChangeRequests] = useState<ScheduleChangeRequest[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [pendingRTS, setPendingRTS] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const greeting = new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening';

  const fetchAll = async () => {
    setLoading(true);
    await Promise.allSettled([
      axiosClient.get(`/dispatch/${today}`)
        .then(r => setDispatch(
          Object.keys(r.data.assigned_crews).length > 0 ? r.data : null
        )),
      axiosClient.get('/trucks')
        .then(r => setTruckNameMap(
          Object.fromEntries((r.data as { id: string; name: string }[]).map(t => [t.id, t.name]))
        ))
        .catch(() => {}),
      axiosClient.get(`/dispatch/${today}/confirmations`)
        .then(r => setConfirmations(r.data.confirmations || {})),
      axiosClient.get(`/dispatch/unavailable-staff/${today}`)
        .then(r => setUnavailable(r.data.unavailable_staff || [])),
      axiosClient.get('/schedule-change-requests/?status=pending&limit=10')
        .then(r => setChangeRequests(r.data))
        .catch(() => {}),
      axiosClient.get('/incidents/?resolved=false&limit=5')
        .then(r => setIncidents(r.data))
        .catch(() => {}),
      axiosClient.get('/shift-ops/rts-reports/pending')
        .then(r => setPendingRTS(r.data))
        .catch(() => {}),
    ]);
    setLoading(false);
  };

  useEffect(() => { fetchAll(); }, []);

  // Derived confirmation stats
  const allAssigned: CrewMember[] = dispatch
    ? Object.values(dispatch.assigned_crews).flat()
    : [];
  const totalAssigned = allAssigned.length;
  const confirmed = Object.values(confirmations).filter(s => s === 'confirmed').length;
  const declined  = Object.values(confirmations).filter(s => s === 'declined').length;
  const pending   = Object.keys(confirmations).length > 0
    ? Object.values(confirmations).filter(s => s === 'pending').length
    : totalAssigned - confirmed - declined;

  const isPublished = Object.keys(confirmations).length > 0;

  if (loading) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="Dispatch" title="Dashboard" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} className="h-48" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="Dispatch"
        title={`Good ${greeting}, ${user?.displayName || user?.username}`}
        description={`Operations overview for ${new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
        actions={
          <button onClick={fetchAll} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard
          label="Assigned Today"
          value={totalAssigned}
          icon={Users}
          tone="primary"
          delay={0}
          hint={dispatch ? undefined : 'Not run yet'}
        />
        <StatCard
          label="Confirmed"
          value={confirmed}
          icon={CheckCircle2}
          tone={confirmed === totalAssigned && totalAssigned > 0 ? 'success' : 'teal'}
          delay={0.07}
          hint={!isPublished ? 'Not published' : undefined}
        />
        <StatCard
          label="Pending"
          value={pending}
          icon={Clock}
          tone={pending > 0 ? 'warning' : 'success'}
          delay={0.14}
        />
        <StatCard
          label="Open Incidents"
          value={incidents.length}
          icon={AlertTriangle}
          tone={incidents.length > 0 ? 'danger' : 'success'}
          delay={0.21}
          hint={incidents.length === 0 ? 'All clear' : undefined}
        />
        <StatCard
          label="RTS Pending"
          value={pendingRTS.length}
          icon={Package}
          tone={pendingRTS.length > 0 ? 'warning' : 'success'}
          delay={0.28}
          hint={pendingRTS.length === 0 ? 'No drivers waiting' : undefined}
        />
      </div>

      {/* Main content row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Today's dispatch status */}
        <MotionCard delay={0.1}>
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <Truck className="w-5 h-5 text-primary" />
            <h2 className="text-base font-semibold text-foreground">Today's Dispatch</h2>
            <span className={`ml-auto badge ${isPublished ? 'badge-success' : dispatch ? 'badge-warning' : 'bg-accent text-muted-foreground'}`}>
              {isPublished ? 'Published' : dispatch ? 'Draft' : 'Not run'}
            </span>
          </div>

          {!dispatch ? (
            <div className="text-center py-8 opacity-60">
              <Truck className="w-10 h-10 mb-3 text-muted-foreground mx-auto" />
              <p className="text-sm font-medium">No dispatch for today yet.</p>
              <p className="text-xs text-muted-foreground mt-1">Head to Assignments to run it.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[260px] overflow-y-auto pr-1">
              {Object.entries(dispatch.assigned_crews).map(([truckId, crew]) => {
                const driver = crew.find(m => m.role === 'driver');
                const others = crew.filter(m => m.role !== 'driver');
                return (
                  <div key={truckId} className="p-3 rounded-xl border border-border bg-surface-muted/50">
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-1.5">
                      {truckNameMap[truckId] ?? 'Truck'} · {crew.length} members
                    </p>
                    {driver && (
                      <p className="text-sm font-medium text-foreground">{driver.name}
                        <span className="ml-1.5 text-xs text-muted-foreground font-normal">driver</span>
                      </p>
                    )}
                    {others.length > 0 && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {others.map(m => m.name).join(', ')}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {dispatch?.warnings && dispatch.warnings.length > 0 && (
            <div className="mt-3 p-2.5 rounded-lg bg-warning/10 border border-warning/30">
              <p className="text-xs font-semibold text-warning mb-1">
                {dispatch.warnings.length} warning{dispatch.warnings.length > 1 ? 's' : ''}
              </p>
              {dispatch.warnings.slice(0, 2).map((w, i) => (
                <p key={i} className="text-xs text-warning/80">{w.message}</p>
              ))}
            </div>
          )}
        </MotionCard>

        {/* Confirmation status */}
        <MotionCard delay={0.17}>
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <CheckCircle2 className="w-5 h-5 text-success" />
            <h2 className="text-base font-semibold text-foreground">Confirmations</h2>
          </div>

          {!isPublished ? (
            <div className="text-center py-8 opacity-60">
              <Clock className="w-10 h-10 mb-3 text-muted-foreground mx-auto" />
              <p className="text-sm font-medium">Not published yet.</p>
              <p className="text-xs text-muted-foreground mt-1">Confirmations appear after publishing to Discord.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Summary bars */}
              <div className="space-y-2">
                {[
                  { label: 'Confirmed', count: confirmed, total: totalAssigned, cls: 'bg-success' },
                  { label: 'Pending',   count: pending,   total: totalAssigned, cls: 'bg-warning' },
                  { label: 'Declined',  count: declined,  total: totalAssigned, cls: 'bg-danger' },
                ].map(({ label, count, total, cls }) => (
                  <div key={label}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="font-semibold text-foreground">{count} / {total}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-accent overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${cls}`}
                        style={{ width: total > 0 ? `${(count / total) * 100}%` : '0%' }}
                      />
                    </div>
                  </div>
                ))}
              </div>

              {/* Declined list */}
              {declined > 0 && (
                <div className="mt-3 pt-3 border-t border-border">
                  <p className="text-xs font-semibold text-danger mb-2">Declined</p>
                  <div className="space-y-1">
                    {allAssigned
                      .filter(m => confirmations[m.employee_id] === 'declined')
                      .map(m => (
                        <div key={m.employee_id} className="flex items-center gap-2">
                          <XCircle className="w-3.5 h-3.5 text-danger shrink-0" />
                          <p className="text-sm text-foreground">{m.name}
                            <span className="ml-1 text-xs text-muted-foreground capitalize">{m.role}</span>
                          </p>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </MotionCard>

        {/* Staff off today */}
        <MotionCard delay={0.24}>
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <CalendarClock className="w-5 h-5 text-warning" />
            <h2 className="text-base font-semibold text-foreground">Staff Off Today</h2>
            {unavailable.length > 0 && (
              <span className="ml-auto badge badge-warning">{unavailable.length}</span>
            )}
          </div>

          {unavailable.length === 0 ? (
            <div className="text-center py-8 opacity-60">
              <CheckCircle2 className="w-10 h-10 mb-3 text-success mx-auto" />
              <p className="text-sm font-medium">Full availability today.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
              {unavailable.map(s => (
                <div key={s.id} className="flex items-center justify-between p-2.5 rounded-xl border border-border bg-surface-muted/50">
                  <div>
                    <p className="text-sm font-medium text-foreground">{s.name}</p>
                    <p className="text-xs text-muted-foreground capitalize">{s.role}</p>
                  </div>
                  <span className="badge bg-accent text-muted-foreground text-[10px]">
                    {s.reason === 'time_off_request' ? 'Time off' : 'Day off'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </MotionCard>
      </div>

      {/* Schedule change requests */}
      <MotionCard delay={0.3} hoverable={false}>
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <ClipboardCheck className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Pending Schedule Changes</h2>
          {changeRequests.length > 0 && (
            <span className="ml-auto badge badge-info">{changeRequests.length}</span>
          )}
        </div>

        {changeRequests.length === 0 ? (
          <div className="text-center py-6 opacity-60">
            <CheckCircle2 className="w-8 h-8 mb-2 text-success mx-auto" />
            <p className="text-sm font-medium">No pending change requests.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {changeRequests.map(req => (
              <div key={req.id} className="flex items-center justify-between p-3 rounded-xl border border-border bg-surface-muted/50">
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {req.employee_name || req.employee_id}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Requested: {req.requested_date}
                    {req.reason && ` · ${req.reason}`}
                  </p>
                </div>
                <span className="badge badge-warning capitalize">{req.status}</span>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={() => navigate('/schedule-changes')}
          className="mt-4 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          Review all requests <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </MotionCard>

      {/* RTS Return Requests */}
      <MotionCard delay={0.36} hoverable={false}>
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <Package className="w-5 h-5 text-warning" />
          <h2 className="text-base font-semibold text-foreground">RTS Return Requests</h2>
          {pendingRTS.length > 0 && (
            <span className="ml-auto badge badge-warning">{pendingRTS.length}</span>
          )}
        </div>

        <p className="text-xs text-muted-foreground mb-3">
          Drivers waiting for field clearance to head back to the station with RTS packages.
          Approve to release them, or reject if their counts need follow-up.
        </p>

        {pendingRTS.length === 0 ? (
          <div className="text-center py-6 opacity-60">
            <CheckCircle2 className="w-8 h-8 mb-2 text-success mx-auto" />
            <p className="text-sm font-medium">No drivers waiting for RTS clearance.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {pendingRTS.map(r => (
              <div key={r.report_id} className="flex items-start justify-between gap-3 p-3 rounded-xl border border-warning/30 bg-warning/5">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">{r.driver_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {r.crew_confirmed} crew confirmed · {r.total_rts} RTS package{r.total_rts !== 1 ? 's' : ''}
                  </p>
                  {r.rts_packages?.length > 0 && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {r.rts_packages.map((p: any) =>
                        `${p.reason.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())} ×${p.count}`
                      ).join(' · ')}
                    </p>
                  )}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => {
                      axiosClient.patch(`/shift-ops/rts-report/${r.driver_id}`, { status: 'approved' })
                        .then(() => setPendingRTS(prev => prev.filter(x => x.driver_id !== r.driver_id)))
                        .catch(() => {});
                    }}
                    className="p-1.5 rounded-lg bg-success/10 hover:bg-success/20 text-success transition-colors"
                    title="Clear to return"
                  >
                    <Check className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => {
                      axiosClient.patch(`/shift-ops/rts-report/${r.driver_id}`, { status: 'rejected' })
                        .then(() => setPendingRTS(prev => prev.filter(x => x.driver_id !== r.driver_id)))
                        .catch(() => {});
                    }}
                    className="p-1.5 rounded-lg bg-danger/10 hover:bg-danger/20 text-danger transition-colors"
                    title="Hold — needs follow-up"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </MotionCard>
    </div>
  );
}
