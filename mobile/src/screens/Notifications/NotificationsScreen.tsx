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
import { NotificationTicker } from '@components/notifications/NotificationTicker';
import {
  isTicker, isUrgent, toneStyle, urgentStyle,
  type NotificationSeverity, type NotificationTone,
} from '@components/notifications/tone';

type Notification = {
  id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
  dispatch_date: string | null;

  /** Resolved from the server's registry per read, not stored (ADR-487 D4).
   *
   *  Optional because a row delivered by an older server build has none, and
   *  because this surface has no codegen — `types.ts` is hand-maintained, so a
   *  field the server sends and this file does not declare is invisible to TS.
   *  Every consumer below falls back, so an older build degrades to the
   *  previous behaviour rather than rendering blank. */
  severity?: NotificationSeverity;
  label?: string;
  tone?: NotificationTone;
  icon?: string;
  channels?: string[];
};

type ConfirmationStatus = 'pending' | 'confirmed' | 'declined' | null;

/**
 * Label and icon, from the SERVER (ADR-487 D4).
 *
 * This replaced two hardcoded tables that lived here: a 52-entry `TYPE_META`
 * and a `typeColor` chain of 20 string tests ending in
 * `type.includes('approved')`. Between them they covered 52 of the registry's
 * 86 types — the other 34 fell to a default by accident rather than decision —
 * and they DISAGREED with web for the same row from the same endpoint:
 * `incident_critical` was `c.danger` here and a warning tint there.
 *
 * The fallbacks are not decoration. Three types reaching this screen are
 * PlatformAlert vocabulary with no registry entry (ADR-324 D2 keeps the two
 * apart because a super admin has no Employee row), and a row written before
 * ADR-487 shipped has no server fields at all. Both render as a neutral bell
 * with a title-cased type, which is exactly what the old default did.
 */
function labelFor(n: Notification): string {
  if (n.label) return n.label;
  return n.type.replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
}

function iconFor(n: Notification): string {
  return n.icon || '🔔';
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

function DispatchConfirmationModal({ notif, userId, onClose, onResponded, c }: DispatchModalProps) {
  const [status,         setStatus]         = useState<ConfirmationStatus>(null);
  const [dispatchPhase,  setDispatchPhase]  = useState<'planned' | 'active' | 'completed' | null>(null);
  const [truckName,      setTruckName]      = useState<string | null>(null);
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
        setTruckName(mine.truckName);

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
  // ADR-332 D2 — the real name from the payload. The regex this replaced
  // parsed the notification MESSAGE and rendered "Truck the" against
  // "assigned to the hub (Atlas)".

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

  /* ADR-487 D4 — route by what the SERVER says, three groups:
   *
   *   urgent  — its own region, pinned ABOVE the scroll (D4a)
   *   ticker  — events with no consequence for the reader (D4b)
   *   inbox   — everything else: cards, as today
   *
   * Severity is NOT the ticker test. 52 types are INFO and only 20 carry
   * 'ticker'; `pto_approved` is INFO and must not scroll past, because it is a
   * decision about the reader's own time off. That is why the server sends
   * `channels`.
   *
   * ACTION stays in the inbox rather than being hoisted: a dispatch_assignment
   * awaiting confirm/decline already has its own CTA on the card, and the modal
   * is the blocking surface for it. URGENT is different — it needs no answer
   * from the reader, it needs to be impossible to miss. */
  const urgent = notifications.filter(n => isUrgent(n.severity));
  const rest   = notifications.filter(n => !isUrgent(n.severity));
  const ticker = rest.filter(n => isTicker(n.channels));
  const inbox  = rest.filter(n => !isTicker(n.channels));

  const s = styles(c);

  const renderItem = ({ item }: { item: Notification }) => {
    // The server's tone, mapped to THIS surface's theme values. Web maps the
    // same tone to Tailwind classes — which is why the server sends a semantic
    // role and not a colour.
    const t           = toneStyle(item.tone ?? 'neutral', c);
    const accent      = t.text;
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
            <Text style={s.iconText}>{iconFor(item)}</Text>
          </View>

          {/* Body */}
          <View style={s.body}>
            {/* Top row: label + time */}
            <View style={s.topRow}>
              <View style={[s.typePill, { backgroundColor: accent + '18' }]}>
                <Text style={[s.typeLabel, { color: accent }]}>{labelFor(item)}</Text>
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
        <>
          {/* URGENT — OUTSIDE the FlatList, so it cannot be scrolled away.
              ADR-487 D4a: the web cap works by scrolling its contents and a
              FlatList does the same, so "render it above" means outside the
              scrolling element, not merely first in its data. A sibling of the
              list, not its ListHeaderComponent, which scrolls with the rows.

              Not a live region: it is a card the reader is meant to ACT on,
              not an announcement to interrupt them with. */}
          {urgent.length > 0 && (
            <View style={s.urgentRegion}>
              {urgent.map(item => {
                const u = urgentStyle(c);
                return (
                  <TouchableOpacity
                    key={item.id}
                    style={[s.urgentCard, {
                      backgroundColor: u.bg,
                      borderColor: u.border,
                      borderLeftWidth: u.barWidth,
                      borderLeftColor: u.border,
                    }]}
                    onPress={() => handleTap(item)}
                    activeOpacity={0.7}
                  >
                    <Text style={s.urgentIcon}>{iconFor(item)}</Text>
                    <View style={s.urgentBody}>
                      <Text style={[s.urgentLabel, { color: u.text }]}>
                        {labelFor(item)}
                      </Text>
                      <Text style={[s.urgentMessage, { color: c.foreground }]}>
                        {stripMarkdown(item.message)}
                      </Text>
                    </View>
                  </TouchableOpacity>
                );
              })}
            </View>
          )}

          <FlatList
            data={inbox}
            keyExtractor={item => item.id}
            renderItem={renderItem}
            contentContainerStyle={s.list}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />}
            /* The ticker is the LOWEST-consequence group, so it is the one that
               may scroll out of view. Long-press clears the strip: these are
               acknowledgements rather than decisions, and a dismiss control per
               item would be more chrome than content on a 32pt row. */
            ListFooterComponent={
              ticker.length > 0
                ? <View style={s.tickerSlot}>
                    <NotificationTicker
                      items={ticker.map(n => ({
                        id: n.id, message: stripMarkdown(n.message),
                        icon: n.icon, label: n.label,
                      }))}
                      onDismissAll={() => { void markAllRead(); }}
                    />
                  </View>
                : null
            }
            ListEmptyComponent={
              /* Only when there is NOTHING at all. "All caught up" beneath an
                 injury alert or a scrolling ticker would be a lie. */
              urgent.length === 0 && ticker.length === 0 ? (
                <View style={s.emptyCard}>
                  <View style={[s.emptyIcon, { backgroundColor: c.surfaceMuted }]}>
                    <Text style={{ fontSize: 32 }}>🔔</Text>
                  </View>
                  <Text style={[s.emptyTitle, { color: c.foreground }]}>All caught up</Text>
                  <Text style={[s.emptySub, { color: c.mutedForeground }]}>No notifications yet</Text>
                </View>
              ) : null
            }
          />
        </>
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

  // ADR-487 D4a — the URGENT region. Outside the FlatList, so it cannot be
  // scrolled away. Colours come from `urgentStyle`, not from here: the shape is
  // layout and the palette is the server's tone mapped to this theme.
  urgentRegion: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    gap: spacing.sm,
  },
  urgentCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    // borderLeftWidth is set inline from urgentStyle().barWidth — a thick bar
    // rather than only a tint, because ADR-487 D4a rejected "the registry tone
    // alone": colour alone fails for a dispatcher whose eyes are on a truck
    // list, and fails outright for anyone with a colour-vision deficiency.
  },
  urgentIcon:    { fontSize: fontSize.lg, marginTop: 1 },
  urgentBody:    { flex: 1, gap: 2 },
  urgentLabel:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  urgentMessage: { fontSize: fontSize.sm },

  // The ticker sits at the bottom of the list, inside the scroll: it is the
  // lowest-consequence group, so it is the one that may scroll out of view.
  tickerSlot: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
});
