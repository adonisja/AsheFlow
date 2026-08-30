import React, { useEffect, useState, useCallback, useRef } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, FlatList, StyleSheet, TouchableOpacity,
  ActivityIndicator, RefreshControl, Modal, Pressable, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '@contexts/AuthContext';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { useTabSwitch } from '@navigation/index';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { useMyTruck } from '../../hooks/useMyTruck';

type Notification = {
  id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
  dispatch_date: string | null;
};

type ConfirmationStatus = 'pending' | 'confirmed' | 'declined' | null;

// Human-readable label + icon per notification type
const TYPE_META: Record<string, { label: string; icon: string }> = {
  dispatch_assignment:            { label: 'Assignment',         icon: '📋' },
  dispatch_assignment_info:       { label: 'Assignment Update',  icon: '📋' },
  trainer_decline_reassignment:   { label: 'Reassignment',       icon: '🔀' },
  trainee_unassigned:             { label: 'Unassigned',         icon: '⚠️' },
  graduation:                     { label: 'Graduation',         icon: '🎓' },
  trainee_graduated:              { label: 'Graduation',         icon: '🎓' },
  trainee_reset:                  { label: 'Training Reset',     icon: '🔄' },
  schedule_change:                { label: 'Schedule Change',    icon: '📅' },
  schedule_change_approved:       { label: 'Schedule Approved',  icon: '✅' },
  schedule_change_denied:         { label: 'Schedule Denied',    icon: '❌' },
  schedule_change_rejected:       { label: 'Schedule Denied',    icon: '❌' },
  schedule_change_request:        { label: 'Schedule Request',   icon: '📅' },
  incident_info:                  { label: 'Incident',           icon: '🚨' },
  incident_warning:               { label: 'Incident Warning',   icon: '⚠️' },
  incident_critical:              { label: 'Critical Incident',  icon: '🚨' },
  incident_submitted:             { label: 'Incident Filed',     icon: '📋' },
  incident_resolved:              { label: 'Incident Resolved',  icon: '✅' },
  anchor_point_submitted:         { label: 'Anchor Point',       icon: '📍' },
  anchor_point_arrived:           { label: 'AP Arrival',         icon: '📍' },
  anchor_point_departed:          { label: 'AP Departure',       icon: '📍' },
  anchor_point_running_late:      { label: 'Running Late',       icon: '⏰' },
  inspection_failed:              { label: 'Inspection Failed',  icon: '🚨' },
  rts_submitted:                  { label: 'RTS Submitted',      icon: '🏁' },
  rts_approved:                   { label: 'RTS Approved',       icon: '✅' },
  rts_rejected:                   { label: 'RTS Rejected',       icon: '❌' },
  rts_revised:                    { label: 'RTS Revised',        icon: '🔄' },
  training_phase_closed:          { label: 'Phase Complete',     icon: '📚' },
  phase4_failed:                  { label: 'Phase 4 Result',     icon: '📋' },
  underperforming_trainer:        { label: 'Trainer Alert',      icon: '⚠️' },
  exemplary_trainer:              { label: 'Trainer Noted',      icon: '⭐' },
  ban_override_reassignment:      { label: 'Override Notice',    icon: '🔀' },
  offday_approved:                { label: 'Day Off Approved',   icon: '✅' },
  offday_rejected:                { label: 'Day Off Denied',     icon: '❌' },
  pto_approved:                   { label: 'PTO Approved',       icon: '✅' },
  pto_rejected:                   { label: 'PTO Denied',         icon: '❌' },
  feedback_submitted:             { label: 'Feedback',           icon: '💬' },
  credentials_sent:               { label: 'Credentials',        icon: '🔑' },
  truck_transfer:                 { label: 'Truck Transfer',     icon: '🔀' },
  role_change:                    { label: 'Role Change',        icon: '⭐' },
  quiz_issued:                    { label: 'Quiz Ready',         icon: '📝' },
  quiz_submitted:                 { label: 'Quiz Submitted',     icon: '📝' },
  quiz_result_confirmed:          { label: 'Quiz Result',        icon: '📋' },
  trainee_reassign_warning:       { label: 'Reassign Warning',   icon: '⚠️' },
  continuation_request:           { label: 'Cont. Request',      icon: '🔁' },
  assignment_change_request:      { label: 'Reassign Request',   icon: '📋' },
  assignment_change_approved:     { label: 'Reassign Approved',  icon: '✅' },
  assignment_change_rejected:     { label: 'Reassign Denied',    icon: '❌' },
  driver_survey:                  { label: 'Driver Survey',      icon: '📊' },
};

function typeMeta(type: string): { label: string; icon: string } {
  if (TYPE_META[type]) return TYPE_META[type];
  // Convert snake_case to Title Case as fallback
  const label = type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return { label, icon: '🔔' };
}

function typeColor(type: string, c: ThemeColors): string {
  if (type === 'dispatch_assignment' || type === 'dispatch_assignment_info') return c.primary;
  if (type === 'credentials_sent')                             return c.info;
  if (type === 'truck_transfer')                               return c.warning;
  if (type === 'trainer_decline_reassignment')                 return c.warning;
  if (type === 'trainee_unassigned')                           return c.danger;
  if (type === 'trainee_graduated' || type === 'graduation')  return c.success;
  if (type === 'trainee_reset')                                return c.info;
  if (type === 'incident' || type === 'incident_resolved')     return c.danger;
  if (type === 'rts_approved')                                 return c.success;
  if (type === 'rts_rejected')                                 return c.danger;
  if (type === 'rts_submitted')                                return c.warning;
  if (type === 'training_phase_closed')                        return c.success;
  if (type === 'phase4_failed')                                return c.danger;
  if (type === 'underperforming_trainer')                      return c.danger;
  if (type === 'exemplary_trainer')                            return c.success;
  if (type.includes('approved') || type.includes('exemplary')) return c.success;
  if (type.includes('rejected') || type.includes('denied') || type.includes('failed')) return c.danger;
  if (type.includes('schedule'))                               return c.info;
  if (type.includes('anchor_point'))                           return c.gold;
  return c.info;
}

function stripMarkdown(text: string): string {
  return text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1');
}

function formatRelative(iso: string) {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1)  return 'Just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24)  return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return days === 1 ? 'Yesterday' : `${days}d ago`;
  } catch { return ''; }
}

// ── Confirmation status cache (30-second TTL, keyed by dispatch_date) ────────

type CacheEntry = { status: ConfirmationStatus; fetchedAt: number };
const confirmationCache = new Map<string, CacheEntry>();
const CACHE_TTL_MS = 30_000;

function getCached(date: string): ConfirmationStatus | undefined {
  const entry = confirmationCache.get(date);
  if (!entry) return undefined;
  if (Date.now() - entry.fetchedAt > CACHE_TTL_MS) {
    confirmationCache.delete(date);
    return undefined;
  }
  return entry.status;
}

function setCached(date: string, status: ConfirmationStatus) {
  confirmationCache.set(date, { status, fetchedAt: Date.now() });
}

function bustCache(date: string) {
  confirmationCache.delete(date);
}

// ── Dispatch Confirmation Modal ───────────────────────────────────────────────

type DispatchModalProps = {
  notif: Notification | null;
  userId: string;
  onClose: () => void;
  onResponded: (notifId: string) => void;
  c: ThemeColors;
};

function extractTruckName(message: string): string | null {
  const m = message.match(/\b([A-Z]{2,4}[-\s]?\d{1,4}[A-Z]?)\b/) ??
            message.match(/truck\s+([^\s,]+)/i) ??
            message.match(/assigned to\s+([^\s,.]+)/i);
  return m ? m[1] : null;
}

function DispatchConfirmationModal({ notif, userId, onClose, onResponded, c }: DispatchModalProps) {
  const [status,         setStatus]         = useState<ConfirmationStatus>(null);
  const [dispatchPhase,  setDispatchPhase]  = useState<'planned' | 'active' | 'completed' | null>(null);
  const [loading,        setLoading]        = useState(true);
  const [acting,         setActing]         = useState<'confirming' | 'declining' | null>(null);
  const submitting = useRef(false);

  useEffect(() => {
    if (!notif?.dispatch_date) return;
    setLoading(true);
    setStatus(null);
    setDispatchPhase(null);

    const cached = getCached(notif.dispatch_date);
    if (cached !== undefined) {
      setStatus(cached);
      // Phase is not cached — always fetch it fresh so stale 'active' doesn't show buttons post-finalize
    }

    Promise.allSettled([
      apiClient.get(`/dispatch/${notif.dispatch_date}/my-confirmation`),
      apiClient.get(`/dispatch/${notif.dispatch_date}`),
    ]).then(([confResult, dispatchResult]) => {
      if (confResult.status === 'fulfilled') {
        const s = confResult.value.data.status ?? null;
        setCached(notif.dispatch_date!, s);
        setStatus(s);
      } else if (cached !== undefined) {
        setStatus(cached);
      }

      if (dispatchResult.status === 'fulfilled') {
        // ADR-330 D1 — THIS member's truck, not the day.
        //
        // `workflow_status` is the day's furthest-along status: 'finalized' the
        // moment ANY truck completes. Reading it here closed the confirm window
        // on the phone of every crew member on every OTHER truck, and relabelled
        // them "No Response Recorded" — which reads as though they failed to
        // reply. Measured on staging: 19 Eagle crew locked out because Falcon
        // was finalized.
        //
        // TodayAssignmentScreen already does this correctly; so do FieldOps,
        // Reattempt, RouteSort and DriverSurvey. This screen was the one that
        // took the pre-aggregated field because it was already in the payload.
        const data = dispatchResult.value.data;
        // ADR-331 — one implementation of "which truck am I on". The hook
        // returns THIS truck's status and deliberately does not surface the
        // day's workflow_status, so the ADR-330 bug is unexpressible here.
        const mine = useMyTruck(data, userId);

        if (mine.status === 'completed') setDispatchPhase('completed');
        else if (mine.status === 'active') setDispatchPhase('active');
        else if (mine.status === 'planned') setDispatchPhase('planned');
        else {
          // ADR-330 D2 — the member's own truck could not be resolved.
          //
          // Two different unknowns, and they must not share a default:
          //
          //  * the DAY has no dispatch at all ('none', ADR-274) -> 'planned'.
          //    Nothing has been published, so there is nothing to confirm and
          //    "planned" is the honest state.
          //  * the day HAS dispatch but this member's truck is unresolvable
          //    (crew list still loading, member removed) -> 'active', i.e.
          //    leave the window OPEN.
          //
          // A wrong "closed" silently strips someone's ability to respond and
          // then labels them "No Response Recorded" — it blames them for the
          // bug. A wrong "open" shows a button that may 409: visible,
          // recoverable, honest. Asymmetric failure modes; default to the one
          // the user can recover from.
          const wf: string = data?.workflow_status ?? '';
          if (wf === 'none' || wf === '') setDispatchPhase('planned');
          else setDispatchPhase('active');
        }
      }
    }).finally(() => setLoading(false));
    // ADR-330 — userId is now read inside (to find the member's own truck), so
    // it belongs in the deps: without it a modal opened before the id resolves
    // keeps a phase derived from an empty userId and never recomputes.
  }, [notif?.id, notif?.dispatch_date, userId]);

  const respond = useCallback(async (choice: 'confirmed' | 'declined') => {
    if (!notif?.dispatch_date || submitting.current) return;
    submitting.current = true;
    setActing(choice === 'confirmed' ? 'confirming' : 'declining');
    try {
      await apiClient.post(`/dispatch/${notif.dispatch_date}/confirmations`, {
        employee_id: userId,
        status: choice,
      });
      await apiClient.patch(`/notifications/${notif.id}/read`);
      bustCache(notif.dispatch_date);
      setCached(notif.dispatch_date, choice);
      setStatus(choice);
      onResponded(notif.id);
      Alert.alert(
        choice === 'confirmed' ? 'Confirmed' : 'Declined',
        choice === 'confirmed'
          ? 'Your assignment has been confirmed.'
          : 'Your assignment has been declined. Dispatch has been notified.',
        [{ text: 'OK', onPress: onClose }],
      );
    } catch (e: unknown) {
      Alert.alert('Error', errorText(e, 'Could not record your response. Try again.'));
    } finally {
      setActing(null);
      submitting.current = false;
    }
  }, [notif, userId, onClose, onResponded]);

  const ms = modalStyles(c);

  const dateLabel = notif?.dispatch_date
    ? new Date(notif.dispatch_date + 'T12:00:00').toLocaleDateString('en-US', {
        weekday: 'long', month: 'long', day: 'numeric',
      })
    : '';

  const cleanMessage = notif?.message ? stripMarkdown(notif.message) : '';
  const truckName = cleanMessage ? extractTruckName(cleanMessage) : null;

  // The confirmation window is open only during the 'active' dispatch phase.
  // Past-date and finalized dispatches are read-only regardless of status.
  const localToday = new Date().toISOString().slice(0, 10);
  const isPastDate = !!notif?.dispatch_date && notif.dispatch_date < localToday;
  const isFinalized = dispatchPhase === 'completed';
  // dispatch_assignment_info is always informational — no action required
  const isInfoOnly = notif?.type === 'dispatch_assignment_info';

  // Derive accent color and status metadata from current status
  const statusAccent = status === 'confirmed' ? c.success
    : status === 'declined' ? c.danger
    : c.warning;

  const statusIcon = status === 'confirmed' ? '✅'
    : status === 'declined' ? '❌'
    : '⏳';

  const windowClosed = isPastDate || isFinalized;

  const statusLabel = status === 'confirmed' ? 'Confirmed'
    : status === 'declined' ? 'Declined'
    : windowClosed ? 'No Response Recorded'
    : 'Awaiting Response';

  const statusSub = status === 'confirmed' ? 'Your attendance was recorded'
    : status === 'declined' ? 'You declined this assignment'
    : isFinalized ? 'Final crews have been posted — this window is closed'
    : isPastDate ? 'This assignment has passed'
    : 'Please confirm or decline your assignment';

  // Show action buttons only when the window is open and no response has been submitted
  const needsAction = !isInfoOnly && !windowClosed && (status === 'pending' || status === null);

  return (
    <Modal visible={!!notif} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={ms.backdrop} onPress={onClose} />
      <View style={[ms.sheet, { backgroundColor: c.card }]}>

        {/* Status-colored top stripe */}
        {!loading && <View style={[ms.topStripe, { backgroundColor: statusAccent }]} />}

        <View style={[ms.handle, { backgroundColor: c.border }]} />

        {/* Header */}
        <View style={ms.sheetHeader}>
          <View style={[ms.sheetIcon, { backgroundColor: c.primary + '18' }]}>
            <Text style={{ fontSize: 24 }}>📋</Text>
          </View>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs }}>
              <Text style={[ms.sheetTitle, { color: c.foreground }]}>Dispatch Assignment</Text>
              {(isPastDate || isFinalized) && (
                <View style={[ms.pastPill, { backgroundColor: c.mutedForeground + '20' }]}>
                  <Text style={[ms.pastPillText, { color: c.mutedForeground }]}>
                    {isFinalized ? 'Finalized' : 'Past'}
                  </Text>
                </View>
              )}
            </View>
            {dateLabel ? <Text style={[ms.sheetDate, { color: c.mutedForeground }]}>{dateLabel}</Text> : null}
          </View>
        </View>

        {/* Truck name hero (when extractable) */}
        {truckName && (
          <View style={[ms.truckRow, { backgroundColor: c.primary + '10', borderColor: c.primary + '30' }]}>
            <Text style={{ fontSize: 16 }}>🚚</Text>
            <Text style={[ms.truckLabel, { color: c.primary }]}>Truck {truckName}</Text>
          </View>
        )}

        {/* Message box */}
        {notif?.message ? (
          <View style={[ms.messageBox, { backgroundColor: c.surfaceMuted, borderColor: c.border }]}>
            <Text style={[ms.messageText, { color: c.mutedForeground }]} numberOfLines={4}>
              {stripMarkdown(notif.message)}
            </Text>
          </View>
        ) : null}

        {/* Status / action area */}
        {loading ? (
          <View style={ms.loadingRow}>
            <ActivityIndicator color={c.primary} />
            <Text style={[ms.loadingText, { color: c.mutedForeground }]}>Checking status…</Text>
          </View>
        ) : (
          <>
            {/* Status badge — always shown */}
            <View style={[ms.statusBadge, {
              backgroundColor: statusAccent + '12',
              borderColor: statusAccent + '35',
            }]}>
              <Text style={ms.statusIcon}>{statusIcon}</Text>
              <View style={{ flex: 1 }}>
                <Text style={[ms.statusTitle, { color: statusAccent }]}>{statusLabel}</Text>
                <Text style={[ms.statusSub, { color: c.mutedForeground }]}>{statusSub}</Text>
              </View>
            </View>

            {/* Action buttons — only when no response yet */}
            {needsAction && (
              <View style={ms.actionRow}>
                <TouchableOpacity
                  onPress={() => respond('declined')}
                  disabled={!!acting}
                  style={[ms.btn, ms.btnDecline, {
                    borderColor: c.danger,
                    backgroundColor: c.danger + '08',
                    opacity: acting === 'confirming' ? 0.35 : 1,
                  }]}>
                  {acting === 'declining'
                    ? <ActivityIndicator size="small" color={c.danger} />
                    : <Text style={[ms.btnText, { color: c.danger }]}>Decline</Text>
                  }
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => respond('confirmed')}
                  disabled={!!acting}
                  style={[ms.btn, ms.btnConfirm, {
                    backgroundColor: c.success,
                    borderColor: c.success,
                    opacity: acting === 'declining' ? 0.35 : 1,
                  }]}>
                  {acting === 'confirming'
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={[ms.btnText, { color: c.primaryForeground }]}>Confirm Attendance</Text>
                  }
                </TouchableOpacity>
              </View>
            )}
          </>
        )}

        <TouchableOpacity onPress={onClose} style={[ms.closeBtn, { borderColor: c.border }]}>
          <Text style={[ms.closeBtnText, { color: c.mutedForeground }]}>Close</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

const modalStyles = (c: ThemeColors) => StyleSheet.create({
  backdrop:    { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' },
  sheet:       {
    borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl,
    overflow: 'hidden',
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xl + 16,
    gap: spacing.sm,
  },
  topStripe:   { height: 4, marginHorizontal: -spacing.lg },
  handle:      { width: 36, height: 4, borderRadius: 2, alignSelf: 'center', marginTop: spacing.sm, marginBottom: spacing.xs },
  sheetHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.xs },
  sheetIcon:   { width: 48, height: 48, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center' },
  sheetTitle:  { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  sheetDate:   { fontSize: fontSize.xs, marginTop: 2 },
  pastPill:    { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.sm },
  pastPillText:{ fontSize: 10, fontWeight: fontWeight.semibold, textTransform: 'uppercase' as const, letterSpacing: 0.4 },

  truckRow:    {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: radius.md, borderWidth: 1,
  },
  truckLabel:  { fontSize: fontSize.base, fontWeight: fontWeight.bold, letterSpacing: 0.3 },

  messageBox:  { padding: spacing.md, borderRadius: radius.md, borderWidth: 1 },
  messageText: { fontSize: fontSize.sm, lineHeight: 20 },

  loadingRow:  { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.md },
  loadingText: { fontSize: fontSize.sm },

  statusBadge: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.lg, borderWidth: 1,
  },
  statusIcon:  { fontSize: 22 },
  statusTitle: { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  statusSub:   { fontSize: fontSize.xs, marginTop: 2 },

  actionRow:   { flexDirection: 'row', gap: spacing.sm },
  btn:         {
    paddingVertical: spacing.sm + 6, borderRadius: radius.md,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1.5,
  },
  btnDecline:  { flex: 1 },
  btnConfirm:  { flex: 2 },
  btnText:     { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  closeBtn:    {
    marginTop: spacing.xs, paddingVertical: spacing.sm + 4,
    borderRadius: radius.md, borderWidth: 1, alignItems: 'center',
  },
  closeBtnText:{ fontSize: fontSize.sm },
});

// ── Main Screen ───────────────────────────────────────────────────────────────

export default function NotificationsScreen() {
  const c = useColors();
  const { user } = useAuth();
  const switchTab = useTabSwitch();

  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [refreshing,    setRefreshing]    = useState(false);
  const [markingAll,    setMarkingAll]    = useState(false);
  const [activeNotif,   setActiveNotif]   = useState<Notification | null>(null);

  const employeeDbId = useRef<string | null>(null);

  const resolveEmployeeId = useCallback(async (): Promise<string | null> => {
    if (employeeDbId.current) return employeeDbId.current;
    try {
      const res = await apiClient.get('/employees/me');
      employeeDbId.current = res.data.id;
      return res.data.id;
    } catch { return null; }
  }, []);

  const fetchNotifications = useCallback(async () => {
    const eid = await resolveEmployeeId();
    if (!eid) return;
    try {
      const res = await apiClient.get(`/notifications/${eid}?limit=50`);
      setNotifications(res.data ?? []);
    } catch {
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  }, [resolveEmployeeId]);

  useEffect(() => { fetchNotifications(); }, [fetchNotifications]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchNotifications();
    setRefreshing(false);
  }, [fetchNotifications]);

  const markAsRead = useCallback(async (id: string) => {
    try {
      await apiClient.patch(`/notifications/${id}/read`);
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
    } catch { /* no-op */ }
  }, []);

  const markAllRead = useCallback(async () => {
    const eid = employeeDbId.current;
    if (!eid) return;
    setMarkingAll(true);
    try {
      const res = await apiClient.patch(`/notifications/employee/${eid}/read-all`);
      // Server marks everything except assignments still awaiting a
      // Confirm/Decline (today/future) — mirror that locally.
      const today = new Date().toISOString().slice(0, 10);
      setNotifications(prev => prev.map(n =>
        n.type === 'dispatch_assignment' && (!n.dispatch_date || n.dispatch_date >= today)
          ? n
          : { ...n, is_read: true },
      ));
      const skipped = res.data?.skipped_actionable ?? 0;
      if (skipped > 0) {
        Alert.alert(
          'Almost all read',
          `${skipped} assignment notification${skipped === 1 ? '' : 's'} still need${skipped === 1 ? 's' : ''} a Confirm/Decline response — respond to clear ${skipped === 1 ? 'it' : 'them'}.`,
        );
      }
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not mark notifications read.'));
    }
    finally { setMarkingAll(false); }
  }, []);

  const handleTap = useCallback((item: Notification) => {
    if ((item.type === 'dispatch_assignment' || item.type === 'dispatch_assignment_info') && item.dispatch_date) {
      setActiveNotif(item);
    } else if (!item.is_read) {
      markAsRead(item.id);
    }
  }, [markAsRead]);

  const handleResponded = useCallback((notifId: string) => {
    setNotifications(prev => prev.map(n => n.id === notifId ? { ...n, is_read: true } : n));
  }, []);

  const unreadCount = notifications.filter(n => !n.is_read).length;
  const s = styles(c);

  const renderItem = ({ item }: { item: Notification }) => {
    const meta        = typeMeta(item.type);
    const accent      = typeColor(item.type, c);
    const isDispatch  = item.type === 'dispatch_assignment';
    const isInfoOnly  = item.type === 'dispatch_assignment_info';
    const unread      = !item.is_read;
    const isPast      = !!item.dispatch_date && item.dispatch_date < new Date().toISOString().slice(0, 10);

    return (
      <TouchableOpacity
        style={[
          s.card,
          unread
            ? { borderColor: accent + '50', backgroundColor: accent + '06' }
            : { borderColor: c.border, backgroundColor: c.card },
        ]}
        onPress={() => handleTap(item)}
        activeOpacity={0.7}
      >
        {/* Left accent stripe — only on unread */}
        {unread && <View style={[s.stripe, { backgroundColor: accent }]} />}

        <View style={s.cardInner}>
          {/* Icon */}
          <View style={[s.iconBubble, { backgroundColor: accent + (unread ? '20' : '12') }]}>
            <Text style={s.iconText}>{meta.icon}</Text>
          </View>

          {/* Body */}
          <View style={s.body}>
            {/* Top row: label + time */}
            <View style={s.topRow}>
              <View style={[s.typePill, { backgroundColor: accent + '18' }]}>
                <Text style={[s.typeLabel, { color: accent }]}>{meta.label}</Text>
              </View>
              <Text style={[s.timeText, { color: c.mutedForeground }]}>{formatRelative(item.created_at)}</Text>
            </View>

            {/* Message */}
            <Text
              style={[s.message, { color: unread ? c.foreground : c.mutedForeground,
                fontWeight: unread ? fontWeight.medium : fontWeight.regular }]}
              numberOfLines={2}
            >
              {stripMarkdown(item.message)}
            </Text>

            {/* Dispatch CTA */}
            {(isDispatch || isInfoOnly) && item.dispatch_date && (
              <View style={s.ctaRow}>
                <Text style={[s.cta, { color: isPast || isInfoOnly ? c.mutedForeground : c.primary }]}>
                  {isInfoOnly ? 'View assignment info →'
                    : isPast ? 'View past assignment →'
                    : 'View & respond to assignment →'}
                </Text>
              </View>
            )}
          </View>

          {/* Unread dot — right edge */}
          {unread && !isDispatch && !isInfoOnly && (
            <View style={[s.dot, { backgroundColor: accent }]} />
          )}
          {(isDispatch || isInfoOnly) && unread && (
            <View style={[s.dot, { backgroundColor: isInfoOnly ? c.primary : c.warning }]} />
          )}
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={s.safe} edges={['top']}>

      {/* ── Header ── */}
      <View style={s.header}>
        {/* Back */}
        <TouchableOpacity onPress={() => switchTab('Home')} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }} style={s.backBtn}>
          <Text style={[s.backChevron, { color: c.primary }]}>‹</Text>
        </TouchableOpacity>

        {/* Centred title + badge */}
        <View style={s.headerCenter}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs }}>
            <Text style={s.pageTitle}>Notifications</Text>
            {unreadCount > 0 && (
              <View style={[s.unreadBadge, { backgroundColor: c.danger }]}>
                <Text style={s.unreadBadgeText}>{unreadCount > 99 ? '99+' : unreadCount}</Text>
              </View>
            )}
          </View>
        </View>

        {/* Right action */}
        <View style={s.headerRight}>
          {unreadCount > 0 && (
            <TouchableOpacity onPress={markAllRead} disabled={markingAll}>
              {markingAll
                ? <ActivityIndicator color={c.primary} size="small" />
                : <Text style={[s.markAllText, { color: c.primary }]}>All read</Text>}
            </TouchableOpacity>
          )}
        </View>
      </View>

      {loading ? (
        <View style={s.center}><ActivityIndicator color={c.primary} size="large" /></View>
      ) : (
        <FlatList
          data={notifications}
          keyExtractor={item => item.id}
          renderItem={renderItem}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />}
          ListEmptyComponent={
            <View style={s.emptyCard}>
              <View style={[s.emptyIcon, { backgroundColor: c.surfaceMuted }]}>
                <Text style={{ fontSize: 32 }}>🔔</Text>
              </View>
              <Text style={[s.emptyTitle, { color: c.foreground }]}>All caught up</Text>
              <Text style={[s.emptySub, { color: c.mutedForeground }]}>No notifications yet</Text>
            </View>
          }
        />
      )}

      <DispatchConfirmationModal
        notif={activeNotif}
        userId={employeeDbId.current ?? ''}
        onClose={() => setActiveNotif(null)}
        onResponded={handleResponded}
        c={c}
      />
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:   { flex: 1, backgroundColor: c.background },

  // Header
  header: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: spacing.md, paddingTop: spacing.md, paddingBottom: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.border,
    backgroundColor: c.surface,
  },
  backBtn:         { width: 44, alignItems: 'center' },
  backChevron:     { fontSize: 30, lineHeight: 32, fontWeight: '300' },
  headerCenter:    { flex: 1, alignItems: 'center' },
  headerRight:     { width: 64, alignItems: 'flex-end' },
  pageTitle:       { fontSize: fontSize.xl, fontWeight: fontWeight.bold, color: c.foreground, letterSpacing: -0.3 },
  unreadBadge:     { minWidth: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6 },
  unreadBadgeText: { color: c.primaryForeground, fontSize: 11, fontWeight: fontWeight.bold },
  markAllText:     { fontSize: fontSize.xs, fontWeight: fontWeight.medium },
  center:          { flex: 1, justifyContent: 'center', alignItems: 'center' },

  list: { padding: spacing.md, paddingBottom: 80, gap: spacing.sm },

  // Individual notification card
  card: {
    borderRadius: radius.xl,
    borderWidth: 1,
    overflow: 'hidden',
  },
  stripe:    { height: 3 },
  cardInner: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, padding: spacing.md },
  iconBubble:{ width: 44, height: 44, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  iconText:  { fontSize: 20 },

  body:    { flex: 1, gap: 4 },
  topRow:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.xs },
  typePill:{ paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  typeLabel:{ fontSize: 10, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.5 },
  timeText: { fontSize: fontSize.xs, color: c.mutedForeground },
  message:  { fontSize: fontSize.sm, lineHeight: 20 },
  ctaRow:   { marginTop: 2 },
  cta:      { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  dot: { width: 9, height: 9, borderRadius: 5, flexShrink: 0, marginTop: 2 },

  // Empty state
  emptyCard:    { alignItems: 'center', marginTop: 80, gap: spacing.md },
  emptyIcon:    { width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center' },
  emptyTitle:   { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  emptySub:     { fontSize: fontSize.sm },
});
