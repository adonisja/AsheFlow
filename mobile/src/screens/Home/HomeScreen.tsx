import React, { useState, useCallback, useRef } from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { useAuth } from '@contexts/AuthContext';
import { useTabSwitch } from '@navigation/index';
// NOT from @navigation/index — that would be a require cycle (index imports
// this screen), which evaluates the constant as undefined and broke the
// role filter silently. See @navigation/roles.
import { FIELD_OPS_ROLES } from '@navigation/roles';
import { useColors } from '@contexts/ThemeContext';
import apiClient from '@api/client';
import {
  spacing, radius, fontSize, fontWeight,
  getRoleColor, getRoleLight, ROLE_LABELS, type ThemeColors,
} from '@theme/index';
import { Avatar, Skeleton } from '@components/ui/primitives';

function greet() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function formatTodayLong() {
  return new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
}

function stripMarkdown(text: string): string {
  return text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1');
}

function getInitials(name: string): string {
  const parts = name.trim().split(' ');
  if (parts.length === 1) return parts[0][0]?.toUpperCase() ?? '?';
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

const roleBadgeTone: Record<string, 'slate' | 'teal' | 'gold' | 'info' | 'neutral'> = {
  driver: 'slate', walker: 'teal', trainer: 'gold', trainee: 'info',
};

// Quick-action definitions — key matches tab key in navigation.
// `roles` must mirror the tab's role gate (navigation/index.tsx): a tile for
// a tab the role doesn't have silently no-ops on tap (Field Ops showed for
// trainers/trainees/walkers but only drivers have the tab).
const QUICK_ACTIONS: { key: string; label: string; icon: string; roles?: readonly string[] }[] = [
  { key: 'FieldOps',      label: 'Field Ops',    icon: '🔧', roles: FIELD_OPS_ROLES },
  { key: 'Schedule',      label: 'Schedule',     icon: '📅' },
  { key: 'Notifications', label: 'Inbox',        icon: '🔔' },
  { key: 'Account',       label: 'Account',      icon: '👤' },
];

export default function HomeScreen() {
  const c          = useColors();
  const { user }   = useAuth();
  const navigation = useNavigation<any>();
  const switchTab  = useTabSwitch();

  const today = localToday();

  const [truckName,  setTruckName]  = useState<string | null>(null);
  const [myRole,     setMyRole]     = useState<string | null>(null);
  const [crew,       setCrew]       = useState<{ id: string; name: string; role: string }[]>([]);
  const [assignLoad, setAssignLoad] = useState(true);

  const [unreadCount,   setUnreadCount]   = useState(0);
  const [latestMessage, setLatestMessage] = useState<string | null>(null);
  const [notifLoad,     setNotifLoad]     = useState(true);

  const [refreshing, setRefreshing] = useState(false);

  const employeeDbId = useRef<string | null>(null);

  const displayName = user?.firstName ?? user?.email?.split('@')[0] ?? 'Crew Member';
  const primaryRole = ['driver', 'trainer', 'trainee', 'walker'].find(r => user?.groups?.includes(r)) as string | undefined;
  const roleColor   = primaryRole ? getRoleColor(primaryRole as any, c) : c.primary;
  const roleLight   = primaryRole ? getRoleLight(primaryRole as any, c) : c.primaryLight;
  const initials    = getInitials(displayName);

  const resolveEmployeeId = useCallback(async (): Promise<string | null> => {
    if (employeeDbId.current) return employeeDbId.current;
    try {
      const res = await apiClient.get('/employees/me');
      employeeDbId.current = res.data.id;
      return res.data.id;
    } catch {
      return null;
    }
  }, []);

  const fetchAssignment = useCallback(async () => {
    try {
      // The eid resolve must live INSIDE try/finally — an early `return`
      // before it left the loading flag true forever (skeletons hung
      // indefinitely after navigating away and back).
      const eid = await resolveEmployeeId();
      if (!eid) { setTruckName(null); return; }
      const res   = await apiClient.get(`/schedule/${eid}?start_date=${today}&end_date=${today}`);
      const entry = (res.data ?? [])[0];
      if (!entry || entry.status !== 'Assigned' || !entry.truck_name) {
        setTruckName(null); setMyRole(null); setCrew([]);
        return;
      }
      const crewList = entry.crew ?? [];
      const me       = crewList.find((m: any) => m.id === eid);
      setTruckName(entry.truck_name);
      setMyRole(me?.role ?? null);
      setCrew(crewList);
    } catch {
      setTruckName(null);
    } finally {
      setAssignLoad(false);
    }
  }, [today, resolveEmployeeId]);

  const fetchNotifications = useCallback(async () => {
    try {
      const eid = await resolveEmployeeId();
      if (!eid) { setUnreadCount(0); return; }
      // limit must cover the whole unread set — counting within a 10-item
      // page showed "10 unread" while 14 existed.
      const res  = await apiClient.get(`/notifications/${eid}?limit=50`);
      const list: any[] = res.data ?? [];
      setUnreadCount(list.filter(n => !n.is_read).length);
      setLatestMessage(list[0]?.message ?? null);
    } catch {
      setUnreadCount(0);
    } finally {
      setNotifLoad(false);
    }
  }, [resolveEmployeeId]);

  // Refetch on every focus, not just mount — returning from the Notifications
  // screen (where items get read) must not leave a stale unread badge here.
  useFocusEffect(useCallback(() => {
    fetchAssignment();
    fetchNotifications();
  }, [fetchAssignment, fetchNotifications]));

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([fetchAssignment(), fetchNotifications()]);
    setRefreshing(false);
  }, [fetchAssignment, fetchNotifications]);

  const s = styles(c);

  // Crew initials to show in assignment card (max 4)
  const crewInitials = crew.slice(0, 4).map(m => ({
    initials: m.name.split(' ').map(p => p[0]).join('').toUpperCase().slice(0, 2),
    role: m.role,
  }));

  return (
    <SafeAreaView style={s.safe} edges={['top']}>

      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />}
      >

        {/* ── Hero card ── */}
        <View style={[s.hero, { backgroundColor: c.card, borderColor: c.border }]}>
          <TouchableOpacity onPress={() => navigation.navigate('Profile')} activeOpacity={0.8} style={s.heroAvatarWrap}>
            <View style={[s.heroAvatarRing, { borderColor: roleColor }]}>
              <Avatar initials={initials} role={primaryRole as any ?? 'driver'} size={80} />
            </View>
          </TouchableOpacity>
          <Text style={[s.heroDate, { color: c.mutedForeground }]}>{formatTodayLong()}</Text>
          <Text style={[s.heroGreet, { color: c.mutedForeground }]}>{greet()},</Text>
          <Text style={[s.heroName, { color: c.foreground }]}>{displayName}</Text>
          {primaryRole && (
            <View style={[s.heroRolePill, { backgroundColor: roleColor + '18', borderColor: roleColor + '35' }]}>
              <View style={[s.heroRoleDot, { backgroundColor: roleColor }]} />
              <Text style={[s.heroRoleText, { color: roleColor }]}>
                {ROLE_LABELS[primaryRole] ?? primaryRole}
              </Text>
            </View>
          )}
        </View>

        {/* ── Quick actions ── */}
        <View style={s.quickRow}>
          {QUICK_ACTIONS.filter(a =>
            !a.roles || a.roles.some(r => user?.groups?.includes(r)),
          ).map(action => (
            <TouchableOpacity
              key={action.key}
              style={[s.quickBtn, { backgroundColor: c.card, borderColor: c.border }]}
              onPress={() => switchTab(action.key)}
              activeOpacity={0.7}
            >
              <Text style={s.quickIcon}>{action.icon}</Text>
              <Text style={[s.quickLabel, { color: c.mutedForeground }]}>{action.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* ── Today's assignment ── */}
        <Text style={s.sectionLabel}>TODAY'S ASSIGNMENT</Text>
        <TouchableOpacity
          style={[s.assignCard, { backgroundColor: c.card, borderColor: truckName ? roleColor : c.border }]}
          onPress={() => navigation.navigate('TodayAssignment')}
          activeOpacity={0.75}
        >
          {/* Color accent stripe */}
          <View style={[s.assignStripe, { backgroundColor: truckName ? roleColor : c.surfaceMuted }]} />

          <View style={s.assignBody}>
            {/* Icon + truck info */}
            <View style={s.assignTop}>
              <View style={[s.assignIconWell, { backgroundColor: truckName ? roleLight : c.surfaceMuted }]}>
                <Text style={{ fontSize: 22 }}>🚚</Text>
              </View>
              <View style={{ flex: 1 }}>
                {assignLoad ? (
                  <>
                    <Skeleton width={80} height={11} style={{ marginBottom: 6 }} />
                    <Skeleton width={140} height={18} />
                  </>
                ) : truckName ? (
                  <>
                    <Text style={[s.assignEyebrow, { color: c.mutedForeground }]}>ASSIGNED TRUCK</Text>
                    <Text style={[s.assignTruck, { color: c.foreground }]}>{truckName}</Text>
                    {myRole && (
                      <View style={[s.rolePill, { backgroundColor: roleLight }]}>
                        <Text style={[s.rolePillText, { color: roleColor }]}>
                          {ROLE_LABELS[myRole] ?? myRole}
                        </Text>
                      </View>
                    )}
                  </>
                ) : (
                  <>
                    <Text style={[s.assignEyebrow, { color: c.mutedForeground }]}>TRUCK</Text>
                    <Text style={[s.assignEmpty, { color: c.mutedForeground }]}>No assignment today</Text>
                  </>
                )}
              </View>
              <Text style={[s.chevron, { color: c.subtleForeground }]}>›</Text>
            </View>

            {/* Crew row */}
            {truckName && crewInitials.length > 0 && (
              <View style={s.crewRow}>
                <View style={s.crewAvatars}>
                  {crewInitials.map((m, i) => (
                    <View
                      key={i}
                      style={[
                        s.crewAvatar,
                        { backgroundColor: c.surfaceMuted, borderColor: c.card, marginLeft: i === 0 ? 0 : -8 },
                      ]}
                    >
                      <Text style={[s.crewAvatarText, { color: c.foreground }]}>{m.initials}</Text>
                    </View>
                  ))}
                  {crew.length > 4 && (
                    <View style={[s.crewAvatar, { backgroundColor: c.surfaceMuted, borderColor: c.card, marginLeft: -8 }]}>
                      <Text style={[s.crewAvatarText, { color: c.mutedForeground }]}>+{crew.length - 4}</Text>
                    </View>
                  )}
                </View>
                <Text style={[s.crewCount, { color: c.mutedForeground }]}>
                  {crew.length} crew member{crew.length !== 1 ? 's' : ''}
                </Text>
              </View>
            )}
          </View>
        </TouchableOpacity>

        {/* ── Notifications ── */}
        <Text style={s.sectionLabel}>INBOX</Text>
        <TouchableOpacity
          style={[
            s.notifCard,
            unreadCount > 0
              ? { backgroundColor: c.danger + '06', borderColor: c.danger + '40' }
              : { backgroundColor: c.card, borderColor: c.border },
          ]}
          onPress={() => switchTab('NotificationsTab')}
          activeOpacity={0.75}
        >
          {/* Top stripe when unread */}
          {unreadCount > 0 && <View style={[s.notifStripe, { backgroundColor: c.danger }]} />}

          <View style={s.notifInner}>
            <View style={[s.notifIconWell, {
              backgroundColor: unreadCount > 0 ? c.danger + '18' : c.surfaceMuted,
            }]}>
              <Text style={{ fontSize: 22 }}>🔔</Text>
            </View>

            <View style={{ flex: 1 }}>
              <View style={s.notifTitleRow}>
                <Text style={[s.notifTitle, { color: c.foreground }]}>Notifications</Text>
                {unreadCount > 0 && (
                  <View style={[s.unreadBadge, { backgroundColor: c.danger }]}>
                    <Text style={s.unreadText}>{unreadCount > 99 ? '99+' : unreadCount} unread</Text>
                  </View>
                )}
              </View>

              {notifLoad ? (
                <Skeleton width={180} height={13} style={{ marginTop: 4 }} />
              ) : latestMessage ? (
                <Text style={[s.notifPreview, { color: unreadCount > 0 ? c.foreground : c.mutedForeground }]} numberOfLines={1}>
                  {stripMarkdown(latestMessage)}
                </Text>
              ) : (
                <Text style={[s.notifPreview, { color: c.mutedForeground }]}>All caught up</Text>
              )}
            </View>

            <Text style={[s.chevron, { color: c.subtleForeground }]}>›</Text>
          </View>
        </TouchableOpacity>

      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:    { flex: 1, backgroundColor: c.background },
  scroll:  { flex: 1 },
  content: { padding: spacing.md, paddingBottom: spacing.xxl, gap: spacing.xs },

  // Top bar
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: c.border,
    backgroundColor: c.surface,
  },
  wordmark: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.extrabold,
    letterSpacing: -0.5,
    color: c.foreground,
  },

  // Hero card — centered profile style
  hero: {
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
    borderRadius: radius.xl,
    borderWidth: 1,
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
    gap: spacing.xs,
  },
  heroAvatarWrap: { marginBottom: spacing.lg },
  heroAvatarRing: {
    borderRadius: 999, borderWidth: 2.5, padding: 3,
  },
  heroDate:    { fontSize: fontSize.xs, fontWeight: fontWeight.medium, letterSpacing: 0.2, textAlign: 'center' },
  heroGreet:   { fontSize: fontSize.sm, fontWeight: fontWeight.regular, textAlign: 'center' },
  heroName:    { fontSize: fontSize['2xl'], fontWeight: fontWeight.extrabold, letterSpacing: -0.5, lineHeight: 34, textAlign: 'center' },
  heroRolePill: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    paddingHorizontal: spacing.sm + 2, paddingVertical: 5,
    borderRadius: radius.full, borderWidth: 1,
    marginTop: spacing.xs,
  },
  heroRoleDot:  { width: 7, height: 7, borderRadius: 4 },
  heroRoleText: { fontSize: fontSize.xs, fontWeight: fontWeight.bold, letterSpacing: 0.3 },

  // Quick actions
  quickRow: {
    flexDirection: 'row',
    gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  quickBtn: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.lg,
    borderWidth: 1,
    gap: 4,
  },
  quickIcon:  { fontSize: 22 },
  quickLabel: { fontSize: 10, fontWeight: fontWeight.semibold, textAlign: 'center' },

  // Section labels
  sectionLabel: {
    fontSize: 10,
    fontWeight: fontWeight.bold,
    letterSpacing: 0.8,
    color: c.mutedForeground,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
    paddingHorizontal: spacing.xs,
  },

  // Assignment card
  assignCard: {
    flexDirection: 'row',
    borderRadius: radius.xl,
    borderWidth: 1.5,
    overflow: 'hidden',
    marginBottom: spacing.xs,
  },
  assignStripe: { width: 4 },
  assignBody:   { flex: 1, padding: spacing.md, gap: spacing.sm },
  assignTop:    { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  assignIconWell: {
    width: 52, height: 52,
    borderRadius: radius.lg,
    alignItems: 'center', justifyContent: 'center',
    flexShrink: 0,
  },
  assignEyebrow: { fontSize: 10, fontWeight: fontWeight.semibold, letterSpacing: 0.6, textTransform: 'uppercase' },
  assignTruck:   { fontSize: fontSize.lg, fontWeight: fontWeight.extrabold, marginTop: 1, letterSpacing: -0.3 },
  assignEmpty:   { fontSize: fontSize.base, fontWeight: fontWeight.regular, marginTop: 2 },
  rolePill: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.full,
    marginTop: spacing.xs,
  },
  rolePillText: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  // Crew row
  crewRow:       { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingTop: spacing.xs, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.border },
  crewAvatars:   { flexDirection: 'row' },
  crewAvatar:    { width: 28, height: 28, borderRadius: 14, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  crewAvatarText:{ fontSize: 9, fontWeight: fontWeight.bold },
  crewCount:     { fontSize: fontSize.xs },

  // Notifications card
  notifCard: {
    borderRadius: radius.xl,
    borderWidth: 1,
    marginBottom: spacing.xs,
    overflow: 'hidden',
  },
  notifStripe:   { height: 3 },
  notifInner:    { flexDirection: 'row', alignItems: 'center', padding: spacing.md, gap: spacing.sm },
  notifIconWell: { width: 48, height: 48, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  notifTitleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: 2 },
  notifTitle:    { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground },
  notifPreview:  { fontSize: fontSize.xs },

  unreadBadge: { paddingHorizontal: spacing.sm, height: 20, borderRadius: radius.full, alignItems: 'center', justifyContent: 'center' },
  unreadText:  { color: '#fff', fontSize: 10, fontWeight: fontWeight.bold },

  chevron: { fontSize: 22, paddingLeft: spacing.xs },
});
