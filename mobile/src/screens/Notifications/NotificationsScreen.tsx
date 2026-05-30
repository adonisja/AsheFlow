import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  View, Text, FlatList, StyleSheet, TouchableOpacity,
  ActivityIndicator, RefreshControl, Modal, Pressable, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '@contexts/AuthContext';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

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
  dispatch_assignment:            { label: 'Assignment',        icon: '📋' },
  trainer_decline_reassignment:   { label: 'Reassignment',      icon: '🔀' },
  trainee_unassigned:             { label: 'Unassigned',        icon: '⚠️' },
  graduation:                     { label: 'Graduation',        icon: '🎓' },
  schedule_change:                { label: 'Schedule Change',   icon: '📅' },
  schedule_change_approved:       { label: 'Schedule Approved', icon: '✅' },
  schedule_change_denied:         { label: 'Schedule Denied',   icon: '❌' },
  incident:                       { label: 'Incident',          icon: '🚨' },
  anchor_point_submitted:         { label: 'Anchor Point',      icon: '📍' },
  anchor_point_arrived:           { label: 'AP Arrival',        icon: '📍' },
  anchor_point_confirmed:         { label: 'AP Confirmed',      icon: '📍' },
};

function typeMeta(type: string): { label: string; icon: string } {
  if (TYPE_META[type]) return TYPE_META[type];
  // Convert snake_case to Title Case as fallback
  const label = type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return { label, icon: '🔔' };
}

function typeColor(type: string, c: ThemeColors): string {
  if (type === 'dispatch_assignment')              return c.primary;
  if (type === 'trainer_decline_reassignment')     return c.warning;
  if (type === 'trainee_unassigned')               return c.danger;
  if (type === 'graduation')                       return c.success;
  if (type === 'incident')                         return c.danger;
  if (type === 'schedule_change_approved')         return c.success;
  if (type === 'schedule_change_denied')           return c.danger;
  if (type.includes('schedule'))                   return c.info;
  if (type.includes('anchor_point'))               return c.gold;
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

// ── Dispatch Confirmation Modal ───────────────────────────────────────────────

type DispatchModalProps = {
  notif: Notification | null;
  userId: string;
  onClose: () => void;
  onResponded: (notifId: string) => void;
  c: ThemeColors;
};

function DispatchConfirmationModal({ notif, userId, onClose, onResponded, c }: DispatchModalProps) {
  const [status,  setStatus]  = useState<ConfirmationStatus>(null);
  const [loading, setLoading] = useState(true);
  const [acting,  setActing]  = useState<'confirming' | 'declining' | null>(null);
  const submitting = useRef(false);

  useEffect(() => {
    if (!notif?.dispatch_date) return;
    setLoading(true);
    setStatus(null);
    apiClient.get(`/dispatch/${notif.dispatch_date}/my-confirmation`)
      .then(r => setStatus(r.data.status ?? null))
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  }, [notif?.id, notif?.dispatch_date]);

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
      setStatus(choice);
      onResponded(notif.id);
      Alert.alert(
        choice === 'confirmed' ? 'Confirmed ✓' : 'Declined',
        choice === 'confirmed'
          ? 'Your assignment has been confirmed.'
          : 'Your assignment has been declined. Dispatch has been notified.',
        [{ text: 'OK', onPress: onClose }],
      );
    } catch (e: any) {
      Alert.alert('Error', e.response?.data?.detail ?? 'Could not record your response. Try again.');
    } finally {
      setActing(null);
      submitting.current = false;
    }
  }, [notif, userId, onClose, onResponded]);

  const ms = modalStyles(c);

  const StatusBadge = () => {
    if (status === 'confirmed') return (
      <View style={[ms.statusBadge, { backgroundColor: c.success + '15', borderColor: c.success + '40' }]}>
        <Text style={{ fontSize: 18 }}>✅</Text>
        <View>
          <Text style={[ms.statusTitle, { color: c.success }]}>Assignment Confirmed</Text>
          <Text style={[ms.statusSub, { color: c.mutedForeground }]}>Your response has been recorded</Text>
        </View>
      </View>
    );
    if (status === 'declined') return (
      <View style={[ms.statusBadge, { backgroundColor: c.danger + '10', borderColor: c.danger + '30' }]}>
        <Text style={{ fontSize: 18 }}>❌</Text>
        <View>
          <Text style={[ms.statusTitle, { color: c.danger }]}>Assignment Declined</Text>
          <Text style={[ms.statusSub, { color: c.mutedForeground }]}>Contact dispatch if this was a mistake</Text>
        </View>
      </View>
    );
    return null;
  };

  const dateLabel = notif?.dispatch_date
    ? new Date(notif.dispatch_date + 'T12:00:00').toLocaleDateString('en-US', {
        weekday: 'long', month: 'long', day: 'numeric',
      })
    : '';

  return (
    <Modal visible={!!notif} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={ms.backdrop} onPress={onClose} />
      <View style={[ms.sheet, { backgroundColor: c.card }]}>
        <View style={[ms.handle, { backgroundColor: c.border }]} />

        <View style={ms.sheetHeader}>
          <View style={[ms.sheetIcon, { backgroundColor: c.primary + '15' }]}>
            <Text style={{ fontSize: 22 }}>📋</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[ms.sheetTitle, { color: c.foreground }]}>Dispatch Assignment</Text>
            {dateLabel ? <Text style={[ms.sheetDate, { color: c.mutedForeground }]}>{dateLabel}</Text> : null}
          </View>
        </View>

        {notif?.message ? (
          <View style={[ms.messageBox, { backgroundColor: c.surfaceMuted, borderColor: c.border }]}>
            <Text style={[ms.messageText, { color: c.foreground }]}>{stripMarkdown(notif.message)}</Text>
          </View>
        ) : null}

        {loading ? (
          <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.lg }} />
        ) : (
          <>
            <StatusBadge />

            {(status === 'pending' || status === null) && (
              <View style={ms.actionRow}>
                <TouchableOpacity
                  onPress={() => respond('declined')}
                  disabled={!!acting}
                  style={[ms.btn, ms.btnDecline, { opacity: acting === 'confirming' ? 0.35 : 1 }]}>
                  {acting === 'declining'
                    ? <ActivityIndicator size="small" color={c.danger} />
                    : <Text style={[ms.btnText, { color: c.danger }]}>Decline</Text>
                  }
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => respond('confirmed')}
                  disabled={!!acting}
                  style={[ms.btn, ms.btnConfirm, { backgroundColor: c.success, opacity: acting === 'declining' ? 0.35 : 1 }]}>
                  {acting === 'confirming'
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={[ms.btnText, { color: '#fff' }]}>Confirm Attendance</Text>
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
  backdrop:    { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)' },
  sheet:       {
    borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl,
    padding: spacing.lg, paddingBottom: spacing.xl + 16, gap: spacing.sm,
  },
  handle:      { width: 36, height: 4, borderRadius: 2, alignSelf: 'center', marginBottom: spacing.md },
  sheetHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.xs },
  sheetIcon:   { width: 44, height: 44, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  sheetTitle:  { fontSize: fontSize.base, fontWeight: fontWeight.bold },
  sheetDate:   { fontSize: fontSize.xs, marginTop: 2 },
  messageBox:  {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    marginBottom: spacing.xs,
  },
  messageText: { fontSize: fontSize.sm, lineHeight: 22 },
  statusBadge: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    marginTop: spacing.xs,
  },
  statusTitle: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  statusSub:   { fontSize: fontSize.xs, marginTop: 2 },
  actionRow:   { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  btn:         {
    paddingVertical: spacing.sm + 4, borderRadius: radius.md,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1.5,
  },
  btnDecline:  { flex: 1, borderColor: c.danger, backgroundColor: c.danger + '08' },
  btnConfirm:  { flex: 2, borderColor: c.success },
  btnText:     { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  closeBtn:    { marginTop: spacing.xs, paddingVertical: spacing.sm + 2, borderRadius: radius.md, borderWidth: 1, alignItems: 'center' },
  closeBtnText:{ fontSize: fontSize.sm },
});

// ── Main Screen ───────────────────────────────────────────────────────────────

export default function NotificationsScreen() {
  const c = useColors();
  const { user } = useAuth();

  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [refreshing,    setRefreshing]    = useState(false);
  const [markingAll,    setMarkingAll]    = useState(false);
  const [activeNotif,   setActiveNotif]   = useState<Notification | null>(null);

  const fetchNotifications = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res = await apiClient.get(`/notifications/${user.id}?limit=50`);
      setNotifications(res.data ?? []);
    } catch {
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

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
    if (!user?.id) return;
    setMarkingAll(true);
    try {
      await apiClient.patch(`/notifications/employee/${user.id}/read-all`);
      setNotifications(prev =>
        prev.map(n => n.type === 'dispatch_assignment' ? n : { ...n, is_read: true })
      );
    } catch { /* no-op */ }
    finally { setMarkingAll(false); }
  }, [user?.id]);

  const handleTap = useCallback((item: Notification) => {
    if (item.type === 'dispatch_assignment' && item.dispatch_date) {
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

  const renderItem = ({ item, index }: { item: Notification; index: number }) => {
    const meta      = typeMeta(item.type);
    const accent    = typeColor(item.type, c);
    const isDispatch = item.type === 'dispatch_assignment';
    const isFirst   = index === 0;
    const isLast    = index === notifications.length - 1;

    return (
      <TouchableOpacity
        style={[
          s.row,
          isFirst  && s.rowFirst,
          isLast   && s.rowLast,
          !isLast  && s.rowDivider,
          !item.is_read && { backgroundColor: accent + '06' },
        ]}
        onPress={() => handleTap(item)}
        activeOpacity={0.65}
      >
        {/* Unread indicator strip */}
        {!item.is_read && (
          <View style={[s.unreadStrip, { backgroundColor: accent }]} />
        )}

        {/* Icon bubble */}
        <View style={[s.iconBubble, { backgroundColor: accent + '15' }]}>
          <Text style={s.iconText}>{meta.icon}</Text>
        </View>

        {/* Content */}
        <View style={s.rowContent}>
          <View style={s.rowTop}>
            <Text style={[s.typeLabel, { color: accent }]}>{meta.label}</Text>
            <Text style={[s.timeText, { color: c.mutedForeground }]}>{formatRelative(item.created_at)}</Text>
          </View>
          <Text style={[s.messageText, { color: item.is_read ? c.mutedForeground : c.foreground }]}
            numberOfLines={2}>
            {stripMarkdown(item.message)}
          </Text>
          {isDispatch && item.dispatch_date && (
            <Text style={[s.tapHint, { color: c.primary }]}>Tap to view assignment →</Text>
          )}
        </View>

        {/* Unread dot */}
        {!item.is_read && !isDispatch && (
          <View style={[s.dot, { backgroundColor: accent }]} />
        )}
      </TouchableOpacity>
    );
  };

  // Group rows in a single rounded container like iOS Settings
  const grouped = notifications.length > 0;

  return (
    <SafeAreaView style={[s.safe, { backgroundColor: c.background }]} edges={['top']}>
      {/* Header */}
      <View style={[s.header, { borderBottomColor: c.border }]}>
        <View>
          <Text style={[s.pageTitle, { color: c.foreground }]}>Notifications</Text>
          {unreadCount > 0 && (
            <Text style={[s.unreadLabel, { color: c.mutedForeground }]}>
              {unreadCount} unread
            </Text>
          )}
        </View>
        {unreadCount > 0 && (
          <TouchableOpacity onPress={markAllRead} disabled={markingAll} style={s.markAllBtn}>
            {markingAll
              ? <ActivityIndicator color={c.primary} size="small" />
              : <Text style={[s.markAllText, { color: c.primary }]}>Mark all read</Text>
            }
          </TouchableOpacity>
        )}
      </View>

      {loading ? (
        <View style={s.center}><ActivityIndicator color={c.primary} size="large" /></View>
      ) : (
        <FlatList
          data={notifications}
          keyExtractor={item => item.id}
          renderItem={renderItem}
          contentContainerStyle={[s.list, grouped && s.listGrouped]}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />
          }
          ListHeaderComponent={grouped ? (
            // Wrap in a container — the rows themselves form one group card
            null
          ) : null}
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
        userId={user?.id ?? ''}
        onClose={() => setActiveNotif(null)}
        onResponded={handleResponded}
        c={c}
      />
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:         { flex: 1 },
  header:       {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end',
    paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  pageTitle:    { fontSize: fontSize.xl, fontWeight: fontWeight.bold, letterSpacing: -0.3 },
  unreadLabel:  { fontSize: fontSize.xs, marginTop: 2 },
  markAllBtn:   { paddingBottom: 2 },
  markAllText:  { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  center:       { flex: 1, justifyContent: 'center', alignItems: 'center' },

  list:         { paddingBottom: 80 },
  listGrouped:  { paddingHorizontal: spacing.md, paddingTop: spacing.md },

  // Rows form one grouped card (Settings-style)
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: c.card,
    paddingVertical: spacing.md,
    paddingRight: spacing.md,
    paddingLeft: spacing.sm,
    position: 'relative',
    overflow: 'hidden',
  },
  rowFirst:   { borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg },
  rowLast:    { borderBottomLeftRadius: radius.lg, borderBottomRightRadius: radius.lg },
  rowDivider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.border },

  unreadStrip:  { position: 'absolute', left: 0, top: 0, bottom: 0, width: 3 },
  iconBubble:   { width: 40, height: 40, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  iconText:     { fontSize: 18 },

  rowContent:   { flex: 1, gap: 3 },
  rowTop:       { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  typeLabel:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.4 },
  timeText:     { fontSize: fontSize.xs },
  messageText:  { fontSize: fontSize.sm, lineHeight: 19 },
  tapHint:      { fontSize: fontSize.xs, fontWeight: fontWeight.medium, marginTop: 2 },
  dot:          { width: 8, height: 8, borderRadius: 4, flexShrink: 0, marginLeft: spacing.xs },

  // Empty state
  emptyCard:    { alignItems: 'center', marginTop: 80, gap: spacing.md },
  emptyIcon:    { width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center' },
  emptyTitle:   { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  emptySub:     { fontSize: fontSize.sm },
});
