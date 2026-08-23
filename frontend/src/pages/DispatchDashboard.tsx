import { errorText } from '../utils/errorText';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { Truck, Users, AlertCircle, Play, GripVertical, Plus, Trash2, Phone, Mail, Info, ChevronDown, ChevronUp, RefreshCw, Send, CheckCircle2, XCircle, Clock, ArrowRightLeft } from 'lucide-react';
import type { UnavailableStaff, EmergencyPoolMember, DispatchResult, FinalizeResponse } from '../api/types';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { getLocalYMD } from '../utils/date';
import PreviousAssignments from '../components/PreviousAssignments';
import { useNotificationContext } from '../contexts/NotificationContext';

/* Availability for the SELECTED date, derived from data the page already holds
   (ADR-266). `unavailable-staff` is fetched on every date change and returns a
   reason per employee; absence from that list is what "available" means. No
   extra request, and no second source of truth to drift from the call-in list
   rendered further down. */
type AvailabilityKey = 'available' | 'pto' | 'scheduled_off';

const AVAILABILITY: Record<AvailabilityKey, { label: string; cls: string; title: string }> = {
  available:     { label: 'Available',     cls: 'badge-success', title: 'Working this date' },
  pto:           { label: 'PTO',           cls: 'badge-info',    title: 'Approved time-off request' },
  // Distinct from PTO on purpose: this is the person's normal weekly pattern,
  // not leave they asked for — which is the difference dispatch weighs when
  // deciding who to call in.
  scheduled_off: { label: 'Scheduled off', cls: 'badge-slate',   title: 'Recurring day off' },
};

function availabilityOf(
  employeeId: string,
  unavailable: UnavailableStaff[],
): AvailabilityKey {
  const hit = unavailable.find((u) => u.id === employeeId);
  if (!hit) return 'available';
  return hit.reason === 'time_off_request' ? 'pto' : 'scheduled_off';
}

type DispatchTab = 'current' | 'previous';

/** Tab shell (ADR-268).

    Two surfaces rather than one board with a date control: every write here is
    keyed to the date, so a shared picker let a past day be published against.
    Splitting them means the current board can only ever act on today, and the
    history view can only ever read. */
export default function DispatchDashboard() {
  const [tab, setTab] = useState<DispatchTab>('current');

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm w-fit">
        {([['current', 'Current Assignments'], ['previous', 'Previous Assignments']] as [DispatchTab, string][])
          .map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                tab === k
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {label}
            </button>
          ))}
      </div>

      {tab === 'current' ? <CurrentAssignments /> : <PreviousAssignments />}
    </div>
  );
}

function CurrentAssignments() {
  const { groups } = useAuth();
  const { setOnNotification } = useNotificationContext();
  const isAdmin = groups.includes('admin') || groups.includes('Admin');
  /* Today, always. The picker that used to set this lived on the same surface
     as every write (publish, finalize, assign, swap, remove), all of which are
     keyed to it — so a dispatcher could select a past date and publish crews
     against a day that had already happened. Viewing history now lives in the
     Previous Assignments tab, which is read-only, so the hazard is removed by
     construction rather than by disabling controls (ADR-268). */
  const selectedDate = getLocalYMD();
  const [totalEmployees, setTotalEmployees] = useState<number | ''>('');
  // ADR-202: dispatch selects the exact trucks to send out; the count is derived.
  const [selectedTruckIds, setSelectedTruckIds] = useState<Set<string>>(new Set());
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
  // Emergency pool (ADR-267): everyone dispatch can still phone, and why they
  // are free. Supersedes the call-in list's membership — that one listed PTO
  // (who must not be called) and omitted decliners and unassigned staff (who
  // are exactly who you call).
  const [emergencyPool, setEmergencyPool] = useState<EmergencyPoolMember[]>([]);
  /* Who the dispatcher has actually reached out to this session (ADR-267).
     Gates the Add button — adding someone who is off, without speaking to
     them, schedules a shift they never agreed to. Deliberately session-only:
     it is a UI nudge, not a claim of record, and persisting it would imply an
     audit trail that does not exist. */
  const [contactedIds, setContactedIds] = useState<Set<string>>(new Set());
  const [showCallInList, setShowCallInList] = useState(false);
  const [addingStaffId, setAddingStaffId] = useState<string | null>(null);
  // confirmations: { [employee_id]: "pending" | "confirmed" | "declined" }
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});
  const [isPollingConfirmations, setIsPollingConfirmations] = useState(false);
  const [confirmingEmployee, setConfirmingEmployee] = useState<string | null>(null);
  const [confirmationsStale, setConfirmationsStale] = useState(false);
  const [companyTimezone, setCompanyTimezone] = useState<string | null>(null);
  const confirmationPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dispatchPhasePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollFailureCount = useRef(0);

  // transfers: employee_id → most-recent transfer for selected date
  const [transfers, setTransfers] = useState<Record<string, { to_truck_name: string; from_truck_name: string }>>({});
  // transfer modal state
  const [transferModal, setTransferModal] = useState<{ employeeId: string; employeeName: string } | null>(null);
  const [transferDestTruckId, setTransferDestTruckId] = useState<string>('');
  const [transferNote, setTransferNote] = useState<string>('');
  const [isTransferring, setIsTransferring] = useState(false);
  const [transferWarnings, setTransferWarnings] = useState<string[]>([]);
  // ADR-256 D3: trucks that finalized without a captain. Warn-only for now —
  // enforcement lands once captains are staffed and assign_captains places them.
  const [captainlessTrucks, setCaptainlessTrucks] = useState<string[]>([]);
  // hub state
  const [showHubModal, setShowHubModal] = useState(false);
  const [hubModalTruckId, setHubModalTruckId] = useState<string>('');

  /* Hubs that can still take an assignment for this date: hub trucks (ADR-274
     D1) minus any already assigned. Derived once and shared by the "+ Add Hub"
     trigger and the modal, so the two cannot disagree about what is on offer. */
  const availableHubs = Object.entries(trucks)
    .filter(([id, t]: [string, any]) => t.is_hub && !assignedTruckIds.has(id))
    .map(([id, t]: [string, any]) => ({ id, name: t.name as string }));
  const anyHubsConfigured = Object.values(trucks).some((t: any) => t.is_hub);
  const [isCreatingHub, setIsCreatingHub] = useState(false);
  const [publishingHubTruckId, setPublishingHubTruckId] = useState<string | null>(null);

  /* ── Dock zones (ADR-274 D17) ──────────────────────────────────────────────
     The physical bay a truck collects from. `suggestions` holds each truck's
     last known bay plus its recent ones; a value that came from history renders
     muted until dispatch confirms or edits it.

     Publish applies an unconfirmed suggestion anyway (the backend resolves it),
     so this UI is about VISIBILITY — which bays have actually been looked at —
     not about whether the driver gets one. */
  const [dockDrafts, setDockDrafts] = useState<Record<string, string>>({});
  const [dockSuggest, setDockSuggest] = useState<Record<string, { prefill: string; recent: string[] }>>({});
  const [dockSaving, setDockSaving] = useState<string | null>(null);
  const [removingHubTruckId, setRemovingHubTruckId] = useState<string | null>(null);

  type DialogConfig = { title: string; message: string; confirmLabel: string; variant: 'danger' | 'warning' | 'default'; onConfirm: () => void };
  const [dialog, setDialog] = useState<DialogConfig | null>(null);

  // Trainee→trainer pairing picker (ADR-210): which trainee's picker is open, and pending write.
  const [pairingFor, setPairingFor] = useState<string | null>(null);
  const [savingPairing, setSavingPairing] = useState(false);

  // Close the pairing picker on outside-click / Escape.
  useEffect(() => {
    if (!pairingFor) return;
    const onDown = () => setPairingFor(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPairingFor(null); };
    // pointerdown fires before the button's onClick toggle; delay attach a tick so
    // opening the picker doesn't immediately close it.
    const t = setTimeout(() => {
      window.addEventListener('pointerdown', onDown);
      window.addEventListener('keydown', onKey);
    }, 0);
    return () => { clearTimeout(t); window.removeEventListener('pointerdown', onDown); window.removeEventListener('keydown', onKey); };
  }, [pairingFor]);

  // Contact card popover (ADR-266): which employee's details are open. Same
  // shape and same dismissal as the pairing picker above — including the
  // setTimeout, without which the listener fires on the click that opened it.
  const [contactFor, setContactFor] = useState<string | null>(null);
  useEffect(() => {
    if (!contactFor) return;
    const onDown = () => setContactFor(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setContactFor(null); };
    /* The panel is position:fixed so it can escape the pool's overflow clip,
       which means it does NOT travel with the card. Closing on scroll beats
       leaving it stranded over unrelated rows. Capture phase: the pool is an
       inner scroller and its scroll events do not bubble to window. */
    const onScroll = () => setContactFor(null);
    const t = setTimeout(() => {
      window.addEventListener('pointerdown', onDown);
      window.addEventListener('keydown', onKey);
      window.addEventListener('scroll', onScroll, true);
    }, 0);
    return () => {
      clearTimeout(t);
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [contactFor]);

  /* Only one overlay per card. Opening either closes the other, so a trainee's
     pairing picker and their contact card cannot stack. */
  const openContact = (id: string) => {
    setPairingFor(null);
    setContactFor((cur) => (cur === id ? null : id));
  };
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

  const stopDispatchPhasePolling = () => {
    if (dispatchPhasePollRef.current !== null) {
      clearInterval(dispatchPhasePollRef.current);
      dispatchPhasePollRef.current = null;
    }
  };

  // One-shot dispatch-phase fetch. Returns true once the terminal state
  // (finalized) is reached so callers can stop their fallback poll. Used both
  // by the fallback interval below and by the SSE handler (ADR-179).
  const fetchDispatchPhaseOnce = useCallback(async (date: string): Promise<boolean> => {
    try {
      const res = await axiosClient.get(`/dispatch/${date}`);
      // Best-effort: a failed suggestion fetch leaves the fields empty and
      // typeable, which is strictly better than blocking the board on it.
      axiosClient.get(`/dispatch/${date}/dock-suggestions`)
        .then(r => {
          const map: Record<string, { prefill: string; recent: string[] }> = {};
          for (const t of r.data?.trucks ?? []) {
            map[t.truck_id] = { prefill: t.prefill, recent: t.recent ?? [] };
          }
          setDockSuggest(map);
        })
        .catch(() => {/* no history yet — dispatch types the bay */});
      const hasCrews = Object.keys(res.data.assigned_crews).length > 0;
      // ADR-286: "none" is TRUTHY, and it means dispatch has NOT run. A bare
      // `!!workflow_status` would read a hub-only day as "dispatch ran".
      const hasStatus = !!res.data.workflow_status && res.data.workflow_status !== 'none';
      setDispatchData((!hasCrews && !hasStatus) ? null : res.data);
      return res.data.workflow_status === 'finalized';
    } catch {
      return false; // silent — stale UI is acceptable, user can Refresh
    }
  }, []);

  // Fallback poll for phase changes made on another tab/device (co-dispatcher
  // clicking Publish/Finalize). SSE (dispatch_finalized) is the primary channel;
  // this 60s poll only catches a missed event. Self-terminates on finalized —
  // the phase can't regress. (ADR-179: was a 30s primary poll.)
  const startDispatchPhasePolling = useCallback((date: string) => {
    stopDispatchPhasePolling();
    dispatchPhasePollRef.current = setInterval(async () => {
      if (await fetchDispatchPhaseOnce(date)) stopDispatchPhasePolling();
    }, 60000);
  }, [fetchDispatchPhaseOnce]);

  // One-shot confirmations fetch. Returns true once no confirmation is pending
  // (terminal), so the fallback poll / SSE handler can stop.
  const fetchConfirmationsOnce = useCallback(async (date: string): Promise<boolean> => {
    try {
      const res = await axiosClient.get(`/dispatch/${date}/confirmations`);
      const data: Record<string, string> = res.data.confirmations || {};
      pollFailureCount.current = 0;
      setConfirmationsStale(false);
      setConfirmations(data);
      const values = Object.values(data);
      return values.length > 0 && values.every(s => s !== 'pending');
    } catch {
      pollFailureCount.current += 1;
      if (pollFailureCount.current >= 3) setConfirmationsStale(true);
      return false;
    }
  }, []);

  // Fallback poll while the confirmation window is open. SSE (crew_all_confirmed)
  // is the primary channel; this 60s poll catches individual confirms and a
  // missed all-confirmed event. Self-terminates when all responses are in.
  // (ADR-179: was a 15s primary poll.)
  const startConfirmationPolling = useCallback((date: string) => {
    stopConfirmationPolling();
    setIsPollingConfirmations(true);
    setConfirmationsStale(false);
    confirmationPollRef.current = setInterval(async () => {
      if (await fetchConfirmationsOnce(date)) stopConfirmationPolling();
    }, 60000);
  }, [fetchConfirmationsOnce]);

  useEffect(() => {
    fetchTrucksAndEmployees();
    axiosClient.get('/companies/my-info').then(r => setCompanyTimezone(r.data.timezone)).catch(() => {});
    return () => {
      stopConfirmationPolling();
      stopDispatchPhasePolling();
    };
  }, []);

  // SSE-driven refetch (ADR-179): the backend emits dispatch_finalized when
  // dispatch is finalized and crew_all_confirmed when the last pending
  // confirmation flips. Refetch once on receipt so terminal transitions arrive
  // faster than the 60s fallback poll, then let those fetchers stop the polls.
  useEffect(() => {
    setOnNotification((type: string) => {
      if (type === 'dispatch_finalized') {
        fetchDispatchPhaseOnce(selectedDate).then(done => {
          if (done) stopDispatchPhasePolling();
        });
      } else if (type === 'crew_all_confirmed') {
        fetchConfirmationsOnce(selectedDate).then(done => {
          if (done) stopConfirmationPolling();
        });
      }
    });
    return () => setOnNotification(null);
  }, [selectedDate, setOnNotification, fetchDispatchPhaseOnce, fetchConfirmationsOnce]);

  useEffect(() => {
    stopConfirmationPolling();
    stopDispatchPhasePolling();
    setConfirmationsStale(false);
    fetchDispatchData();
    fetchAvailablePool();
    fetchUnavailableStaff();
    fetchEmergencyPool();
    fetchConfirmations();
    fetchTransfers(selectedDate);
    startDispatchPhasePolling(selectedDate);
  }, [selectedDate]);

  const fetchConfirmations = async () => {
    try {
      const res = await axiosClient.get(`/dispatch/${selectedDate}/confirmations`);
      setConfirmations(res.data.confirmations || {});
    } catch {
      // No confirmations yet — not an error worth surfacing
    }
  };

  const fetchTransfers = async (date: string) => {
    try {
      const res = await axiosClient.get(`/truck-transfers?date=${date}`);
      const map: Record<string, { to_truck_name: string; from_truck_name: string }> = {};
      for (const t of res.data) {
        map[t.employee_id] = { to_truck_name: t.to_truck_name, from_truck_name: t.from_truck_name };
      }
      setTransfers(map);
    } catch {
      setTransfers({});
    }
  };

  const handleTransfer = async () => {
    if (!transferModal || !transferDestTruckId) return;
    setIsTransferring(true);
    setTransferWarnings([]);
    try {
      const res = await axiosClient.post('/truck-transfers', {
        employee_ids: [transferModal.employeeId],
        to_truck_id: transferDestTruckId,
        date: selectedDate,
        note: transferNote.trim() || null,
      });
      if (res.data.warnings?.length) setTransferWarnings(res.data.warnings);
      await fetchTransfers(selectedDate);
      if (!res.data.warnings?.length) {
        setTransferModal(null);
        setTransferDestTruckId('');
        setTransferNote('');
      }
    } catch (err: unknown) {
      setTransferWarnings([errorText(err, 'Transfer failed.')]);
    } finally {
      setIsTransferring(false);
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
          const res = await axiosClient.post(`/dispatch/${selectedDate}/publish`);
          // Partial-success channel: publish committed but a delivery leg
          // (e.g. Discord bot) failed — surface it without blocking.
          if (res.data?.warnings?.length) {
            setError(res.data.warnings.join(' '));
          }
          await Promise.all([fetchDispatchData(), fetchConfirmations()]);
          startConfirmationPolling(selectedDate);
        } catch (err: unknown) {
          setError(errorText(err, 'Failed to publish to Discord.'));
        } finally {
          setIsPublishing(false);
        }
      },
    });
  };

  const handleFinalize = () => {
    if (!dispatchData) return;
    // Hard block (also enforced by the backend) — should be unreachable since the
    // button is disabled, but guard the handler too.
    if (confirmationGate.block) {
      setError('Post Final Crews is blocked — under 50% confirmed on at least one truck.');
      return;
    }
    const lowNote = confirmationGate.warn
      ? `⚠ Low confirmations on ${confirmationGate.below80.map(t => `${t.name} (${t.confirmed}/${t.total})`).join(', ')}. Pending crew will not be posted. `
      : '';
    openDialog({
      title: 'Post Final Crews',
      message: `${lowNote}Post confirmed crews to each truck channel and the master list to #drivers-chat for ${selectedDate}?`,
      confirmLabel: 'Post Final Crews',
      variant: confirmationGate.warn ? 'warning' : 'default',
      onConfirm: async () => {
        closeDialog();
        setIsFinalizing(true);
        setError(null);
        stopConfirmationPolling();
        try {
          const res = await axiosClient.post<FinalizeResponse>(
            `/dispatch/${selectedDate}/finalize`,
          );
          // ADR-256 D3 is warn-only: finalize succeeds with captainless trucks, and
          // the response is the only place that says which. Discarding it — as this
          // did — meant the warning existed on the server and reached nobody.
          const captainless = res.data?.captainless_trucks ?? [];
          setCaptainlessTrucks(captainless);
          await fetchDispatchData();
        } catch (err: unknown) {
          setError(errorText(err, 'Failed to post final assignments to Discord.'));
        } finally {
          setIsFinalizing(false);
        }
      },
    });
  };

  const handleConfirmEmployee = async (employeeId: string) => {
    setConfirmingEmployee(employeeId);
    try {
      await axiosClient.post(`/dispatch/${selectedDate}/confirmations`, {
        employee_id: employeeId,
        status: 'confirmed',
      });
      setConfirmations(prev => ({ ...prev, [employeeId]: 'confirmed' }));
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to confirm employee.'));
    } finally {
      setConfirmingEmployee(null);
    }
  };

  const fetchUnavailableStaff = async () => {
    try {
      const res = await axiosClient.get(`/dispatch/unavailable-staff/${selectedDate}`);
      setUnavailableStaff(res.data.unavailable_staff || []);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchEmergencyPool = async () => {
    try {
      const res = await axiosClient.get(`/dispatch/emergency-pool/${selectedDate}`);
      setEmergencyPool(res.data.pool || []);
    } catch (e) {
      console.error(e);
    }
  };

  // Structural, not UnavailableStaff: the emergency pool calls this too, and
  // the body only ever reads these three fields. Widening beats an `as any` at
  // the call site, which would hide a real mismatch if the body grows.
  const handleAddUnavailableStaff = async (member: { id: string; name: string; role: string }) => {
    if (!dispatchData) return;
    // ONE PER TRUCK roles (driver, captain) need a truck that lacks that role;
    // everyone else can join any truck. Captain was missing here, so adding one
    // dropped them onto the first truck in the list even if it already had a
    // captain (ADR-256).
    let targetTruckId: string | undefined;
    if (member.role === 'driver' || member.role === 'captain') {
      const entry = Object.entries(dispatchData.assigned_crews).find(
        ([, crew]) => !crew.some((m: any) => m.role === member.role)
      );
      if (!entry) {
        setError(`All trucks already have a ${member.role}. Use the unassigned panel to place manually.`);
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
    } catch (err: unknown) {
      setError(errorText(err, `Failed to add ${member.name} to dispatch.`));
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

      // Include all dispatch-eligible roles from the availability-filtered
      // response. CAPTAIN belongs here (ADR-256): omitting it meant a captain
      // removed from a truck never reappeared in the unassigned list, so they
      // looked deleted rather than unassigned.
      // ADR-264: driver_trainee belongs here for the same reason captain does.
      // Omitted, a held-out driver trainee is absent from availablePool, and the
      // drop handler's `emp?.role || 'walker'` fallback would silently assign
      // them as a WALKER — the backend then trains nobody, because injection
      // keys on the driver_trainee slot.
      ['driver', 'captain', 'trainer', 'walker', 'trainee', 'driver_trainee'].forEach(role => {
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
      
      // Only null out dispatchData if there are genuinely no assignments AND no
      // workflow_status — an empty crew dict with a status means dispatch ran
      // and the button must stay disabled.
      //
      // ADR-286: except "none", which is truthy and means the opposite. A day
      // holding only a hub reports "none", and treating that as "dispatch ran"
      // is the bug this ADR removed on the backend arriving by a second route.
      const hasCrews = Object.keys(response.data.assigned_crews).length > 0;
      const hasStatus =
        !!response.data.workflow_status && response.data.workflow_status !== 'none';
      if (!hasCrews && !hasStatus) {
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
    if (selectedTruckIds.size === 0) {
      setError('Select at least one truck to dispatch.');
      return;
    }
    try {
      setIsLoading(true);
      setError(null);
      const payload: any = { date: selectedDate, truck_ids: Array.from(selectedTruckIds) };
      if (totalEmployees) payload.total_employees = totalEmployees;

      await axiosClient.post('/dispatch/', payload);
      // Render from the canonical GET payload (not the POST body) so pairings and
      // any other GET-only fields show immediately — the POST response shape and
      // the GET shape must not silently drift (ADR-210 follow-up).
      await Promise.all([fetchDispatchData(), fetchAvailablePool()]);
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
        // ASSIGN: from unassigned to truck. The employee's job title is the
        // DEFAULT slot, not the slot itself — AssignmentMember.role is the job
        // for the day (ADR-256 D2).
        const emp = availablePool[employeeId] || employees[employeeId];
        let role = emp?.role || 'walker';

        // ADR-284 — a hub crew is walkers. A hub runs no route, so a captain
        // leads nothing and a trainer supervises nobody. The backend coerces
        // this too and is the real guarantee; sending the right slot here just
        // keeps the request honest and avoids a pointless round trip.
        const targetIsHub = !!trucks[targetTruckId]?.is_hub;
        if (targetIsHub) {
          if (role === 'trainee') {
            // D2 — refused, not coerced: a trainee on a hub is unsupervised,
            // and a silent relabel makes the day look like work while their
            // phase progression does not advance.
            setError(
              `${emp?.name || 'That employee'} is a trainee and cannot be assigned to a hub — ` +
              `there is no route to run and no trainer to supervise them.`
            );
            return;
          }
          if (role === 'captain' || role === 'trainer') role = 'walker';
        }

        // The server is authoritative on the effective slot; the refetch below
        // pulls it into assigned_crews, and the card renders that slot rather
        // than the job title — so a coercion reads as "Captain Test — WALKER".
        await axiosClient.post('/dispatch/assign', {
          employee_id: employeeId,
          truck_id: targetTruckId,
          date: selectedDate,
          role,
        });
      }
      await fetchDispatchData(); // Refresh on drop
    } catch (err: unknown) {
      console.error(err);
      setError(errorText(err, 'Failed to move employee.'));
    } finally {
      setIsLoading(false);
    }
  };

  // Set (or clear, trainerId=null) a trainee's paired trainer on their truck (ADR-210).
  const setPairing = async (traineeId: string, trainerId: string | null) => {
    setSavingPairing(true);
    try {
      await axiosClient.patch(`/dispatch/assign/${selectedDate}/${traineeId}/pairing`, {
        trainer_id: trainerId,
      });
      setPairingFor(null);
      await fetchDispatchData();
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to update trainer pairing.'));
    } finally {
      setSavingPairing(false);
    }
  };

  // True swap (ADR-210): exchange two employees' trucks in one gesture (drop A onto B).
  const swapTwo = async (empA: string, truckA: string, empB: string, truckB: string) => {
    if (truckA === truckB) return;
    setIsLoading(true);
    try {
      // Move A to B's truck, then B to A's — sequential so the second sees A gone.
      await axiosClient.patch('/dispatch/assign', { employee_id: empA, date: selectedDate, new_truck_id: truckB });
      await axiosClient.patch('/dispatch/assign', { employee_id: empB, date: selectedDate, new_truck_id: truckA });
      await fetchDispatchData();
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to swap the two employees.'));
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
          await Promise.all([fetchDispatchData(), fetchAvailablePool()]);
        } catch (err: unknown) {
          console.error(err);
          setError(errorText(err, 'Failed to remove employee.'));
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
        } catch (err: unknown) {
          setError(errorText(err, 'Failed to clear dispatch.'));
        } finally {
          setIsLoading(false);
        }
      },
    });
  };

  const handleAddHub = async () => {
    if (!hubModalTruckId) return;
    setIsCreatingHub(true);
    setError(null);
    try {
      await axiosClient.post('/dispatch/hubs', { truck_id: hubModalTruckId, date: selectedDate });
      setShowHubModal(false);
      setHubModalTruckId('');
      await fetchDispatchData();
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to create hub.'));
    } finally {
      setIsCreatingHub(false);
    }
  };

  const handleRemoveHub = (truckId: string, crewCount: number, published: boolean) => {
    const truckName = trucks[truckId]?.name || 'Hub';
    // WARN, DO NOT BLOCK (ADR-274 D8). A published hub has crew who were
    // notified and may have confirmed; removing it does not un-notify them.
    // Blocking would leave no recovery from a published mistake, and silent
    // removal would leave people holding a shift that no longer exists.
    const notified = published && crewCount > 0
      ? ` ${crewCount} crew member${crewCount === 1 ? ' was' : 's were'} already notified on Discord — `
        + `removing will NOT tell them, so message them yourself.`
      : '';
    openDialog({
      title: `Remove ${truckName}?`,
      message:
        `This deletes the hub assignment for ${selectedDate}`
        + (crewCount > 0 ? ` and unassigns ${crewCount} crew member${crewCount === 1 ? '' : 's'}` : '')
        + `.${notified}`,
      confirmLabel: 'Remove hub',
      variant: 'danger',
      onConfirm: async () => {
        closeDialog();
        setRemovingHubTruckId(truckId);
        setError(null);
        try {
          await axiosClient.delete(`/dispatch/hubs/${truckId}`, {
            params: { target_date: selectedDate },
          });
          await fetchDispatchData();
        } catch (err: unknown) {
          setError(errorText(err, 'Failed to remove hub.'));
        } finally {
          setRemovingHubTruckId(null);
        }
      },
    });
  };

  /* ── Dock zone handlers (ADR-274 D17) ─────────────────────────────────── */

  /** The bay showing for a truck, and whether it is confirmed or inherited.
   *  `saved` — dispatch set it for today (or publish already resolved one)
   *  `suggested` — the truck's last known bay, offered but not yet confirmed */
  const dockStateFor = (truckId: string): { value: string; suggested: boolean } => {
    if (truckId in dockDrafts) return { value: dockDrafts[truckId], suggested: false };
    const saved = (dispatchData?.truck_assignments || [])
      .find((a: any) => a.truck_id === truckId)?.dock_zone;
    if (saved) return { value: saved, suggested: false };
    return { value: dockSuggest[truckId]?.prefill || '', suggested: true };
  };

  const saveDockZone = async (truckId: string, value: string) => {
    setDockSaving(truckId);
    try {
      await axiosClient.patch(
        `/dispatch/${selectedDate}/trucks/${truckId}/dock`,
        { dock_zone: value.trim() },
      );
      // Refresh so the field flips from suggested to confirmed from the SERVER's
      // answer rather than optimistically — a rejected save must not look saved.
      setDockDrafts(prev => {
        const next = { ...prev }; delete next[truckId]; return next;
      });
      await fetchDispatchPhaseOnce(selectedDate);
    } catch {
      setError('Could not save the dock zone. Try again.');
    } finally {
      setDockSaving(null);
    }
  };

  /** Commit every truck still showing an unconfirmed suggestion.
   *  Publish would apply these anyway; this makes the decision explicit and
   *  visible, so dispatch can see at a glance what they have vetted. */
  const confirmAllSuggestedDocks = async () => {
    const pending = Object.keys(dispatchData?.assigned_crews || {})
      .map(id => ({ id, ...dockStateFor(id) }))
      .filter(d => d.suggested && d.value);
    if (pending.length === 0) return;
    setDockSaving('__all__');
    try {
      for (const d of pending) {
        await axiosClient.patch(
          `/dispatch/${selectedDate}/trucks/${d.id}/dock`,
          { dock_zone: d.value },
        );
      }
      await fetchDispatchPhaseOnce(selectedDate);
      setError(null);
    } catch {
      setError('Some dock zones could not be confirmed. Check and retry.');
    } finally {
      setDockSaving(null);
    }
  };

  const handlePublishHub = (truckId: string) => {
    const truckName = trucks[truckId]?.name || 'Hub';
    openDialog({
      title: 'Publish Hub',
      message: `Send dispatch_assignment notifications to all staff on ${truckName} and post their crew card to Discord?`,
      confirmLabel: 'Publish Hub',
      variant: 'default',
      onConfirm: async () => {
        closeDialog();
        setPublishingHubTruckId(truckId);
        setError(null);
        try {
          await axiosClient.post(`/dispatch/hubs/${truckId}/publish`, { date: selectedDate });
          await fetchDispatchData();
        } catch (err: unknown) {
          setError(errorText(err, 'Failed to publish hub.'));
        } finally {
          setPublishingHubTruckId(null);
        }
      },
    });
  };

  const sortCrewMembers = (a: any, b: any) => {
    /* The SLOT held on this truck today wins over the job title (ADR-256 D2,
       ADR-284). `a.role` comes from assigned_crews and IS the slot; the
       employees map only fills in when a member arrives without one. Reading
       the title first put a hub's coerced captain in the CAPTAINS group while
       the database said walker. */
    const roleA = (a.role || employees[a.employee_id || a.id]?.role || 'walker').toLowerCase();
    const roleB = (b.role || employees[b.employee_id || b.id]?.role || 'walker').toLowerCase();
    
    // CAPTAIN SITS DIRECTLY UNDER DRIVER (ADR-256): the two run the truck and
    // belong together above the people who carry. Missing from this map, a
    // captain fell through to the `|| 5` default and sorted BELOW walkers — the
    // opposite of their standing on the truck.
    const roleOrder: Record<string, number> = {
      driver: 1, captain: 2, trainer: 3, trainee: 4, walker: 5,
    };
    const orderA = roleOrder[roleA] || 6;
    const orderB = roleOrder[roleB] || 6;
    
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

  /* Emergency-pool trigger (ADR-267). Three independent conditions:

       1+ driver/captain decline — a walker short is a slower route; a DRIVER or
         CAPTAIN short is a truck that does not leave. No threshold applies.
       3+ declines of any role   — enough attrition to need a phone.
       understaffed warning      — thin before anyone declined.

     Against the SLOT held today (assigned_crews), not Employee.role: a
     captain-titled employee may be slotted as a walker (ADR-256 D2), and their
     decline then costs a walker, not a truck. */
  const declinedIds = Object.entries(confirmations)
    .filter(([, s]) => s === 'declined')
    .map(([id]) => id);

  /* The SLOT each decliner held today, not their job title — a captain-titled
     employee slotted as a walker costs a walker (ADR-256 D2). */
  const slotRoleOf = (id: string): string | null => {
    for (const crew of Object.values(dispatchData?.assigned_crews ?? {})) {
      const slot = (crew as any[]).find((m) => m.employee_id === id);
      if (slot) return slot.role;
    }
    return null;
  };

  const declinedRoles = declinedIds
    .map(slotRoleOf)
    .filter((r): r is string => r !== null);

  const declineCounts = declinedRoles.reduce<Record<string, number>>((acc, r) => {
    acc[r] = (acc[r] || 0) + 1;
    return acc;
  }, {});

  const criticalDecline = declinedRoles.some((r) => r === 'driver' || r === 'captain');

  /* The decliners as pool members, ordered by how much the gap hurts: a
     captain or driver strands a truck, so those holes are shown first. */
  const _gapOrder: Record<string, number> = { captain: 0, driver: 1, trainer: 2, walker: 3 };
  const declinedMembers = emergencyPool
    .filter((m) => m.reason === 'declined')
    .sort((a, b) => (_gapOrder[slotRoleOf(a.id) || a.role] ?? 9)
                  - (_gapOrder[slotRoleOf(b.id) || b.role] ?? 9));

  /* Name what actually happened. A single hardcoded "Driver/captain declined"
     read as a lie when three walkers called out, and told a dispatcher nothing
     about which hole to fill.

     Ordered by how much each role hurts: a captain or driver strands a truck,
     so those are named individually and first; walkers and trainers are
     reported as counts, because the number is the signal. */
  const declineBadge: string | null = (() => {
    const parts: string[] = [];
    const singular: Record<string, string> = {
      captain: 'Captain out',
      driver: 'Driver out',
    };
    for (const role of ['captain', 'driver']) {
      const n = declineCounts[role] || 0;
      if (n === 1) parts.push(singular[role]);
      else if (n > 1) parts.push(`${n} ${role}s out`);
    }
    for (const role of ['trainer', 'walker']) {
      const n = declineCounts[role] || 0;
      if (n === 1) parts.push(`1 ${role} out`);
      else if (n > 1) parts.push(`${n} ${role}s out`);
    }
    return parts.length ? parts.join(' · ') : null;
  })();

  const understaffed = Boolean(dispatchData?.warnings?.some(
    (w) => w.type === 'understaffed_drivers'
        || w.type === 'understaffed_trainers'
        || w.type === 'understaffed_walkers',
  ));

  const showEmergencyPool =
    (criticalDecline || declinedIds.length >= 3 || understaffed) && emergencyPool.length > 0;

  const unassigned = getUnassignedEmployees();
  /* `maxCrewSize` is gone. It was the largest crew on ANY truck today, falling
     back to 3 — not a capacity. There is no capacity column on Truck and no
     crew-size config, so `20 / 20` in green meant "ties today's biggest crew",
     not "full", and the denominator moved as crews changed. The card now shows
     the count alone: what is known, with nothing invented. */

  // Workflow step derived from durable backend status — never from local flag
  type WorkflowStep = 'none' | 'dispatched' | 'published' | 'finalized';
  const workflowStep: WorkflowStep = !dispatchData
    ? 'none'
    // ADR-286 — the backend now says 'none' explicitly when no NON-HUB
    // assignment exists. Without this branch the value falls through to the
    // `: 'dispatched'` default below, which is the very bug being fixed: a day
    // with only a hub would still disable Run Dispatch.
    : dispatchData.workflow_status === 'none'
    ? 'none'
    : dispatchData.workflow_status === 'finalized'
    ? 'finalized'
    : dispatchData.workflow_status === 'published'
    ? 'published'
    : 'dispatched';

  // Finalize gate by per-truck confirmation rate (ADR-205). Rate = confirmed /
  // crew on each truck. If ANY truck is < 50% → BLOCK Post Final Crews (posting
  // would push near-empty crews to Discord). If any truck is 50–80% → WARN and
  // require an explicit confirm. ≥ 80% everywhere → clean. Only relevant once
  // published (before that, zero confirmations is expected). The backend enforces
  // the < 50% block too — this is UX, not the safety boundary.
  const FINALIZE_BLOCK = 0.5;
  const FINALIZE_WARN = 0.8;
  const confirmationGate = useMemo(() => {
    const crews: Record<string, any[]> = dispatchData?.assigned_crews ?? {};
    const live = workflowStep === 'published';
    const truckStats = Object.entries(crews)
      .map(([truckId, crew]) => {
        const total = crew.length;
        const confirmed = crew.filter(m => confirmations[m.employee_id] === 'confirmed').length;
        return { name: trucks[truckId]?.name || 'Unnamed truck', total, confirmed, rate: total ? confirmed / total : 1 };
      })
      .filter(t => t.total > 0);   // trucks with no crew don't gate

    const below50 = truckStats.filter(t => t.rate < FINALIZE_BLOCK);
    const below80 = truckStats.filter(t => t.rate < FINALIZE_WARN);
    return {
      live,
      truckStats,
      block: live && below50.length > 0,       // hard gate
      warn: live && below50.length === 0 && below80.length > 0,  // soft gate
      below50, below80,
    };
  }, [dispatchData, confirmations, trucks, workflowStep]);

  // Hub trucks come from the TRUCK, not from a status (ADR-274).
  //
  // This used to filter `status === 'planned'` with no workflow-phase term, and
  // before publish EVERY assignment is 'planned' — so every card showed a
  // "Publish Hub" button instead of "Publish Crew". Hub-ness is a property of
  // the truck; the backend now sends it as one.
  const hubTruckIds: Set<string> = new Set(
    (dispatchData?.truck_assignments || [])
      .filter((a: any) => a.is_hub)
      .map((a: any) => a.truck_id)
  );

  // Trucks that already have an assignment for selectedDate (to exclude from hub modal picker)
  const assignedTruckIds: Set<string> = new Set(
    Object.keys(dispatchData?.assigned_crews || {})
  );

  return (
    <div /* No animate-slide-up here: the tab shell above already wraps this, and
       replaying the entrance animation on every tab switch is distracting. */
      className="space-y-6">
      <div className="flex flex-col gap-4">
        {/* Row 1 — title + refresh */}
        <div className="flex items-center gap-3">
          <div>
            <h1 className="page-title">Dispatch Center</h1>
            <p className="text-subtle mt-1">Manage and assign daily routes</p>
          </div>
          <button
            onClick={() => { fetchDispatchData(); fetchAvailablePool(); fetchUnavailableStaff(); fetchEmergencyPool(); fetchConfirmations(); }}
            disabled={isLoading}
            className="btn-ghost text-muted-foreground hover:text-foreground disabled:opacity-40"
            title="Refresh dispatch data"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Row 2 — inputs + admin clear */}
        <div className="flex flex-wrap items-center gap-3">
          {/* ADR-202: pick the exact trucks to dispatch; count is derived. */}
          <TruckPicker
            trucks={trucks}
            selected={selectedTruckIds}
            onToggle={(id) => setSelectedTruckIds(prev => {
              const next = new Set(prev);
              next.has(id) ? next.delete(id) : next.add(id);
              return next;
            })}
            onSelectAll={(ids) => setSelectedTruckIds(new Set(ids))}
            onClear={() => setSelectedTruckIds(new Set())}
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
          <div className="flex items-center gap-1.5">
            {/* Today is stated, not chosen — see selectedDate above. */}
            <span className="rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm text-foreground">
              {selectedDate}
            </span>
            {companyTimezone && (
              <span className="text-xs text-muted-foreground whitespace-nowrap">({companyTimezone})</span>
            )}
          </div>
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
            disabled={isLoading || workflowStep !== 'none'}
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
            disabled={isPublishing || isLoading || workflowStep !== 'dispatched'}
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
            disabled={isFinalizing || isLoading || workflowStep !== 'published' || confirmationGate.block}
            className="bg-info text-white hover:bg-info/90 px-4 py-2 rounded-lg font-medium transition-colors shadow-sm flex items-center gap-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            title={confirmationGate.block
              ? 'Blocked — under 50% confirmed on at least one truck'
              : 'Post confirmed crew lists to each truck channel and #drivers-chat'}
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

      {/* Finalize gate (post-publish): explains why Post Final Crews is blocked or
          needs confirmation, with the low-confirmation trucks named (ADR-205). */}
      {(confirmationGate.block || confirmationGate.warn) && (
        <div className={`rounded-lg border p-3 flex items-start gap-3 ${
          confirmationGate.block
            ? 'border-danger/50 bg-danger/10 text-danger'
            : 'border-warning/50 bg-warning/10 text-warning'
        }`}>
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            {confirmationGate.block ? (
              <p className="font-medium">
                <span className="font-semibold">Post Final Crews is blocked</span> — under 50% confirmed on{' '}
                {confirmationGate.below50.map(t => `${t.name} (${t.confirmed}/${t.total})`).join(', ')}.
                Wait for more confirmations or check that notifications went out.
              </p>
            ) : (
              <p className="font-medium">
                <span className="font-semibold">Low confirmations</span> — under 80% on{' '}
                {confirmationGate.below80.map(t => `${t.name} (${t.confirmed}/${t.total})`).join(', ')}.
                You can still post final crews, but you'll be asked to confirm.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ADR-256 D3 — captainless trucks after finalize.
          Separate from the warnings block below, and above it: this one reports a
          crew that has ALREADY been posted to Discord, so it needs to survive being
          skimmed past in a list of pre-dispatch advisories. */}
      {captainlessTrucks.length > 0 && (
        <div className="card space-y-2 border-warning border mb-4 bg-warning/5">
          <h3 className="font-semibold text-warning flex items-center gap-2 text-sm uppercase tracking-wide">
            <AlertCircle className="w-4 h-4" />
            No captain on {captainlessTrucks.length} truck
            {captainlessTrucks.length > 1 ? 's' : ''}
          </h3>
          <p className="text-sm text-warning pl-1">
            Crews were posted anyway. Assign a captain, or elevate an unpaired trainer:{' '}
            <span className="font-semibold">{captainlessTrucks.join(', ')}</span>
          </p>
          <button
            type="button"
            onClick={() => setCaptainlessTrucks([])}
            className="text-xs underline text-warning/80 hover:text-warning"
          >
            Dismiss
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

        </div>
      )}

      {/* ADR-264 — driver trainees held out of crews.

          Its OWN block, not nested in the warnings card, for the same reason
          the emergency pool below is not: this must render whether or not a
          warning fired. A held-out trainee has no AssignmentMember row, so they
          appear on no truck — if this block is gated on something else, they
          are simply absent from the day and nobody can tell they were
          scheduled.

          The dispatcher acts from HERE: drag them onto a truck to pair them
          with that truck's driver, or approve a solo day. */}
      {(dispatchData?.unpaired_driver_trainees?.length ?? 0) > 0 && (
        <div className="card space-y-3 border-warning border mb-4 bg-warning/5">
          <h3 className="font-semibold text-warning flex items-center gap-2 text-sm uppercase tracking-wide">
            <AlertCircle className="w-4 h-4" />
            Driver trainees needing a supervisor ({dispatchData!.unpaired_driver_trainees!.length})
          </h3>
          {/* No sourceTruckId on drag: they are on no truck, so a drop is an
              ASSIGN rather than a swap. */}
          <ul className="space-y-2">
            {dispatchData!.unpaired_driver_trainees!.map(t => (
              <li
                key={t.employee_id}
                draggable={!isLoading}
                onDragStart={(e) => handleDragStart(e, t.employee_id)}
                className="flex items-center justify-between gap-3 bg-background border border-border rounded p-2 cursor-grab active:cursor-grabbing"
              >
                <div className="min-w-0">
                  <p className="font-medium text-sm truncate">{t.employee_name}</p>
                  <p className="text-[10px] text-subtle uppercase tracking-wider">
                    driver trainee &middot;{' '}
                    {t.reason === 'first_day'
                      ? 'first supervised day'
                      : 'usual supervisor is out'}
                  </p>
                </div>
                <span className="text-[10px] text-subtle shrink-0">
                  drag to a truck to pair
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Emergency pool (ADR-267) — its OWN block, deliberately not nested in
          the warnings card. It used to live inside, which meant it inherited
          `warnings.length > 0` on top of its own trigger: three declines with
          no warning fired rendered nothing at all. That over-gating is the very
          thing this feature was built to fix, so it must not depend on a
          warning existing. */}
      {showEmergencyPool && (
        <div className="card space-y-3 border-danger/40 border mb-4 bg-danger/[0.03]">
          <button
            onClick={() => setShowCallInList(p => !p)}
            className="w-full flex items-center gap-2 text-sm font-semibold text-foreground hover:text-danger transition-colors"
          >
            <Phone className="w-4 h-4 text-danger" />
            Emergency pool
            {declineBadge && (
              /* Composed from the roles that ACTUALLY declined. A static
                 "Driver/captain out" read as a lie when three walkers called
                 out, and told the dispatcher nothing about which hole to fill. */
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide ${
                criticalDecline ? 'bg-danger text-danger-foreground' : 'bg-warning/20 text-warning'
              }`}>
                {declineBadge}
              </span>
            )}
            <span className="ml-auto text-subtle">
              {showCallInList ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </span>
          </button>

          {showCallInList && (
            <div className="space-y-4">
              {/* ── Each decline is a GAP, with its own candidates ──────────
                  The flat list put the person who called out next to an "Add"
                  button, which reads as "re-add the person who just said no".
                  A decline is a hole to fill; the people who can fill it are
                  same-role staff who are off or unassigned. */}
              {declinedMembers.length > 0 && (
                <div className="space-y-3">
                  {declinedMembers.map((gap) => {
                    const role = slotRoleOf(gap.id) || gap.role;
                    const critical = role === 'driver' || role === 'captain';
                    const candidates = emergencyPool.filter(
                      (m) => m.reason !== 'declined' && m.role === role,
                    );
                    return (
                      <div
                        key={gap.id}
                        className={`rounded-lg border ${critical ? 'border-danger/50' : 'border-border'} overflow-hidden`}
                      >
                        {/* The gap itself */}
                        <div className={`px-3 py-2 ${critical ? 'bg-danger/10' : 'bg-warning/10'}`}>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide ${
                              critical ? 'bg-danger text-danger-foreground' : 'bg-warning/25 text-warning'
                            }`}>
                              {role} out
                            </span>
                            <p className="text-sm font-medium text-foreground">{gap.name}</p>
                            <span className="text-xs text-subtle">declined</span>
                            <div className="ml-auto">
                              <ContactActions member={gap} />
                            </div>
                          </div>
                          <p className="text-[11px] text-subtle mt-1">
                            Try them first — a decline is often negotiable. If not, pick a
                            replacement below.
                          </p>
                        </div>

                        {/* Same-role replacements */}
                        <div className="px-3 py-2 space-y-1.5 bg-card">
                          {candidates.length === 0 ? (
                            <p className="text-xs text-warning flex items-center gap-1">
                              <AlertCircle className="w-3 h-3 shrink-0" />
                              No other {role} is contactable for this date.
                            </p>
                          ) : (
                            <>
                              <p className="text-[10px] font-bold uppercase tracking-widest text-subtle">
                                Suggested {role}s ({candidates.length})
                              </p>
                              {candidates.map((c) => (
                                <PoolRow
                                  key={c.id}
                                  member={c}
                                  adding={addingStaffId === c.id}
                                  onAdd={() => handleAddUnavailableStaff(c)}
                                  contacted={contactedIds.has(c.id)}
                                  onContact={() => setContactedIds(s => new Set(s).add(c.id))}
                                />
                              ))}
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* ── Everyone else, still available to call ─────────────────── */}
              {([
                ['scheduled_off', 'On a scheduled day off'],
                ['unassigned',    'Unassigned today'],
              ] as const).map(([reason, heading]) => {
                const group = emergencyPool.filter(m => m.reason === reason);
                if (group.length === 0) return null;
                return (
                  <div key={reason} className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-widest text-subtle">
                        {heading}
                      </span>
                      <span className="text-[10px] text-subtle">({group.length})</span>
                      <div className="h-px bg-border/60 flex-1" />
                    </div>
                    {group.map((member) => (
                      <PoolRow
                        key={member.id}
                        member={member}
                        adding={addingStaffId === member.id}
                        onAdd={() => handleAddUnavailableStaff(member)}
                        contacted={contactedIds.has(member.id)}
                        onContact={() => setContactedIds(s => new Set(s).add(member.id))}
                      />
                    ))}
                  </div>
                );
              })}
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
                      draggable={!isLoading}
                      onDragStart={(e) => handleDragStart(e, emp.id)}
                      className="group flex items-center gap-2 bg-accent/50 p-2 rounded border border-transparent hover:border-primary/30 cursor-grab active:cursor-grabbing"
                    >
                      <GripVertical className="w-4 h-4 text-muted-foreground shrink-0" />
                      <div className="overflow-hidden min-w-0 flex-1">
                        <p className="text-sm font-medium text-foreground truncate leading-tight">{emp.name}</p>
                        {/* No availability badge here. This pool comes from
                            /schedule/available, which excludes approved PTO and
                            recurring off-days by definition, so the non-available
                            branch could never render — dead code that implied a
                            state this list cannot contain. The badge is still
                            live on the truck-crew cards, where someone assigned
                            AND off is a real and useful signal (ADR-266 D5). */}
                        <p className="text-[10px] text-subtle uppercase tracking-wider truncate">{emp.role}</p>
                      </div>
                      <ContactPopover
                        employee={employees[emp.id] || emp}
                        name={emp.name}
                        role={emp.role}
                        status={availabilityOf(emp.id, unavailableStaff)}
                        open={contactFor === emp.id}
                        onToggle={() => openContact(emp.id)}
                      />
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
            {/* ALWAYS AVAILABLE (ADR-274). This was gated on
                `workflowStep !== 'none'`, i.e. only after dispatch had run —
                which fit ADR-125, where a hub was an intra-day addition to a
                RUNNING dispatch. Under ADR-274 a hub is its own truck that
                never joins dispatch at all, so on a fresh day the only control
                for creating one was invisible. A hub day should be creatable
                before, during or after the main dispatch. */}
            <button
              onClick={() => {
                setShowHubModal(true);
                /* A company has ONE hub in practice (7 delivery trucks to 1 hub
                   on staging). Preselect it: picking from a list of one is a
                   step whose answer is forced, and it left Create Hub disabled
                   on open. The name is shown in the modal, so nothing is
                   chosen invisibly. */
                setHubModalTruckId(availableHubs.length === 1 ? availableHubs[0].id : '');
              }}
              disabled={isLoading}
              className="flex items-center gap-1.5 text-sm font-medium bg-muted text-foreground hover:bg-muted/80 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed border border-border"
              title="Create a hub truck assignment for this date"
            >
              <Plus className="w-4 h-4" />
              Add Hub
            </button>
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
            <>
            {/* Rejections banner — only shown after publish when someone declined */}
            {workflowStep === 'published' && (() => {
              const declined = Object.entries(confirmations).filter(([, s]) => s === 'declined');
              if (declined.length === 0) return null;
              const declinedNames = declined.map(([empId]) => employees[empId]?.name || empId);
              return (
                <div className="mb-4 p-3 rounded-xl bg-danger/8 border border-danger/20 flex items-start gap-2">
                  <XCircle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-semibold text-danger">
                      {declined.length} rejection{declined.length > 1 ? 's' : ''} — reassignment needed
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {declinedNames.join(', ')}
                    </p>
                  </div>
                </div>
              );
            })()}
            {/* Confirm-all (ADR-274 D17). Publish applies unconfirmed suggestions
                anyway, so this is about making the decision explicit — one click
                instead of tabbing through every truck on a morning when nothing
                moved. Hidden when there is nothing left to confirm. */}
            {(() => {
              const pending = Object.keys(dispatchData.assigned_crews)
                .map(id => dockStateFor(id))
                .filter(d => d.suggested && d.value).length;
              if (pending === 0) return null;
              return (
                <div className="flex items-center justify-between gap-3 mb-3 px-3 py-2 rounded-xl border border-dashed border-border bg-surface-muted/30">
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{pending}</span>{' '}
                    dock zone{pending === 1 ? '' : 's'} suggested from each truck&apos;s last run.
                    They publish as-is — confirm to mark them checked.
                  </p>
                  <button
                    onClick={confirmAllSuggestedDocks}
                    disabled={dockSaving !== null}
                    className="shrink-0 flex items-center gap-1 text-[11px] font-semibold bg-primary/10 text-primary hover:bg-primary/20 px-2.5 py-1 rounded transition-colors disabled:opacity-50"
                  >
                    {dockSaving === '__all__'
                      ? <div className="w-3 h-3 border border-primary border-t-transparent rounded-full animate-spin" />
                      : <CheckCircle2 className="w-3 h-3" />}
                    Confirm all suggested
                  </button>
                </div>
              );
            })()}
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
               {Object.entries(dispatchData.assigned_crews).map(([truckId, crew]) => {
                 const isHub = hubTruckIds.has(truckId);
                 return (
                 <div
                   key={truckId}
                   className={`card-elevated border flex flex-col transition-colors min-h-[160px] ${isHub ? 'border-primary/40' : 'border-border'}`}
                   onDragOver={(e) => e.preventDefault()}
                   onDrop={(e) => handleDropToTruck(e, truckId)}
                 >
                   {/* Header wraps as a unit: identity on one line, actions
                       dropping to their own full-width line when the card is
                       narrow. Previously one non-wrapping row — at the 1- and
                       2-column breakpoints "Publish Hub" broke mid-phrase and
                       the count pill collapsed to a vertical "0 / 3". */}
                   <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 mb-3 pb-2 border-b border-border">
                     <div className="flex items-center gap-2 min-w-0">
                       <div className={`w-8 h-8 shrink-0 rounded flex items-center justify-center ${isHub ? 'bg-primary/20' : 'bg-primary/10'}`}>
                         <Truck className={`w-4 h-4 ${isHub ? 'text-primary' : 'text-primary'}`} />
                       </div>
                       <h3 className="font-semibold text-foreground text-sm uppercase tracking-wide truncate">
                         {trucks[truckId]?.name || `Truck ${truckId.substring(0,4)}`}
                       </h3>
                     </div>
                     {/* Right-hand group: crew count, then the HUB badge.
                         The badge sat next to the name, but the name is
                         left-justified in the row and the badge belongs with
                         the other card-level metadata rather than trailing the
                         title. */}
                     <div className="flex items-center gap-2 shrink-0 ml-auto">
                       {/* Crew COUNT, not a ratio — see the maxCrewSize note
                           above. Colour still carries the one fact that is
                           real: an empty crew needs attention.
                           whitespace-nowrap + shrink-0 because at the 1-column
                           breakpoint this used to wrap into a vertical stack. */}
                       <div
                         className={`shrink-0 whitespace-nowrap flex items-center gap-1 px-2 py-1 text-xs font-semibold rounded-full tabular-nums ${
                           (crew as any[]).length === 0
                             ? 'bg-warning/20 text-warning'
                             : 'bg-success/20 text-success'}`}
                         title={`${(crew as any[]).length} crew member${(crew as any[]).length === 1 ? '' : 's'} on this truck`}
                       >
                         <Users className="w-3 h-3" />
                         {(crew as any[]).length}
                       </div>
                       {isHub && (
                         <span className="shrink-0 text-[9px] font-bold uppercase tracking-widest text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                           Hub
                         </span>
                       )}
                     </div>
                   </div>

                   {/* Hub actions get their OWN row, so every card's header is
                       the same shape: name + count. Sharing the header with the
                       count pill made a hub card visibly denser than the regular
                       trucks beside it — three rows of chrome before any crew. */}
                   {isHub && (
                     <div className="flex items-center gap-2 mb-3">
                         <button
                           onClick={() => handlePublishHub(truckId)}
                           disabled={publishingHubTruckId === truckId || (crew as any[]).length === 0}
                           className="flex items-center gap-1 shrink-0 whitespace-nowrap text-[10px] font-semibold bg-success/15 text-success hover:bg-success/30 px-2 py-1 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                           title={crew.length === 0 ? 'Add staff before publishing' : 'Publish hub — notify all assigned staff'}
                         >
                           {publishingHubTruckId === truckId
                             ? <div className="w-3 h-3 border border-success border-t-transparent rounded-full animate-spin" />
                             : <Send className="w-3 h-3" />}
                           Publish Hub
                         </button>
                       {/* REMOVE — hubs only (ADR-274 D8). A hub is created one
                           at a time by hand, so it must be removable one at a
                           time; a mistake should not cost the whole day via
                           Clear Dispatch. Regular trucks have no equivalent:
                           they arrive as a balanced SET from Run Dispatch. */}
                         <button
                           onClick={() => handleRemoveHub(
                             truckId,
                             (crew as any[]).length,
                             (dispatchData?.truck_assignments || [])
                               .find((a: any) => a.truck_id === truckId)?.status !== 'planned',
                           )}
                           disabled={removingHubTruckId === truckId}
                           className="flex items-center gap-1 shrink-0 whitespace-nowrap text-[10px] font-semibold bg-danger/10 text-danger hover:bg-danger/25 px-2 py-1 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                           title="Remove this hub assignment"
                         >
                           {removingHubTruckId === truckId
                             ? <div className="w-3 h-3 border border-danger border-t-transparent rounded-full animate-spin" />
                             : <Trash2 className="w-3 h-3" />}
                           Remove
                         </button>
                     </div>
                   )}

                   {/* Dock zone (ADR-274 D17) — the bay this truck collects
                       from. Its OWN row, not wedged into the identity block:
                       it is an editable, savable field and was rendered at
                       w-20 / 11px beside a 9px label, smaller than the text
                       describing it, competing with the action buttons for the
                       header's horizontal space.
                       A value inherited from the truck's last run renders muted
                       until dispatch confirms or edits it; publish applies it
                       either way. */}
                   {(() => {
                     const d = dockStateFor(truckId);
                     const listId = `dock-opts-${truckId}`;
                     return (
                       <div className="flex items-center gap-2 mb-3">
                         <label
                           htmlFor={`dock-${truckId}`}
                           className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground shrink-0"
                         >
                           Dock
                         </label>
                         <div className="relative flex-1 min-w-0">
                           <input
                             id={`dock-${truckId}`}
                             list={listId}
                             value={d.value}
                             placeholder="set one…"
                             maxLength={50}
                             disabled={dockSaving !== null}
                             onChange={e => setDockDrafts(prev => ({ ...prev, [truckId]: e.target.value }))}
                             onBlur={e => {
                               const v = e.target.value.trim();
                               // Save an edited value, and also a suggestion the
                               // dispatcher tabbed through — touching the field is
                               // the confirmation.
                               if (truckId in dockDrafts || (d.suggested && v)) saveDockZone(truckId, v);
                             }}
                             onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                             className={`w-full h-8 pl-2.5 pr-7 text-xs font-mono rounded-lg border bg-background
                               transition-colors placeholder:text-muted-foreground
                               focus:outline-none focus:ring-2 focus:ring-ring focus:border-ring
                               disabled:opacity-60
                               ${d.suggested && d.value
                                 ? 'border-dashed border-primary/40 text-muted-foreground italic'
                                 : 'border-border text-foreground'}`}
                             title={d.suggested && d.value
                               ? `Suggested from this truck's last run — confirm or change it`
                               : 'Bay this truck collects from'}
                           />
                           {/* Inside the field, so it cannot be pushed onto a
                               second line the way a sibling flex child would. */}
                           {dockSaving === truckId && (
                             <div className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 border border-primary border-t-transparent rounded-full animate-spin" />
                           )}
                         </div>
                         <datalist id={listId}>
                           {(dockSuggest[truckId]?.recent ?? []).map(z => <option key={z} value={z} />)}
                         </datalist>
                       </div>
                     );
                   })()}

                   <div className="space-y-2 flex-1 relative">
                     {(() => {
                       const sortedCrew = [...crew].sort(sortCrewMembers);
                       // Trainers on THIS truck — the candidate list for a trainee's pairing picker (ADR-210).
                       /* Slot first (ADR-284): a trainer-titled employee
                          slotted as a walker on a hub supervises nobody. */
                       const truckTrainers = sortedCrew.filter(
                         (m: any) => (m.role || employees[m.employee_id]?.role || '').toLowerCase() === 'trainer',
                       );
                       return sortedCrew.map((member: any, index: number) => {
                         /* ADR-284 — the card shows the SLOT, so a captain
                            coerced on a hub reads under WALKERS, matching the
                            row the database actually holds. */
                         const currentRole = (member.role || employees[member.employee_id]?.role || 'walker').toLowerCase();
                         const prevMember = index > 0 ? sortedCrew[index - 1] : null;
                         const prevRole = prevMember ? (prevMember.role || employees[prevMember.employee_id]?.role || 'walker').toLowerCase() : '';
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
                               draggable={!isLoading}
                               onDragStart={(e) => handleDragStart(e, member.employee_id, truckId)}
                               onDragOver={(e) => { e.preventDefault(); }}
                               onDrop={(e) => {
                                 // Drop one person onto another → swap their trucks (ADR-210).
                                 e.preventDefault();
                                 e.stopPropagation();
                                 const draggedId = e.dataTransfer.getData('employeeId');
                                 const draggedTruck = e.dataTransfer.getData('sourceTruckId');
                                 if (!draggedId || draggedId === member.employee_id) return;
                                 if (!draggedTruck) {
                                   // From the unassigned panel → treat as a plain add to this truck.
                                   handleDropToTruck(e, truckId);
                                   return;
                                 }
                                 if (draggedTruck === truckId) return; // same truck, nothing to swap
                                 swapTwo(draggedId, draggedTruck, member.employee_id, truckId);
                               }}
                               /* Either overlay needs the card lifted above its
                                  siblings, or the popover renders behind the
                                  next crew member's card. */
                               className={`flex justify-between items-center group bg-background border border-border rounded p-2 cursor-grab active:cursor-grabbing shadow-sm drop-shadow-sm ${pairingFor === member.employee_id || contactFor === member.employee_id ? 'relative z-40' : ''}`}
                             >
                               <div className="flex items-center gap-2">
                                 <GripVertical className="w-4 h-4 text-muted-foreground opacity-30 group-hover:opacity-100" />
                                 <div>
                                   <p className="text-sm font-medium text-foreground leading-tight">{member.name || member.employee_id}</p>
                                   <div className="flex items-center gap-1.5">
                                     {/* The SLOT, not the job title (ADR-284):
                                         this line answers "what are they doing
                                         today", so a captain on a hub reads
                                         WALKER. ContactPopover below keeps the
                                         job title — it answers "who is this
                                         person", a different question. */}
                                     <p className="text-[10px] text-subtle uppercase tracking-wider">{member.role || employees[member.employee_id]?.role}</p>
                                     {currentRole === 'trainee' ? (() => {
                                       // Trainee pairing control (ADR-210): click to pick/switch/clear the trainer.
                                       const pairedName = member.paired_trainer_id
                                         ? (employees[member.paired_trainer_id]?.name
                                            || sortedCrew.find((m: any) => m.employee_id === member.paired_trainer_id)?.name
                                            || 'trainer')
                                         : null;
                                       const open = pairingFor === member.employee_id;
                                       return (
                                         <span className="relative">
                                           <button
                                             onPointerDown={(e) => e.stopPropagation()}
                                             onClick={() => setPairingFor(open ? null : member.employee_id)}
                                             className={`text-[9px] font-bold px-1 py-0.5 rounded tracking-wide ${
                                               pairedName ? 'bg-info/15 text-info hover:bg-info/30' : 'bg-warning/20 text-warning hover:bg-warning/40'
                                             } transition-colors`}
                                             title={pairedName ? 'Paired trainer — click to switch' : 'No trainer — click to assign'}
                                           >
                                             {pairedName ? `⇄ ${pairedName}` : '⚠ No trainer'}
                                           </button>
                                           {open && (
                                             <div onPointerDown={(e) => e.stopPropagation()}
                                               className="absolute z-30 top-full left-0 mt-1 w-44 bg-card border border-border rounded-md shadow-lg py-1 text-left">
                                               <p className="text-[9px] uppercase tracking-wider text-subtle px-2 pb-1">Assign trainer</p>
                                               {truckTrainers.length === 0 && (
                                                 <p className="text-[10px] text-muted-foreground px-2 py-1">No trainers on this truck</p>
                                               )}
                                               {truckTrainers.map((t: any) => (
                                                 <button
                                                   key={t.employee_id}
                                                   disabled={savingPairing}
                                                   onClick={() => setPairing(member.employee_id, t.employee_id)}
                                                   className={`w-full text-left text-[11px] px-2 py-1 hover:bg-accent transition-colors ${
                                                     member.paired_trainer_id === t.employee_id ? 'text-info font-semibold' : 'text-foreground'
                                                   }`}
                                                 >
                                                   {member.paired_trainer_id === t.employee_id ? '✓ ' : ''}{t.name || t.employee_id}
                                                 </button>
                                               ))}
                                               {member.paired_trainer_id && (
                                                 <button
                                                   disabled={savingPairing}
                                                   onClick={() => setPairing(member.employee_id, null)}
                                                   className="w-full text-left text-[11px] px-2 py-1 text-danger hover:bg-danger/10 transition-colors border-t border-border mt-1"
                                                 >
                                                   Clear pairing
                                                 </button>
                                               )}
                                             </div>
                                           )}
                                         </span>
                                       );
                                     })() : member.paired_trainer_id && (
                                       <span
                                         className="text-[9px] font-bold bg-info/15 text-info px-1 py-0.5 rounded tracking-wide"
                                         title="Paired trainee for today"
                                       >
                                         ⇄ {employees[member.paired_trainer_id]?.name
                                           || sortedCrew.find((m: any) => m.employee_id === member.paired_trainer_id)?.name
                                           || 'trainer'}
                                       </span>
                                     )}
                                     {transfers[member.employee_id] && (
                                       <span className="text-[9px] font-bold bg-warning/15 text-warning px-1 py-0.5 rounded uppercase tracking-wide" title={`Transferred to ${transfers[member.employee_id].to_truck_name}`}>
                                         ↗ {transfers[member.employee_id].to_truck_name}
                                       </span>
                                     )}
                                     {/* Assigned but off (ADR-266): PTO or a scheduled
                                         day off on someone already placed on a truck is
                                         a real dispatch problem, so it is drawn on the
                                         card rather than left to the call-in list.
                                         "Available" is not drawn — it is the norm here. */}
                                     {availabilityOf(member.employee_id, unavailableStaff) !== 'available' && (
                                       <span
                                         className={`${AVAILABILITY[availabilityOf(member.employee_id, unavailableStaff)].cls} text-[9px]`}
                                         title={AVAILABILITY[availabilityOf(member.employee_id, unavailableStaff)].title}
                                       >
                                         {AVAILABILITY[availabilityOf(member.employee_id, unavailableStaff)].label}
                                       </span>
                                     )}
                                   </div>
                                 </div>
                               </div>
                               <div className="flex items-center gap-1">
                                 <ContactPopover
                                   employee={employees[member.employee_id]}
                                   name={member.name || member.employee_id}
                                   role={employees[member.employee_id]?.role || member.role}
                                   status={availabilityOf(member.employee_id, unavailableStaff)}
                                   open={contactFor === member.employee_id}
                                   onToggle={() => openContact(member.employee_id)}
                                 />
                                 {(() => {
                                   const conf = confirmations[member.employee_id];
                                   if (conf === 'confirmed') return <CheckCircle2 className="w-4 h-4 text-success" aria-label="Confirmed" />;
                                   if (conf === 'declined')  return <XCircle className="w-4 h-4 text-danger" aria-label="Declined" />;
                                   if (conf === 'pending' && isAdmin && workflowStep === 'published') {
                                     return (
                                       <button
                                         onClick={() => handleConfirmEmployee(member.employee_id)}
                                         disabled={confirmingEmployee === member.employee_id}
                                         className="flex items-center gap-1 text-[10px] font-semibold bg-warning/15 text-warning hover:bg-warning/30 px-1.5 py-0.5 rounded transition-colors disabled:opacity-50"
                                         title="Confirm on behalf of employee"
                                       >
                                         {confirmingEmployee === member.employee_id
                                           ? <div className="w-3 h-3 border border-warning border-t-transparent rounded-full animate-spin" />
                                           : <Clock className="w-3 h-3" />}
                                         Confirm
                                       </button>
                                     );
                                   }
                                   if (conf === 'pending') return <Clock className="w-4 h-4 text-warning" aria-label="Pending confirmation" />;
                                   return null;
                                 })()}
                                 {(workflowStep === 'published' || workflowStep === 'finalized') && (
                                   <button
                                     onClick={() => {
                                       setTransferModal({ employeeId: member.employee_id, employeeName: member.name || member.employee_id });
                                       setTransferDestTruckId('');
                                       setTransferNote('');
                                       setTransferWarnings([]);
                                     }}
                                     className="text-muted-foreground hover:text-warning p-1 opacity-40 hover:opacity-100 transition-opacity"
                                     title="Transfer to another truck"
                                   >
                                     <ArrowRightLeft className="w-4 h-4" />
                                   </button>
                                 )}
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
               );
               })}

               {Object.keys(dispatchData.assigned_crews).length === 0 && (
                 <p className="text-sm text-subtle col-span-full text-center py-8">No trucks have valid configurations today.</p>
               )}
            </div>
            </>
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

      {/* Transfer modal */}
      {transferModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background rounded-2xl shadow-xl w-full max-w-sm mx-4 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-foreground flex items-center gap-2">
                <ArrowRightLeft className="w-4 h-4 text-warning" />
                Transfer {transferModal.employeeName}
              </h2>
              <button onClick={() => setTransferModal(null)} className="text-muted-foreground hover:text-foreground">
                ✕
              </button>
            </div>

            <p className="text-xs text-subtle">
              The employee will be transferred to the selected truck. A Discord channel swap and in-app notification will fire immediately.
              Their original assignment record is preserved.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">Destination Truck</label>
                <select
                  value={transferDestTruckId}
                  onChange={e => setTransferDestTruckId(e.target.value)}
                  className="w-full border border-input rounded-xl px-3 py-2 text-sm bg-background focus:ring-1 focus:ring-primary focus:border-primary outline-none"
                >
                  <option value="">Select a truck…</option>
                  {Object.entries(trucks)
                    .filter(([tid]) => tid !== Object.entries(dispatchData?.assigned_crews ?? {}).find(([, crew]) => crew.some((m: any) => m.employee_id === transferModal.employeeId))?.[0])
                    .map(([tid, t]: [string, any]) => (
                      <option key={tid} value={tid}>{t.name}</option>
                    ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">Note (optional)</label>
                <input
                  type="text"
                  value={transferNote}
                  onChange={e => setTransferNote(e.target.value)}
                  placeholder="e.g. Extra help needed on heavy route"
                  className="w-full border border-input rounded-xl px-3 py-2 text-sm bg-background focus:ring-1 focus:ring-primary focus:border-primary outline-none"
                />
              </div>
            </div>

            {transferWarnings.length > 0 && (
              <div className="space-y-1">
                {transferWarnings.map((w, i) => (
                  <p key={i} className="text-xs text-warning bg-warning/10 rounded-lg px-3 py-1.5">{w}</p>
                ))}
              </div>
            )}

            <div className="flex gap-2 pt-1">
              <button onClick={() => setTransferModal(null)} className="btn-ghost flex-1 text-sm py-2">Cancel</button>
              <button
                onClick={handleTransfer}
                disabled={isTransferring || !transferDestTruckId}
                className="btn-primary flex-1 text-sm py-2 flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {isTransferring && <div className="w-3.5 h-3.5 border border-white border-t-transparent rounded-full animate-spin" />}
                {isTransferring ? 'Transferring…' : 'Transfer'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Hub modal */}
      {showHubModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background rounded-2xl shadow-xl w-full max-w-sm mx-4 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-foreground flex items-center gap-2">
                <Plus className="w-4 h-4 text-primary" />
                Add Hub
              </h2>
              <button onClick={() => setShowHubModal(false)} className="text-muted-foreground hover:text-foreground">
                ✕
              </button>
            </div>
            {/* Two sentences, one idea each: what this does, then what YOU do
                next. The single paragraph ran the two together and buried the
                part the dispatcher acts on. */}
            <p className="text-xs text-subtle leading-relaxed">
              Creates a hub assignment for <strong>{selectedDate}</strong>.
              <br />
              Hub crew is never assigned automatically — drag staff onto the hub,
              then <strong>Publish Hub</strong> to notify them.
            </p>
            {/* Selectable cards, not a native <select>. A company has one hub
                in practice, so the dropdown was a picker over a single item —
                it covered the Create button when open, showed "Choose a hub…"
                with a checkmark as though it were a real choice, and left the
                primary action disabled until you interacted with it.

                The three empty states below are unchanged in meaning: "no
                options" has three causes and a silently empty control explains
                none of them. */}
            {availableHubs.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-2">
                  {availableHubs.length === 1 ? 'Hub' : 'Select a hub'}
                </p>
                <div className="space-y-2">
                  {availableHubs.map(h => {
                    const selected = hubModalTruckId === h.id;
                    return (
                      <button
                        key={h.id}
                        type="button"
                        onClick={() => setHubModalTruckId(h.id)}
                        aria-pressed={selected}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-left
                          transition-colors focus:outline-none focus:ring-2 focus:ring-ring
                          ${selected
                            ? 'border-primary bg-primary/5'
                            : 'border-border bg-background hover:bg-muted/50'}`}
                      >
                        <span className={`w-8 h-8 shrink-0 rounded flex items-center justify-center
                          ${selected ? 'bg-primary/20' : 'bg-muted'}`}>
                          <Truck className={`w-4 h-4 ${selected ? 'text-primary' : 'text-muted-foreground'}`} />
                        </span>
                        <span className="font-semibold text-sm uppercase tracking-wide truncate">
                          {h.name}
                        </span>
                        {selected && (
                          <CheckCircle2 className="w-4 h-4 text-primary ml-auto shrink-0" />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {!anyHubsConfigured ? (
              <p className="text-xs text-warning">
                No hub trucks configured. Create one on the Trucks page with
                &ldquo;Hub truck&rdquo; ticked, and set its Discord channel there.
              </p>
            ) : availableHubs.length === 0 ? (
              <p className="text-xs text-warning">
                Every hub already has an assignment for this date.
              </p>
            ) : null}

            <div className="flex gap-2 pt-1">
              <button onClick={() => setShowHubModal(false)} className="btn-ghost flex-1 text-sm py-2">Cancel</button>
              <button
                onClick={handleAddHub}
                disabled={isCreatingHub || !hubModalTruckId}
                className="btn-primary flex-1 text-sm py-2 flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {isCreatingHub && <div className="w-3.5 h-3.5 border border-white border-t-transparent rounded-full animate-spin" />}
                {isCreatingHub ? 'Creating…' : 'Create Hub'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* The contact channels for one pool member (ADR-267).

   Chips, not text: this surface exists to get someone on the phone, and a
   number you have to select-and-copy is not an affordance. `onUse` fires when
   any channel is actually clicked — that is what unlocks Add on a row. */
function ContactActions({
  member, onUse,
}: {
  member: EmergencyPoolMember;
  onUse?: () => void;
}) {
  const none = !member.phone_number && !member.email && !member.discord_id;
  if (none) {
    return (
      <span className="text-xs text-warning flex items-center gap-1">
        <AlertCircle className="w-3 h-3 shrink-0" />
        No contact details
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 flex-wrap">
      {member.phone_number && (
        <a
          href={`tel:${member.phone_number}`}
          onClick={onUse}
          className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md bg-success/10 text-success hover:bg-success/20 transition-colors"
        >
          <Phone className="w-3 h-3" />
          {member.phone_number}
        </a>
      )}
      {member.email && (
        <a
          href={`mailto:${member.email}`}
          onClick={onUse}
          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-muted text-foreground hover:bg-accent transition-colors max-w-[14rem]"
        >
          <Mail className="w-3 h-3 shrink-0" />
          <span className="truncate">{member.email}</span>
        </a>
      )}
      {member.discord_id && (
        <a
          href={`discord://-/users/${member.discord_id}`}
          onClick={onUse}
          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-info/10 text-info hover:bg-info/20 transition-colors"
          title="Open Discord DM"
        >
          @{member.discord_name || member.discord_id}
        </a>
      )}
    </span>
  );
}

/* One contactable person, with Add gated behind Contact (ADR-267).

   Adding someone who is off — or who just declined — without speaking to them
   first schedules a shift they never agreed to. So Contact is the primary
   action and Add stays disabled until a channel has been used; a person with
   no contact details on file can still be added, because there is no call to
   make and blocking would strand the dispatcher. */
function PoolRow({
  member, adding, onAdd, contacted, onContact,
}: {
  member: EmergencyPoolMember;
  adding: boolean;
  onAdd: () => void;
  contacted: boolean;
  onContact: () => void;
}) {
  const reachable = Boolean(member.phone_number || member.email || member.discord_id);
  const canAdd = contacted || !reachable;
  return (
    <div className="flex items-center gap-3 rounded-md bg-background border border-border px-2.5 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm text-foreground">{member.name}</p>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-subtle uppercase tracking-wide">
            {member.role}
          </span>
          {member.reason === 'scheduled_off' && (
            <span className="text-[10px] text-subtle">day off</span>
          )}
        </div>
        <div className="mt-1">
          <ContactActions member={member} onUse={onContact} />
        </div>
      </div>
      <button
        onClick={onAdd}
        disabled={adding || !canAdd}
        title={canAdd ? 'Add to dispatch' : 'Contact them first'}
        className={`shrink-0 flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-md transition-colors ${
          canAdd
            ? 'bg-primary text-primary-foreground hover:bg-primary/90'
            : 'border border-border text-subtle cursor-not-allowed'
        } disabled:opacity-60`}
      >
        {adding ? (
          <div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
        ) : (
          <Plus className="w-3 h-3" />
        )}
        Add
      </button>
    </div>
  );
}

/* Contact + availability for one employee (ADR-266).
   Shared by the unassigned pool and the truck crew list so the two cannot
   drift. Renders the trigger AND the popover, because the trigger has to stop
   pointerdown from reaching the draggable card — putting that guard in one
   place is the whole reason this is a component. */
function ContactPopover({
  employee, name, role, status, open, onToggle,
}: {
  employee: any;                      // EmployeeResponse row, may be undefined
  name: string;
  role: string;
  status: AvailabilityKey;
  open: boolean;
  onToggle: () => void;
}) {
  const phone: string | null = employee?.phone_number || null;
  const email: string | null = employee?.email || null;
  const s = AVAILABILITY[status];
  const btnRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  /* Positioned against the VIEWPORT and rendered through a PORTAL.

     Two separate ancestor problems force this, and each defeats a simpler fix:

     1. `overflow` — the unassigned pool is `max-h-[300px] overflow-y-auto`, so
        an absolutely-positioned child is clipped by it. The first attempt
        rendered with its left edge and bottom sheared off.

     2. `filter` — the crew card carries `drop-shadow-sm`, and a filtered
        ancestor becomes the CONTAINING BLOCK for `position: fixed`
        descendants. So `fixed` alone was not enough: the coordinates resolved
        against the card instead of the viewport and the panel landed
        thousands of pixels off-screen (measured: top 5348 for a button at
        y≈700).

     A portal to <body> escapes both — no clipping ancestor, and `fixed`
     resolves against the viewport as intended. Everything else is unchanged:
     the panel closes on scroll because it still does not travel with the
     card. */
  useEffect(() => {
    if (!open || !btnRef.current) { setPos(null); return; }
    const r = btnRef.current.getBoundingClientRect();
    const W = 224;                                   // w-56
    const H = 150;                                   // approx; only used to flip
    const left = Math.min(Math.max(8, r.right - W), window.innerWidth - W - 8);
    const below = r.bottom + 6;
    // Flip above when there is not room below, so the panel is never cut off
    // by the bottom of the window.
    const top = below + H > window.innerHeight ? Math.max(8, r.top - H - 6) : below;
    setPos({ top, left });
  }, [open]);

  return (
    <span className="shrink-0">
      <button
        ref={btnRef}
        type="button"
        /* The card is draggable: a pointerdown reaching it starts a drag, so
           the trigger must swallow it. Same guard the pairing button uses. */
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        aria-label={`Contact details for ${name}`}
        aria-expanded={open}
        className="p-0.5 rounded text-muted-foreground opacity-40 hover:opacity-100 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary transition-opacity"
        title="Contact details"
      >
        <Info className="w-3.5 h-3.5" />
      </button>

      {open && pos && createPortal(
        <div
          onPointerDown={(e) => e.stopPropagation()}
          style={{ top: pos.top, left: pos.left }}
          className="fixed z-50 w-56 bg-card border border-border rounded-md shadow-lg p-2.5 text-left"
        >
          <p className="text-sm font-semibold text-foreground leading-tight truncate">{name}</p>
          <p className="text-[10px] text-subtle uppercase tracking-wider mb-1.5">{role}</p>

          <span className={`${s.cls} text-[10px]`} title={s.title}>{s.label}</span>

          <div className="mt-2 pt-2 border-t border-border space-y-1.5">
            {phone && (
              /* tel:/mailto: rather than plain text — dispatch is often on a
                 laptop with a softphone, and copying a number by hand during a
                 shift is the friction this feature exists to remove. */
              <a
                href={`tel:${phone}`}
                className="flex items-center gap-1.5 text-xs text-foreground hover:text-primary transition-colors"
              >
                <Phone className="w-3 h-3 shrink-0 text-muted-foreground" />
                <span className="truncate">{phone}</span>
              </a>
            )}
            {email && (
              <a
                href={`mailto:${email}`}
                className="flex items-center gap-1.5 text-xs text-foreground hover:text-primary transition-colors"
              >
                <Mail className="w-3 h-3 shrink-0 text-muted-foreground" />
                <span className="truncate">{email}</span>
              </a>
            )}
            {!phone && !email && (
              /* Both fields are Optional server-side. Saying so beats an empty
                 box that reads as a loading failure. */
              <p className="text-xs text-subtle italic">No contact details on file</p>
            )}
          </div>
        </div>,
        document.body,
      )}
    </span>
  );
}

// ADR-202: multi-select of the trucks to dispatch. The count is derived from the
// selection (no separate number input). Only active trucks are selectable.
function TruckPicker({
  trucks, selected, onToggle, onSelectAll, onClear,
}: {
  trucks: Record<string, any>;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onSelectAll: (ids: string[]) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  // HUBS ARE NOT DISPATCHABLE (ADR-274 D2). run_dispatch excludes them and the
  // assign endpoint rejects them, so offering one here only produced "One or
  // more selected trucks are not available for your company" and blocked the
  // whole run — the backend was fixed without the picker being fixed with it.
  //
  // A hub gets its day through "+ Add Hub", which creates the assignment
  // directly; crew is then dragged on by hand.
  const active = Object.values(trucks)
    .filter((t: any) => t.is_active !== false && !t.is_hub)
    .sort((a: any, b: any) => (a.name || '').localeCompare(b.name || ''));
  const allIds = active.map((t: any) => t.id);

  // Close the dropdown on outside click or Escape (it overlays the Run button).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm hover:border-primary outline-none"
      >
        <Truck className="w-4 h-4 text-muted-foreground" />
        {selected.size > 0
          ? <span className="font-medium">{selected.size} truck{selected.size === 1 ? '' : 's'} selected</span>
          : <span className="text-muted-foreground">Select trucks…</span>}
        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-64 max-h-72 overflow-auto rounded-lg border border-border bg-card shadow-lg">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border text-xs">
            <button className="font-medium text-primary hover:underline" onClick={() => onSelectAll(allIds)}>Select all</button>
            <button className="text-muted-foreground hover:underline" onClick={onClear}>Clear</button>
          </div>
          {active.length === 0 ? (
            <p className="px-3 py-3 text-xs text-muted-foreground">No active trucks.</p>
          ) : active.map((t: any) => (
            <label key={t.id} className="flex items-center gap-2 px-3 py-2 hover:bg-accent/40 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={selected.has(t.id)}
                onChange={() => onToggle(t.id)}
                className="accent-primary"
              />
              <span className="truncate">{t.name}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
