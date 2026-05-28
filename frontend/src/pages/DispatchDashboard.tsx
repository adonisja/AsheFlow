import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { Calendar, Truck, Users, AlertCircle, Play, GripVertical, Plus, Trash2, Phone, ChevronDown, ChevronUp, RefreshCw, Send, CheckCircle2, XCircle, Clock } from 'lucide-react';
import type { UnavailableStaff, DispatchResult } from '../api/types';
import ConfirmDialog from '../components/ui/ConfirmDialog';

export default function DispatchDashboard() {
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin') || groups.includes('Admin');
  const [selectedDate, setSelectedDate] = useState<string>(
    new Date().toISOString().split('T')[0]
  );
  const [totalEmployees, setTotalEmployees] = useState<number | ''>('');
  const [totalTrucks, setTotalTrucks] = useState<number | ''>('');
  const [dispatchData, setDispatchData] = useState<DispatchResult | null>(null);
  const [trucks, setTrucks] = useState<Record<string, any>>({});
  const [employees, setEmployees] = useState<Record<string, any>>({});
  // Pool of employees actually available for the selected date (excludes off-days, wrong roles)
  const [availablePool, setAvailablePool] = useState<Record<string, any>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unavailableStaff, setUnavailableStaff] = useState<UnavailableStaff[]>([]);
  const [showCallInList, setShowCallInList] = useState(false);
  const [addingStaffId, setAddingStaffId] = useState<string | null>(null);
  // confirmations: { [employee_id]: "pending" | "confirmed" | "declined" }
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});
  const [isPublished, setIsPublished] = useState(false);
  const [isPollingConfirmations, setIsPollingConfirmations] = useState(false);
  const [confirmationsStale, setConfirmationsStale] = useState(false);
  const confirmationPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollFailureCount = useRef(0);

  type DialogConfig = { title: string; message: string; confirmLabel: string; variant: 'danger' | 'warning' | 'default'; onConfirm: () => void };
  const [dialog, setDialog] = useState<DialogConfig | null>(null);
  const openDialog = (cfg: DialogConfig) => setDialog(cfg);
  const closeDialog = () => setDialog(null);

  const stopConfirmationPolling = () => {
    if (confirmationPollRef.current !== null) {
      clearInterval(confirmationPollRef.current);
      confirmationPollRef.current = null;
    }
    pollFailureCount.current = 0;
    setIsPollingConfirmations(false);
  };

  // Start polling every 15s — stops automatically when all responses are in
  const startConfirmationPolling = useCallback((date: string) => {
    stopConfirmationPolling();
    setIsPollingConfirmations(true);
    setConfirmationsStale(false);
    confirmationPollRef.current = setInterval(async () => {
      try {
        const res = await axiosClient.get(`/dispatch/${date}/confirmations`);
        const data: Record<string, string> = res.data.confirmations || {};
        pollFailureCount.current = 0;
        setConfirmationsStale(false);
        setConfirmations(data);
        const values = Object.values(data);
        if (values.length > 0 && values.every(s => s !== 'pending')) {
          stopConfirmationPolling();
        }
      } catch {
        pollFailureCount.current += 1;
        if (pollFailureCount.current >= 3) {
          setConfirmationsStale(true);
        }
      }
    }, 15000);
  }, []);

  useEffect(() => {
    fetchTrucksAndEmployees();
    return () => stopConfirmationPolling();
  }, []);

  useEffect(() => {
    stopConfirmationPolling();
    setConfirmationsStale(false);
    fetchDispatchData();
    fetchAvailablePool();
    fetchUnavailableStaff();
    fetchConfirmations();
  }, [selectedDate]);

  const fetchConfirmations = async () => {
    try {
      const res = await axiosClient.get(`/dispatch/${selectedDate}/confirmations`);
      const data = res.data.confirmations || {};
      setConfirmations(data);
      setIsPublished(Object.keys(data).length > 0);
    } catch {
      // No confirmations yet — not an error worth surfacing
    }
  };

  const handlePublishToDiscord = () => {
    if (!dispatchData) return;
    openDialog({
      title: 'Publish to Discord',
      message: `Send DMs to all assigned employees for ${selectedDate}? This opens the confirmation window.`,
      confirmLabel: 'Publish',
      variant: 'default',
      onConfirm: async () => {
        closeDialog();
        setIsPublishing(true);
        setError(null);
        try {
          await axiosClient.post(`/dispatch/${selectedDate}/publish`);
          setIsPublished(true);
          await fetchConfirmations();
          startConfirmationPolling(selectedDate);
        } catch (err: any) {
          setError(err.response?.data?.detail || 'Failed to publish to Discord.');
        } finally {
          setIsPublishing(false);
        }
      },
    });
  };

  const handleFinalize = () => {
    if (!dispatchData) return;
    openDialog({
      title: 'Post Final Crews',
      message: `Post confirmed crews to each truck channel and the master list to #drivers-chat for ${selectedDate}?`,
      confirmLabel: 'Post Final Crews',
      variant: 'default',
      onConfirm: async () => {
        closeDialog();
        setIsFinalizing(true);
        setError(null);
        stopConfirmationPolling();
        try {
          await axiosClient.post(`/dispatch/${selectedDate}/finalize`);
        } catch (err: any) {
          setError(err.response?.data?.detail || 'Failed to post final assignments to Discord.');
        } finally {
          setIsFinalizing(false);
        }
      },
    });
  };

  const fetchUnavailableStaff = async () => {
    try {
      const res = await axiosClient.get(`/dispatch/unavailable-staff/${selectedDate}`);
      setUnavailableStaff(res.data.unavailable_staff || []);
    } catch (e) {
      console.error(e);
    }
  };

  const handleAddUnavailableStaff = async (member: UnavailableStaff) => {
    if (!dispatchData) return;
    // For drivers: find first truck with no driver. For others: find first truck at all.
    let targetTruckId: string | undefined;
    if (member.role === 'driver') {
      const entry = Object.entries(dispatchData.assigned_crews).find(
        ([, crew]) => !crew.some((m: any) => m.role === 'driver')
      );
      if (!entry) {
        setError('All trucks already have a driver. Use the unassigned panel to place manually.');
        return;
      }
      targetTruckId = entry[0];
    } else {
      // For trainers/walkers: place on the first available truck
      targetTruckId = Object.keys(dispatchData.assigned_crews)[0];
    }
    if (!targetTruckId) return;
    setAddingStaffId(member.id);
    try {
      await axiosClient.post('/dispatch/assign', {
        employee_id: member.id,
        truck_id: targetTruckId,
        date: selectedDate,
        role: member.role,
      });
      await fetchDispatchData();
      setUnavailableStaff(prev => prev.filter(s => s.id !== member.id));
    } catch (err: any) {
      setError(err.response?.data?.detail || `Failed to add ${member.name} to dispatch.`);
    } finally {
      setAddingStaffId(null);
    }
  };

  const fetchAvailablePool = async () => {
    try {
      const res = await axiosClient.get(`/schedule/available/${selectedDate}`);
      // /schedule/available returns { driver, trainer, walker } — merge all into a flat id→emp map
      const pool: Record<string, any> = {};
      const allRes = await axiosClient.get('/employees/');
      const allEmpMap: Record<string, any> = allRes.data.reduce((acc: any, e: any) => ({ ...acc, [e.id]: e }), {});

      // Include all dispatch-eligible roles from the availability-filtered response
      ['driver', 'trainer', 'walker', 'trainee'].forEach(role => {
        (res.data[role] || []).forEach((e: any) => { pool[e.id] = allEmpMap[e.id] || e; });
      });

      setAvailablePool(pool);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchTrucksAndEmployees = async () => {
    try {
      const [trucksRes, empRes] = await Promise.all([
        axiosClient.get('/trucks/'),
        axiosClient.get('/employees/')
      ]);
      const truckMap = trucksRes.data.reduce((acc: any, t: any) => ({ ...acc, [t.id]: t }), {});
      const empMap = empRes.data.reduce((acc: any, e: any) => ({ ...acc, [e.id]: e }), {});
      setTrucks(truckMap);
      setEmployees(empMap);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchDispatchData = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await axiosClient.get(`/dispatch/${selectedDate}`);
      
      if (Object.keys(response.data.assigned_crews).length === 0) {
        setDispatchData(null);
      } else {
        setDispatchData(response.data);
      }
    } catch (err: any) {
      console.error(err);
      setError('Failed to fetch existing dispatch records.');
      setDispatchData(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRunDispatch = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const payload: any = { date: selectedDate };
      if (totalEmployees) payload.total_employees = totalEmployees;
      if (totalTrucks) payload.total_trucks = totalTrucks;
      
      const response = await axiosClient.post('/dispatch/', payload);
      setDispatchData({
        ...response.data,
        assigned_crews: response.data.assigned_crews || {}
      });
      await fetchAvailablePool();
    } catch (err: any) {
      if (err.response && err.response.data && err.response.data.detail) {
        setError(err.response.data.detail);
      } else {
        setError('An unexpected error occurred running dispatch.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleDragStart = (e: React.DragEvent, employeeId: string, sourceTruckId?: string) => {
    e.dataTransfer.setData('employeeId', employeeId);
    if (sourceTruckId) {
      e.dataTransfer.setData('sourceTruckId', sourceTruckId);
    }
  };

  const handleDropToTruck = async (e: React.DragEvent, targetTruckId: string) => {
    e.preventDefault();
    const employeeId = e.dataTransfer.getData('employeeId');
    const sourceTruckId = e.dataTransfer.getData('sourceTruckId');
    
    if (sourceTruckId === targetTruckId) return; // Same truck
    
    setIsLoading(true);
    try {
      if (sourceTruckId) {
        // SWAP: from truck to truck
        await axiosClient.patch('/dispatch/assign', {
          employee_id: employeeId,
          date: selectedDate,
          new_truck_id: targetTruckId
        });
      } else {
        // ASSIGN: from unassigned to truck — use the employee's actual role
        const emp = availablePool[employeeId] || employees[employeeId];
        const role = emp?.role || 'walker';
        await axiosClient.post('/dispatch/assign', {
          employee_id: employeeId,
          truck_id: targetTruckId,
          date: selectedDate,
          role,
        });
      }
      await fetchDispatchData(); // Refresh on drop
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to move employee.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveFromTruck = (employeeId: string) => {
    const empName = employees[employeeId]?.name || 'this employee';
    openDialog({
      title: 'Remove from Assignment',
      message: `Remove ${empName} from today's truck assignment?`,
      confirmLabel: 'Remove',
      variant: 'danger',
      onConfirm: async () => {
        closeDialog();
        setIsLoading(true);
        try {
          await axiosClient.delete(`/dispatch/assign/${selectedDate}/${employeeId}`);
          await fetchDispatchData();
        } catch (err: any) {
          console.error(err);
          setError(err.response?.data?.detail || 'Failed to remove employee.');
        } finally {
          setIsLoading(false);
        }
      },
    });
  };

  const handleClearDispatch = () => {
    openDialog({
      title: 'Clear Dispatch',
      message: `Permanently delete the entire dispatch assignment for ${selectedDate}? This cannot be undone.`,
      confirmLabel: 'Clear Dispatch',
      variant: 'danger',
      onConfirm: async () => {
        closeDialog();
        setIsLoading(true);
        setError(null);
        try {
          await axiosClient.delete(`/dispatch/${selectedDate}`);
          setDispatchData(null);
          await fetchDispatchData();
        } catch (err: any) {
          setError(err.response?.data?.detail || 'Failed to clear dispatch.');
        } finally {
          setIsLoading(false);
        }
      },
    });
  };

  const sortCrewMembers = (a: any, b: any) => {
    // Get true core role from employees map if available
    const roleA = (employees[a.employee_id || a.id]?.role || a.role || 'walker').toLowerCase();
    const roleB = (employees[b.employee_id || b.id]?.role || b.role || 'walker').toLowerCase();
    
    const roleOrder: Record<string, number> = { driver: 1, trainer: 2, trainee: 3, walker: 4 };
    const orderA = roleOrder[roleA] || 5;
    const orderB = roleOrder[roleB] || 5;
    
    if (orderA !== orderB) return orderA - orderB;
    
    const nameA = (employees[a.employee_id || a.id]?.name || a.name || '').toLowerCase();
    const nameB = (employees[b.employee_id || b.id]?.name || b.name || '').toLowerCase();
    return nameA.localeCompare(nameB);
  };

  // Compute unassigned employees — only from the available pool for the selected date,
  // excluding anyone already placed in a truck assignment.
  const getUnassignedEmployees = () => {
    const assignedIds = new Set<string>();
    if (dispatchData) {
      Object.values(dispatchData.assigned_crews).forEach(crew => {
        crew.forEach((m: any) => assignedIds.add(m.employee_id));
      });
    }
    return Object.values(availablePool)
      .filter((emp: any) => !assignedIds.has(emp.id))
      .sort(sortCrewMembers);
  };

  const unassigned = getUnassignedEmployees();
  const maxCrewSize = dispatchData?.assigned_crews
    ? Object.values(dispatchData.assigned_crews).reduce((max: number, crew: any) => Math.max(max, crew.length), 0) || 3
    : 3;

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex flex-col gap-4">
        {/* Row 1 — title + refresh */}
        <div className="flex items-center gap-3">
          <div>
            <h1 className="page-title">Dispatch Center</h1>
            <p className="text-subtle mt-1">Manage and assign daily routes</p>
          </div>
          <button
            onClick={() => { fetchDispatchData(); fetchAvailablePool(); fetchUnavailableStaff(); fetchConfirmations(); }}
            disabled={isLoading}
            className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40"
            title="Refresh dispatch data"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Row 2 — inputs + admin clear */}
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="number"
            placeholder="Total Trucks"
            value={totalTrucks}
            onChange={(e) => {
              const val = e.target.value ? Number(e.target.value) : '';
              if (val === '') setTotalTrucks('');
              else setTotalTrucks(Math.min(val, Object.keys(trucks).length));
            }}
            max={Object.keys(trucks).length || 1}
            className="w-32 rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm focus:border-primary outline-none"
            min="1"
          />
          <input
            type="number"
            placeholder="Total Employees"
            value={totalEmployees}
            onChange={(e) => {
              const val = e.target.value ? Number(e.target.value) : '';
              if (val === '') setTotalEmployees('');
              else setTotalEmployees(Math.min(val, Object.keys(employees).length));
            }}
            max={Object.keys(employees).length || 1}
            className="w-36 rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm focus:border-primary outline-none"
            min="1"
          />
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm focus:border-primary focus:ring-1 focus:ring-primary outline-none"
          />
          {isAdmin && (
            <button
              onClick={handleClearDispatch}
              disabled={isLoading || !dispatchData}
              className="bg-danger text-danger-foreground hover:bg-danger/90 px-4 py-2 rounded-lg font-medium transition-colors shadow-sm flex items-center gap-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
              title="Permanently remove entire dispatch for today"
            >
              <Trash2 className="w-4 h-4" />
              Clear Dispatch
            </button>
          )}
        </div>

        {/* Row 3 — workflow actions */}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleRunDispatch}
            disabled={isLoading}
            className="btn-primary flex items-center gap-2"
          >
            {isLoading ? (
              <div className="w-4 h-4 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Run Dispatch
          </button>
          <button
            onClick={handlePublishToDiscord}
            disabled={isPublishing || isLoading || !dispatchData}
            className="bg-success text-white hover:bg-success/90 px-4 py-2 rounded-lg font-medium transition-colors shadow-sm flex items-center gap-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            title="DM each crew member their assignment and open the confirmation window"
          >
            {isPublishing ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            Publish Initial Confirmations to Discord
          </button>
          <button
            onClick={handleFinalize}
            disabled={isFinalizing || isLoading || !dispatchData || !isPublished}
            className="bg-info text-white hover:bg-info/90 px-4 py-2 rounded-lg font-medium transition-colors shadow-sm flex items-center gap-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            title="Post confirmed crew lists to each truck channel and #drivers-chat"
          >
            {isFinalizing ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <CheckCircle2 className="w-4 h-4" />
            )}
            Post Final Crews
          </button>
          {/* Live polling indicator — visible while waiting for crew responses */}
          {isPollingConfirmations && Object.values(confirmations).some(s => s === 'pending') && (
            <span className="flex items-center gap-1.5 text-xs text-warning font-medium">
              <div className="w-2 h-2 rounded-full bg-warning animate-pulse" />
              Awaiting responses&hellip;
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-danger/50 bg-danger/10 p-4 flex gap-3 text-danger">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <p className="text-sm font-medium">{error}</p>
        </div>
      )}

      {confirmationsStale && (
        <div className="rounded-lg border border-warning/50 bg-warning/10 p-3 flex items-center gap-3 text-warning">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <p className="text-sm font-medium">
            Confirmation data may be stale — the server hasn't responded to the last 3 polls. Check your connection or refresh manually.
          </p>
          <button
            onClick={() => { setConfirmationsStale(false); fetchConfirmations(); }}
            className="ml-auto text-xs font-semibold underline underline-offset-2 hover:opacity-80 transition-opacity whitespace-nowrap"
          >
            Retry now
          </button>
        </div>
      )}

      {/* WARNINGS Block */}
      {dispatchData?.warnings && dispatchData.warnings.length > 0 && (
        <div className="card space-y-3 border-warning border mb-4 bg-warning/5">
          <h3 className="font-semibold text-warning flex items-center gap-2 text-sm uppercase tracking-wide">
            <AlertCircle className="w-4 h-4" />
            Dispatch Warnings ({dispatchData.warnings.length})
          </h3>
          <ul className="text-sm list-disc list-inside text-warning pl-4 space-y-1">
            {dispatchData.warnings.map((w, idx) => (
              <li key={idx}>{w.message}</li>
            ))}
          </ul>

          {/* Staff shortage call-in list — fires on any understaffed warning when staff are unavailable */}
          {dispatchData.warnings.some(w => w.type === 'understaffed_drivers' || w.type === 'understaffed_trainers' || w.type === 'understaffed_walkers') && unavailableStaff.length > 0 && (
            <div className="border-t border-warning/30 pt-3 space-y-2">
              <button
                onClick={() => setShowCallInList(p => !p)}
                className="flex items-center gap-2 text-sm font-medium text-warning hover:text-warning/80 transition-colors"
              >
                <Phone className="w-4 h-4" />
                {showCallInList ? 'Hide' : 'Show'} call-in list ({unavailableStaff.length} staff member{unavailableStaff.length !== 1 ? 's' : ''} unavailable)
                {showCallInList ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>

              {showCallInList && (
                <div className="space-y-2 pt-1">
                  <p className="text-xs text-subtle">
                    These staff members are off today. Call to confirm availability before adding to dispatch.
                  </p>
                  {unavailableStaff.map((member: UnavailableStaff) => (
                    <div
                      key={member.id}
                      className="flex items-center justify-between rounded-lg bg-card border border-border px-3 py-2"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-foreground">{member.name}</p>
                          <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-subtle capitalize">{member.role}</span>
                        </div>
                        <p className="text-xs text-subtle mt-0.5">
                          {member.reason === 'time_off_request' ? 'Approved time-off request' : 'Recurring day off'}
                          {member.phone_number && (
                            <span className="ml-2 font-medium text-foreground">{member.phone_number}</span>
                          )}
                          {member.discord_id && (
                            <span className="ml-2 text-primary">@{member.discord_id}</span>
                          )}
                        </p>
                      </div>
                      <button
                        onClick={() => handleAddUnavailableStaff(member)}
                        disabled={addingStaffId === member.id}
                        className="flex items-center gap-1 text-xs font-medium bg-primary text-primary-foreground px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {addingStaffId === member.id ? (
                          <div className="w-3 h-3 border border-primary-foreground border-t-transparent rounded-full animate-spin" />
                        ) : (
                          <Plus className="w-3 h-3" />
                        )}
                        Add to dispatch
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-col gap-6">
        
        {/* Unassigned List */}
        <div className="w-full">
          <div className="card h-full space-y-4">
            <h2 className="text-lg font-semibold text-foreground flex items-center gap-2 border-b border-border pb-2">
              <Users className="w-5 h-5 text-primary" />
              Unassigned ({unassigned.length})
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-x-2 gap-y-3 max-h-[300px] overflow-y-auto pr-1">
              {unassigned.map((emp, index) => {
                const currentRole = (emp.role || 'walker').toLowerCase();
                const prevRole = index > 0 ? (unassigned[index - 1].role || 'walker').toLowerCase() : '';
                const showHeader = currentRole !== prevRole;

                return (
                  <React.Fragment key={emp.id}>
                    {showHeader && (
                      <div className="col-span-full flex items-center justify-center gap-2 mt-1 -mb-1 opacity-80">
                        <div className="h-px bg-border/60 flex-1"></div>
                        <span className="text-[10px] font-bold text-subtle uppercase tracking-widest text-center">{currentRole}s</span>
                        <div className="h-px bg-border/60 flex-1"></div>
                      </div>
                    )}
                    <div 
                      draggable
                      onDragStart={(e) => handleDragStart(e, emp.id)}
                      className="flex items-center gap-2 bg-accent/50 p-2 rounded border border-transparent hover:border-primary/30 cursor-grab active:cursor-grabbing"
                    >
                      <GripVertical className="w-4 h-4 text-muted-foreground shrink-0" />
                      <div className="overflow-hidden">
                        <p className="text-sm font-medium text-foreground truncate leading-tight">{emp.name}</p>
                        <p className="text-[10px] text-subtle uppercase tracking-wider">{emp.role}</p>
                      </div>
                    </div>
                  </React.Fragment>
                );
              })}
              {unassigned.length === 0 && (
                <p className="text-sm text-subtle italic text-center py-4">All available employees assigned</p>
              )}
            </div>
          </div>
        </div>

        {/* Dispatch Grid */}
        <div className="w-full card">
          <div className="flex items-center justify-between border-b border-border pb-4 mb-4">
            <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
              <Truck className="w-5 h-5 text-primary" />
              Assignments for {selectedDate}
            </h2>
          </div>

          {!dispatchData ? (
            <div className="py-12 text-center flex flex-col items-center">
              <Users className="w-12 h-12 text-muted-foreground mb-3 opacity-20" />
              <h3 className="text-base font-medium text-foreground">No dispatch published</h3>
              <p className="text-sm text-subtle mt-1 max-w-sm">
                There is currently no dispatch data available for this date. 
                Click 'Run Dispatch' to automatically assign employees to trucks.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
               {Object.entries(dispatchData.assigned_crews).map(([truckId, crew]) => (
                 <div 
                   key={truckId} 
                   className={`card-elevated border border-border flex flex-col transition-colors min-h-[160px]`}
                   onDragOver={(e) => e.preventDefault()}
                   onDrop={(e) => handleDropToTruck(e, truckId)}
                 >
                   <div className="flex items-center justify-between mb-3 pb-2 border-b border-border">
                     <div className="flex items-center gap-2">
                       <div className="w-8 h-8 rounded bg-primary/10 flex items-center justify-center">
                         <Truck className="w-4 h-4 text-primary" />
                       </div>
                       <h3 className="font-semibold text-foreground text-sm uppercase tracking-wide">
                            {trucks[truckId]?.name || `Truck ${truckId.substring(0,4)}`}
                       </h3>
                     </div>
                     <div className={`px-2 py-1 text-xs font-semibold rounded-full ${crew.length >= maxCrewSize ? 'bg-success/20 text-success' : 'bg-warning/20 text-warning'}`}>
                       {crew.length} / {maxCrewSize}
                     </div>
                   </div>

                   <div className="space-y-2 flex-1 relative">
                     {(() => {
                       const sortedCrew = [...crew].sort(sortCrewMembers);
                       return sortedCrew.map((member: any, index: number) => {
                         const currentRole = (employees[member.employee_id]?.role || member.role || 'walker').toLowerCase();
                         const prevMember = index > 0 ? sortedCrew[index - 1] : null;
                         const prevRole = prevMember ? (employees[prevMember.employee_id]?.role || prevMember.role || 'walker').toLowerCase() : '';
                         const showHeader = currentRole !== prevRole;

                         return (
                           <React.Fragment key={member.employee_id}>
                             {showHeader && (
                               <div className="flex items-center justify-center gap-2 mt-2 -mb-1 opacity-80 pt-1">
                                 <div className="h-px bg-border/60 flex-1"></div>
                                 <span className="text-[10px] font-bold text-subtle uppercase tracking-widest text-center">{currentRole}s</span>
                                 <div className="h-px bg-border/60 flex-1"></div>
                               </div>
                             )}
                             <div
                               draggable
                               onDragStart={(e) => handleDragStart(e, member.employee_id, truckId)}
                               className="flex justify-between items-center group bg-background border border-border rounded p-2 cursor-grab active:cursor-grabbing shadow-sm drop-shadow-sm"
                             >
                               <div className="flex items-center gap-2">
                                 <GripVertical className="w-4 h-4 text-muted-foreground opacity-30 group-hover:opacity-100" />
                                 <div>
                                   <p className="text-sm font-medium text-foreground leading-tight">{member.name || member.employee_id}</p>
                                   <p className="text-[10px] text-subtle uppercase tracking-wider">{employees[member.employee_id]?.role || member.role}</p>
                                 </div>
                               </div>
                               <div className="flex items-center gap-1">
                                 {(() => {
                                   const conf = confirmations[member.employee_id];
                                   if (!conf) return null;
                                   if (conf === 'confirmed') return <CheckCircle2 className="w-4 h-4 text-success" aria-label="Confirmed" />;
                                   if (conf === 'declined')  return <XCircle className="w-4 h-4 text-danger" aria-label="Declined" />;
                                   return <Clock className="w-4 h-4 text-warning" aria-label="Pending confirmation" />;
                                 })()}
                                 <button
                                   onClick={() => handleRemoveFromTruck(member.employee_id)}
                                   className="text-muted-foreground hover:text-danger p-1 opacity-40 hover:opacity-100 transition-opacity"
                                   title="Remove from assignment"
                                 >
                                   <Trash2 className="w-4 h-4" />
                                 </button>
                               </div>
                             </div>
                           </React.Fragment>
                         );
                       });
                     })()}
                     {crew.length === 0 && (
                       <div className="flex items-center justify-center pt-6 pb-2 pointer-events-none">
                         <p className="text-xs text-subtle italic">Drag employees here</p>
                       </div>
                     )}
                   </div>
                 </div>
               ))}
               
               {Object.keys(dispatchData.assigned_crews).length === 0 && (
                 <p className="text-sm text-subtle col-span-full text-center py-8">No trucks have valid configurations today.</p>
               )}
            </div>
          )}
        </div>
      </div>

      {dialog && (
        <ConfirmDialog
          open
          title={dialog.title}
          message={dialog.message}
          confirmLabel={dialog.confirmLabel}
          variant={dialog.variant}
          onConfirm={dialog.onConfirm}
          onCancel={closeDialog}
        />
      )}
    </div>
  );
}
