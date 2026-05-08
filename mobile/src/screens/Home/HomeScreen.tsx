import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  useColorScheme, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '@contexts/AuthContext';
import { useTabSwitch } from '@navigation/index';
import apiClient from '@api/client';
import { lightColors, darkColors, spacing, radius, fontSize, fontWeight } from '@theme/index';

const ROLE_LABELS: Record<string, string> = {
  driver: 'Driver', trainer: 'Trainer', trainee: 'Trainee', walker: 'Walker',
};
const ROLE_COLORS: Record<string, string> = {
  driver: '#5B4FE8', trainer: '#0FA870', trainee: '#0EA5D8', walker: '#E8820C',
};

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

function stripMarkdown(text: string): string {
  return text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1');
}

function getInitials(name: string): string {
  const parts = name.trim().split(' ');
  if (parts.length === 1) return parts[0][0]?.toUpperCase() ?? '?';
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export default function HomeScreen() {
  const scheme = useColorScheme();
  const c = scheme === 'dark' ? darkColors : lightColors;
  const { user } = useAuth();
  const navigation = useNavigation<any>();
  const switchTab = useTabSwitch();

  const today = localToday();

  const [truckName,   setTruckName]   = useState<string | null>(null);
  const [myRole,      setMyRole]      = useState<string | null>(null);
  const [crewCount,   setCrewCount]   = useState<number>(0);
  const [assignLoad,  setAssignLoad]  = useState(true);

  const [unreadCount,   setUnreadCount]   = useState(0);
  const [latestMessage, setLatestMessage] = useState<string | null>(null);
  const [notifLoad,     setNotifLoad]     = useState(true);

  const [refreshing, setRefreshing] = useState(false);

  const displayName = user?.firstName ?? user?.email?.split('@')[0] ?? 'Crew Member';
  const primaryRole = ['driver', 'trainer', 'trainee', 'walker'].find(r => user?.groups?.includes(r));
  const roleColor   = primaryRole ? ROLE_COLORS[primaryRole] : c.primary;
  const initials    = getInitials(displayName);

  const fetchAssignment = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res = await apiClient.get(`/schedule/${user.id}?start_date=${today}&end_date=${today}`);
      const entry = (res.data ?? [])[0];
      if (!entry || entry.status !== 'Assigned' || !entry.truck_name) {
        setTruckName(null); setMyRole(null); setCrewCount(0);
        return;
      }
      const me = (entry.crew ?? []).find((m: any) => m.id === user.id);
      setTruckName(entry.truck_name);
      setMyRole(me?.role ?? null);
      setCrewCount((entry.crew ?? []).length);
    } catch {
      setTruckName(null);
    } finally {
      setAssignLoad(false);
    }
  }, [today, user?.id]);

  const fetchNotifications = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res = await apiClient.get(`/notifications/${user.id}?limit=10`);
      const list: any[] = res.data ?? [];
      setUnreadCount(list.filter(n => !n.is_read).length);
      setLatestMessage(list[0]?.message ?? null);
    } catch {
      setUnreadCount(0);
    } finally {
      setNotifLoad(false);
    }
  }, [user?.id]);

  useEffect(() => {
    fetchAssignment();
    fetchNotifications();
  }, [fetchAssignment, fetchNotifications]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([fetchAssignment(), fetchNotifications()]);
    setRefreshing(false);
  }, [fetchAssignment, fetchNotifications]);

  const s = styles(c);

  return (
    <SafeAreaView style={s.safe} edges={['top']}>

      {/* ── Fixed top bar (outside ScrollView) ───────────────── */}
      <View style={[s.topBar, { borderBottomColor: c.border }]}>
        <Text style={[s.wordmark, { color: c.foreground }]}>AsheFlow</Text>
        <TouchableOpacity
          onPress={() => navigation.navigate('Profile')}
          activeOpacity={0.75}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <View style={[s.avatar, { backgroundColor: roleColor + '18', borderColor: roleColor + '35' }]}>
            <Text style={[s.avatarText, { color: roleColor }]}>{initials}</Text>
          </View>
        </TouchableOpacity>
      </View>

      {/* ── Scrollable content ────────────────────────────────── */}
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />}
      >
        {/* Greeting section */}
        <View style={s.greetingSection}>
          <Text style={[s.greetingLine, { color: c.foreground }]}>
            <Text style={[s.greetingWord, { color: c.mutedForeground }]}>{greet()}, </Text>
            {displayName}
          </Text>
          {primaryRole && (
            <View style={[s.rolePill, { backgroundColor: roleColor + '15', borderColor: roleColor + '28' }]}>
              <View style={[s.roleDot, { backgroundColor: roleColor }]} />
              <Text style={[s.roleText, { color: roleColor }]}>{ROLE_LABELS[primaryRole]}</Text>
            </View>
          )}
        </View>

        {/* ── Today's Assignment card ── */}
        <TouchableOpacity
          style={[s.card, truckName ? { borderLeftWidth: 3, borderLeftColor: roleColor } : {}]}
          onPress={() => navigation.navigate('TodayAssignment')}
          activeOpacity={0.72}
          disabled={assignLoad}
        >
          <View style={s.cardInner}>
            <View style={[s.iconBox, { backgroundColor: c.primaryLight }]}>
              <Text style={s.iconText}>🚚</Text>
            </View>
            <View style={s.cardBody}>
              <Text style={s.cardLabel}>Today's Assignment</Text>
              {assignLoad ? (
                <ActivityIndicator size="small" color={c.primary} style={{ alignSelf: 'flex-start', marginTop: 4 }} />
              ) : truckName ? (
                <Text style={s.cardValue}>{truckName}</Text>
              ) : (
                <Text style={[s.cardValue, { color: c.mutedForeground, fontWeight: fontWeight.regular }]}>No assignment today</Text>
              )}
              {truckName && myRole && (
                <Text style={[s.cardSub, { color: roleColor }]}>{ROLE_LABELS[myRole] ?? myRole}</Text>
              )}
            </View>
            {truckName && (
              <View style={s.crewBubble}>
                <Text style={[s.crewNum, { color: c.primary }]}>{crewCount}</Text>
                <Text style={s.crewLabel}>CREW</Text>
              </View>
            )}
            <Text style={[s.chevron, { color: c.mutedForeground }]}>›</Text>
          </View>
        </TouchableOpacity>

        {/* ── Notifications card ── */}
        <TouchableOpacity
          style={s.card}
          onPress={() => switchTab('NotificationsTab')}
          activeOpacity={0.72}
          disabled={notifLoad}
        >
          <View style={s.cardInner}>
            <View style={[s.iconBox, {
              backgroundColor: unreadCount > 0 ? c.primary + '15' : c.surfaceMuted,
            }]}>
              <Text style={s.iconText}>🔔</Text>
            </View>
            <View style={s.cardBody}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs }}>
                <Text style={s.cardLabel}>Notifications</Text>
                {unreadCount > 0 && (
                  <View style={[s.badge, { backgroundColor: c.primary }]}>
                    <Text style={s.badgeText}>{unreadCount > 99 ? '99+' : unreadCount}</Text>
                  </View>
                )}
              </View>
              {notifLoad ? (
                <ActivityIndicator size="small" color={c.primary} style={{ alignSelf: 'flex-start', marginTop: 4 }} />
              ) : latestMessage ? (
                <Text style={s.cardSub} numberOfLines={1}>{stripMarkdown(latestMessage)}</Text>
              ) : (
                <Text style={[s.cardSub, { color: c.mutedForeground }]}>All caught up</Text>
              )}
            </View>
            <Text style={[s.chevron, { color: c.mutedForeground }]}>›</Text>
          </View>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: typeof lightColors) => StyleSheet.create({
  safe:    { flex: 1, backgroundColor: c.background },
  scroll:  { flex: 1 },
  content: { padding: spacing.lg, paddingBottom: spacing.xxl },

  // Fixed top bar
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  wordmark: { fontSize: fontSize.lg, fontWeight: fontWeight.extrabold, letterSpacing: -0.5 },
  avatar: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1.5,
  },
  avatarText: { fontSize: fontSize.xs, fontWeight: fontWeight.bold },

  // Greeting
  greetingSection: { marginBottom: spacing.lg, gap: spacing.xs },
  greetingLine:    { fontSize: fontSize.xl, fontWeight: fontWeight.extrabold, letterSpacing: -0.4 },
  greetingWord:    { fontWeight: fontWeight.regular },
  rolePill: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    paddingHorizontal: spacing.sm, paddingVertical: 4,
    borderRadius: radius.full, borderWidth: 1,
    alignSelf: 'flex-start',
  },
  roleDot:  { width: 6, height: 6, borderRadius: 3 },
  roleText: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  // Cards
  card: {
    backgroundColor: c.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    marginBottom: spacing.md,
    overflow: 'hidden',
  },
  cardInner:  { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.md },
  iconBox:    { width: 46, height: 46, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  iconText:   { fontSize: 22 },
  cardBody:   { flex: 1 },
  cardLabel:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.4 },
  cardValue:  { fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground, marginTop: 2 },
  cardSub:    { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  crewBubble: { alignItems: 'center', paddingHorizontal: spacing.xs },
  crewNum:    { fontSize: fontSize.md, fontWeight: fontWeight.extrabold },
  crewLabel:  { fontSize: 9, color: c.mutedForeground, fontWeight: fontWeight.semibold, letterSpacing: 0.6 },
  badge:      { minWidth: 18, height: 18, borderRadius: 9, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 5 },
  badgeText:  { color: '#fff', fontSize: 10, fontWeight: fontWeight.bold },
  chevron:    { fontSize: 20, paddingLeft: spacing.xs },
});
