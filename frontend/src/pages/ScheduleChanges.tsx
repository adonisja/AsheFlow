import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { RefreshCw, X, Plus, Minus, RotateCcw, BarChart2, CheckCircle2, XCircle, Clock } from 'lucide-react';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useConfirm } from '../hooks/useConfirm';

const DAYS_OF_WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

type RequestType = 'add_day' | 'drop_day' | 'full_rework';

const statusBadge = (status: string) => {
  if (status === 'pending') return 'badge-warning';
  if (status === 'approved') return 'badge-success';
  if (status === 'rejected') return 'badge-danger';
  return 'badge bg-accent text-muted-foreground';
};

const typeLabel: Record<RequestType, string> = {
  add_day: 'Add Working Days',
  drop_day: 'Drop Working Days',
  full_rework: 'Full Schedule Rework',
};

const typeDescription: Record<RequestType, string> = {
  add_day: 'Re-enable days you currently have off so you can be dispatched on them again.',
  drop_day: 'Remove days from your working week so you are no longer dispatched on them.',
  full_rework: 'Replace your entire recurring schedule. Choose every day you want to work.',
};

// ---------------------------------------------------------------------------
// Analytics panel — admin only
// ---------------------------------------------------------------------------

function ScheduleAnalytics({ allRequests }: { allRequests: any[] }) {
  const total = allRequests.length;
  const pending  = allRequests.filter(r => r.status === 'pending').length;
  const approved = allRequests.filter(r => r.status === 'approved').length;
  const rejected = allRequests.filter(r => r.status === 'rejected').length;
  const approvalRate = (approved + rejected) > 0
    ? Math.round((approved / (approved + rejected)) * 100)
    : null;

  const byType = (['add_day', 'drop_day', 'full_rework'] as RequestType[]).map(t => ({
    type: t,
    count: allRequests.filter(r => r.request_type === t).length,
  }));

  // Most requested days to drop (across all drop_day and full_rework requests)
  const dayCounts: Record<string, number> = {};
  allRequests.forEach(r => {
    const days = r.request_type === 'drop_day'
      ? (r.days_to_drop ?? [])
      : r.request_type === 'full_rework'
        ? DAYS_OF_WEEK.filter(d => !(r.proposed_schedule ?? []).includes(d))
        : [];
    days.forEach((d: string) => { dayCounts[d] = (dayCounts[d] ?? 0) + 1; });
  });
  const topOffDays = DAYS_OF_WEEK
    .filter(d => dayCounts[d])
    .sort((a, b) => (dayCounts[b] ?? 0) - (dayCounts[a] ?? 0))
    .slice(0, 3);

  const stats = [
    { label: 'Total Requests', value: total, icon: BarChart2, color: 'text-primary' },
    { label: 'Pending',        value: pending,  icon: Clock,         color: 'text-warning' },
    { label: 'Approved',       value: approved, icon: CheckCircle2,  color: 'text-success' },
    { label: 'Rejected',       value: rejected, icon: XCircle,       color: 'text-danger'  },
  ];

  return (
    <div className="space-y-4">
      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {stats.map(s => (
          <div key={s.label} className="card-elevated flex items-center gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-primary/5 shrink-0">
              <s.icon className={`w-4 h-4 ${s.color}`} />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{s.label}</p>
              <p className="text-lg font-bold text-foreground">{s.value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Approval rate */}
        <div className="card space-y-3">
          <h3 className="text-sm font-semibold text-foreground">Approval Rate</h3>
          {approvalRate !== null ? (
            <>
              <div className="w-full bg-accent rounded-full h-2">
                <div
                  className="bg-success h-2 rounded-full transition-all"
                  style={{ width: `${approvalRate}%` }}
                />
              </div>
              <p className="text-xs text-subtle">{approvalRate}% of reviewed requests approved</p>
            </>
          ) : (
            <p className="text-xs text-subtle italic">No reviewed requests yet.</p>
          )}
        </div>

        {/* Requests by type */}
        <div className="card space-y-2">
          <h3 className="text-sm font-semibold text-foreground">By Request Type</h3>
          {byType.map(({ type, count }) => (
            <div key={type} className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{typeLabel[type]}</span>
              <span className="font-semibold text-foreground">{count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Most-requested days off */}
      {topOffDays.length > 0 && (
        <div className="card space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Most Requested Days Off</h3>
          <div className="flex flex-wrap gap-2">
            {topOffDays.map(d => (
              <span key={d} className="px-3 py-1 rounded-full text-xs font-medium bg-warning/10 text-warning border border-warning/20">
                {d} ({dayCounts[d]})
              </span>
            ))}
          </div>
          <p className="text-xs text-subtle">Days most commonly appearing in drop/rework requests.</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const ScheduleChanges = () => {
  const { user, groups } = useAuth();
  const isAdmin = groups.includes('admin');
  const isPrivileged = isAdmin || groups.includes('management') || groups.includes('dispatch');
  const { confirmState, confirm, cancelConfirm } = useConfirm();

  const [myId, setMyId] = useState<string>('');
  const [offDays, setOffDays] = useState<string[]>([]);
  const [requests, setRequests] = useState<any[]>([]);
  const [pendingRequests, setPendingRequests] = useState<any[]>([]);
  const [allRequests, setAllRequests] = useState<any[]>([]);

  // Form state
  const [mode, setMode] = useState<RequestType>('drop_day');
  const [selectedDays, setSelectedDays] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isPrivileged) {
      axiosClient.get('/employees/me').then(res => setMyId(res.data.id)).catch(() => {});
    }
  }, [isPrivileged]);

  useEffect(() => {
    if (isPrivileged) {
      loadPendingRequests();
      loadAllRequests();
    }
    if (!isPrivileged && myId) {
      loadOffDays();
      loadMyRequests();
    }
  }, [myId, isPrivileged]);

  const loadOffDays = async () => {
    try {
      const res = await axiosClient.get(`/employee-off-days/${myId}`);
      setOffDays(res.data.map((o: any) => o.day_of_week));
    } catch (err) { console.error(err); }
  };

  const loadMyRequests = async () => {
    try {
      const res = await axiosClient.get(`/schedule-change-requests/employee/${myId}`);
      setRequests(res.data);
    } catch (err) { console.error(err); }
  };

  const loadPendingRequests = async () => {
    try {
      const res = await axiosClient.get('/schedule-change-requests/', { params: { status: 'pending' } });
      setPendingRequests(res.data);
    } catch (err) { console.error(err); }
  };

  const loadAllRequests = async () => {
    try {
      const res = await axiosClient.get('/schedule-change-requests/');
      setAllRequests(res.data);
    } catch (err) { console.error(err); }
  };

  const workingDays = DAYS_OF_WEEK.filter(d => !offDays.includes(d));

  const selectableDays = () => {
    if (mode === 'add_day') return offDays;
    if (mode === 'drop_day') return workingDays;
    return DAYS_OF_WEEK;
  };

  const toggleDay = (day: string) => {
    setSelectedDays(prev =>
      prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day]
    );
  };

  const handleModeChange = (m: RequestType) => {
    setMode(m);
    setSelectedDays([]);
    setError('');
  };

  const hasPending = requests.some(r => r.status === 'pending');

  const handleSubmit = async () => {
    if (selectedDays.length === 0) { setError('Select at least one day.'); return; }
    if (hasPending) { setError('You already have a pending request. Cancel it before submitting a new one.'); return; }
    setError('');
    setSubmitting(true);
    try {
      const payload: any = {
        employee_id: myId,
        request_type: mode,
        reason: reason || undefined,
        days_to_add: mode === 'add_day' ? selectedDays : [],
        days_to_drop: mode === 'drop_day' ? selectedDays : [],
        proposed_schedule: mode === 'full_rework' ? selectedDays : undefined,
      };
      await axiosClient.post('/schedule-change-requests/', payload);
      setSelectedDays([]);
      setReason('');
      loadMyRequests();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to submit request.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (id: string) => {
    const ok = await confirm({
      title: 'Cancel Schedule Change Request',
      message: 'Are you sure you want to cancel this request?',
      confirmLabel: 'Yes, Cancel It',
      variant: 'warning',
    });
    if (!ok) return;
    try {
      await axiosClient.delete(`/schedule-change-requests/${id}`);
      loadMyRequests();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to cancel.');
    }
  };

  const handleReview = async (id: string, action: 'approve' | 'reject') => {
    const ok = await confirm({
      title: action === 'approve' ? 'Approve Schedule Change' : 'Reject Schedule Change',
      message: action === 'approve'
        ? 'Approve this permanent schedule change request?'
        : 'Reject this request? The employee will be notified.',
      confirmLabel: action === 'approve' ? 'Approve' : 'Reject',
      variant: action === 'approve' ? 'default' : 'danger',
    });
    if (!ok) return;
    try {
      await axiosClient.patch(`/schedule-change-requests/${id}/${action}`);
      loadPendingRequests();
      if (isPrivileged) loadAllRequests();
    } catch (err: any) {
      alert(err.response?.data?.detail || `Failed to ${action}.`);
    }
  };

  const modeIcon: Record<RequestType, React.ReactNode> = {
    add_day:     <Plus className="w-4 h-4" />,
    drop_day:    <Minus className="w-4 h-4" />,
    full_rework: <RotateCcw className="w-4 h-4" />,
  };

  // ---------------------------------------------------------------------------
  // Privileged view (admin / management / dispatch) — analytics + pending queue
  // ---------------------------------------------------------------------------
  if (isPrivileged) {
    return (
      <div className="max-w-3xl mx-auto space-y-6 animate-slide-up">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-accent">
            <BarChart2 className="w-5 h-5 text-muted-foreground" />
          </div>
          <div>
            <h1 className="page-title">Schedule Changes</h1>
            <p className="text-subtle text-sm">Review pending requests and monitor schedule change trends.</p>
          </div>
        </div>

        <ScheduleAnalytics allRequests={allRequests} />

        <div className="card">
          <h2 className="section-title mb-4">Pending Requests</h2>
          {pendingRequests.length === 0 ? (
            <p className="text-subtle text-sm text-center py-4">No pending schedule change requests.</p>
          ) : (
            <ul className="space-y-4">
              {pendingRequests.map((req: any) => (
                <li key={req.id} className="p-4 rounded-xl bg-accent/40 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-foreground">{req.employee?.name}</p>
                      <p className="text-xs text-subtle capitalize">{req.employee?.role} · {typeLabel[req.request_type as RequestType]}</p>
                    </div>
                    <span className={statusBadge(req.status)}>{req.status}</span>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs text-subtle">
                    {req.days_to_add?.length > 0 && <span>Add: {req.days_to_add.join(', ')}</span>}
                    {req.days_to_drop?.length > 0 && <span>Drop: {req.days_to_drop.join(', ')}</span>}
                    {req.proposed_schedule?.length > 0 && <span>New schedule: {req.proposed_schedule.join(', ')}</span>}
                  </div>
                  {req.reason && <p className="text-xs text-subtle italic">"{req.reason}"</p>}
                  <div className="flex gap-2">
                    <button onClick={() => handleReview(req.id, 'approve')} className="btn-primary text-xs">Approve</button>
                    <button onClick={() => handleReview(req.id, 'reject')} className="btn-ghost text-xs text-danger hover:bg-danger/10">Reject</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Field staff view — personal form + own request history
  // ---------------------------------------------------------------------------
  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-slide-up">
      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-accent">
          <RefreshCw className="w-5 h-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="page-title">Schedule Changes</h1>
          <p className="text-subtle text-sm">Request a permanent change to your weekly working schedule.</p>
        </div>
      </div>

      {/* Current schedule summary */}
      <div className="card">
        <h2 className="section-title mb-3">Your Current Schedule</h2>
        <div className="flex flex-wrap gap-2">
          {DAYS_OF_WEEK.map(day => (
            <span
              key={day}
              className={`px-3 py-1 rounded-full text-xs font-medium ${
                offDays.includes(day)
                  ? 'bg-accent text-muted-foreground line-through'
                  : 'bg-primary/10 text-primary'
              }`}
            >
              {day}
            </span>
          ))}
        </div>
        <p className="text-xs text-subtle mt-2">Strikethrough = current off day</p>
      </div>

      {/* Submit form */}
      <div className="card space-y-5">
        <h2 className="section-title">New Request</h2>

        {hasPending && (
          <div className="p-3 rounded-xl bg-warning/10 border border-warning/20 text-sm text-warning">
            You have a pending request. Cancel it below before submitting a new one.
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Request Type</label>
          <div className="flex flex-col sm:flex-row gap-2">
            {(['add_day', 'drop_day', 'full_rework'] as RequestType[]).map(m => (
              <button
                key={m}
                onClick={() => handleModeChange(m)}
                className={`flex items-center gap-2 flex-1 px-4 py-3 rounded-xl text-sm font-medium border transition-colors ${
                  mode === m
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
                }`}
              >
                {modeIcon[m]}
                {typeLabel[m]}
              </button>
            ))}
          </div>
          <p className="text-xs text-subtle mt-2">{typeDescription[mode]}</p>
        </div>

        <div>
          <label className="block text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
            {mode === 'full_rework' ? 'Select your new working days' : `Select days to ${mode === 'add_day' ? 'add back' : 'drop'}`}
          </label>
          {selectableDays().length === 0 ? (
            <p className="text-sm text-subtle italic">
              {mode === 'add_day' ? 'No days are currently off — nothing to add back.' : 'All days are already off.'}
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {selectableDays().map(day => (
                <button
                  key={day}
                  onClick={() => toggleDay(day)}
                  className={`px-4 py-2 rounded-xl text-sm font-medium border transition-colors ${
                    selectedDays.includes(day)
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
                  }`}
                >
                  {day}
                </button>
              ))}
            </div>
          )}
        </div>

        <div>
          <label className="block text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Reason (optional)</label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Explain your request..."
            className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>

        {error && <p className="text-xs text-danger">{error}</p>}

        <button
          onClick={handleSubmit}
          disabled={submitting || hasPending || selectedDays.length === 0}
          className="btn-primary disabled:opacity-50"
        >
          {submitting ? 'Submitting...' : 'Submit Request'}
        </button>
      </div>

      {/* My request history */}
      <div className="card">
        <h2 className="section-title mb-4">My Requests</h2>
        {requests.length === 0 ? (
          <p className="text-subtle text-sm text-center py-4">No schedule change requests yet.</p>
        ) : (
          <ul className="space-y-3">
            {requests.map(req => (
              <li key={req.id} className="p-4 rounded-xl bg-accent/40 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{typeLabel[req.request_type as RequestType]}</span>
                    <span className={statusBadge(req.status)}>{req.status}</span>
                  </div>
                  {req.status === 'pending' && (
                    <button
                      onClick={() => handleCancel(req.id)}
                      className="btn-ghost text-muted-foreground p-1.5 hover:text-danger"
                      title="Cancel request"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  {req.days_to_add?.length > 0 && <span className="text-subtle">Add: {req.days_to_add.join(', ')}</span>}
                  {req.days_to_drop?.length > 0 && <span className="text-subtle">Drop: {req.days_to_drop.join(', ')}</span>}
                  {req.proposed_schedule?.length > 0 && <span className="text-subtle">New schedule: {req.proposed_schedule.join(', ')}</span>}
                </div>
                {req.reason && <p className="text-xs text-subtle">"{req.reason}"</p>}
                <p className="text-xs text-subtle">{new Date(req.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

export default ScheduleChanges;
