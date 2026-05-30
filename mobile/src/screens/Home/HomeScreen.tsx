import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '@contexts/AuthContext';
import { useTabSwitch } from '@navigation/index';
import { useColors } from '@contexts/ThemeContext';
import apiClient from '@api/client';
import {
  spacing, radius, fontSize, fontWeight,
  getRoleColor, getRoleLight, ROLE_LABELS, type ThemeColors,
} from '@theme/index';
import {
  Avatar, Badge, Card, SectionHeader, Skeleton, Row,
} from '@components/ui/primitives';

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

// Role → Badge tone mapping
const roleBadgeTone: Record<string, 'slate' | 'teal' | 'gold' | 'info' | 'neutral'> = {
  driver:  'slate',
  walker:  'teal',
  trainer: 'gold',
  trainee: 'info',
};

export default function HomeScreen() {
  const c = useColors();
  const { user } = useAuth();
  const navigation = useNavigation<any>();
  const switchTab  = useTabSwitch();

  const today = localToday();

  const [truckName,  setTruckName]  = useState<string | null>(null);
  const [myRole,     setMyRole]     = useState<string | null>(null);
  const [crewCount,  setCrewCount]  = useState<number>(0);
  const [assignLoad, setAssignLoad] = useState(true);

  const [unreadCount,    setUnreadCount]    = useState(0);
  const [latestMessage,  setLatestMessage]  = useState<string | null>(null);
  const [notifLoad,      setNotifLoad]      = useState(true);

  const [refreshing, setRefreshing] = useState(false);

  const displayName  = user?.firstName ?? user?.email?.split('@')[0] ?? 'Crew Member';
  const primaryRole  = ['driver', 'trainer', 'trainee', 'walker'].find(r => user?.groups?.includes(r)) as string | undefined;
  const roleColor    = primaryRole ? getRoleColor(primaryRole as any, c) : c.primary;
  const roleLight    = primaryRole ? getRoleLight(primaryRole as any, c) : c.primaryLight;
  const initials     = getInitials(displayName);

  const fetchAssignment = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res   = await apiClient.get(`/schedule/${user.id}?start_date=${today}&end_date=${today}`);
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
      const res  = await apiClient.get(`/notifications/${user.id}?limit=10`);
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

      {/* ── Top bar ────────────────────────────────────────── */}
      <View style={[s.topBar, { borderBottomColor: c.border, backgroundColor: c.surface }]}>
        <Text style={[s.wordmark, { color: c.foreground }]}>AsheFlow</Text>
        <TouchableOpacity
          onPress={() => navigation.navigate('Profile')}
          activeOpacity={0.75}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Avatar initials={initials} role={primaryRole as any ?? 'driver'} size={36} />
        </TouchableOpacity>
      </View>

      {/* ── Scrollable body ────────────────────────────────── */}
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />
        }
      >
        {/* Greeting */}
        <View style={s.greeting}>
          <Text style={[s.greetMuted, { color: c.mutedForeground }]}>{greet()},</Text>
          <Text style={[s.greetName, { color: c.foreground }]}>{displayName}</Text>
          {primaryRole && (
            <View style={{ marginTop: spacing.xs }}>
              <Badge tone={roleBadgeTone[primaryRole] ?? 'muted'} dot>
                {ROLE_LABELS[primaryRole] ?? primaryRole}
              </Badge>
            </View>
          )}
        </View>

        {/* ── Today's Assignment ── */}
        <SectionHeader eyebrow="Today" title="Assignment" style={{ marginBottom: spacing.sm }} />

        <Card
          pressable={!assignLoad}
          onPress={() => navigation.navigate('TodayAssignment')}
          accent={truckName ? roleColor : undefined}
          style={{ marginBottom: spacing.md }}
        >
          <View style={s.cardInner}>
            {/* Icon well */}
            <View style={[s.iconWell, { backgroundColor: roleLight }]}>
              <Text style={s.iconEmoji}>🚚</Text>
            </View>

            {/* Body */}
            <View style={s.cardBody}>
              <Text style={[s.cardEyebrow, { color: c.mutedForeground }]}>TRUCK</Text>
              {assignLoad ? (
                <Skeleton width={120} height={18} style={{ marginTop: 4 }} />
              ) : truckName ? (
                <>
                  <Text style={[s.cardValue, { color: c.foreground }]}>{truckName}</Text>
                  {myRole && (
                    <Text style={[s.cardSub, { color: roleColor }]}>
                      {ROLE_LABELS[myRole] ?? myRole}
                    </Text>
                  )}
                </>
              ) : (
                <Text style={[s.cardValue, { color: c.mutedForeground, fontWeight: fontWeight.regular }]}>
                  No assignment today
                </Text>
              )}
            </View>

            {/* Crew bubble */}
            {truckName && (
              <View style={[s.crewBubble, { backgroundColor: c.primaryLight }]}>
                <Text style={[s.crewNum, { color: c.primary }]}>{crewCount}</Text>
                <Text style={[s.crewLabel, { color: c.mutedForeground }]}>CREW</Text>
              </View>
            )}

            <Text style={[s.chevron, { color: c.subtleForeground }]}>›</Text>
          </View>
        </Card>

        {/* ── Notifications ── */}
        <SectionHeader eyebrow="Inbox" title="Notifications" style={{ marginBottom: spacing.sm }} />

        <Card
          pressable={!notifLoad}
          onPress={() => switchTab('NotificationsTab')}
          style={{ marginBottom: spacing.md }}
        >
          <View style={s.cardInner}>
            <View style={[s.iconWell, {
              backgroundColor: unreadCount > 0 ? c.primaryLight : c.surfaceMuted,
            }]}>
              <Text style={s.iconEmoji}>🔔</Text>
            </View>

            <View style={s.cardBody}>
              <Row gap={8} align="center">
                <Text style={[s.cardEyebrow, { color: c.mutedForeground }]}>MESSAGES</Text>
                {unreadCount > 0 && (
                  <View style={[s.unreadBubble, { backgroundColor: c.danger }]}>
                    <Text style={s.unreadText}>{unreadCount > 99 ? '99+' : unreadCount}</Text>
                  </View>
                )}
              </Row>

              {notifLoad ? (
                <Skeleton width={160} height={16} style={{ marginTop: 4 }} />
              ) : latestMessage ? (
                <Text style={[s.cardSub, { color: c.foreground }]} numberOfLines={1}>
                  {stripMarkdown(latestMessage)}
                </Text>
              ) : (
                <Text style={[s.cardSub, { color: c.mutedForeground }]}>All caught up</Text>
              )}
            </View>

            <Text style={[s.chevron, { color: c.subtleForeground }]}>›</Text>
          </View>
        </Card>

      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:    { flex: 1, backgroundColor: c.background },
  scroll:  { flex: 1 },
  content: { padding: spacing.lg, paddingBottom: spacing.xxl },

  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  wordmark: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.extrabold,
    letterSpacing: -0.5,
  },

  greeting: {
    marginBottom: spacing.xl,
    gap: 2,
  },
  greetMuted: {
    fontSize: fontSize.base,
    fontWeight: fontWeight.regular,
  },
  greetName: {
    fontSize: fontSize['2xl'],
    fontWeight: fontWeight.extrabold,
    letterSpacing: -0.5,
    lineHeight: 34,
  },

  cardInner:   { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.md },
  iconWell:    { width: 48, height: 48, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  iconEmoji:   { fontSize: 22 },
  cardBody:    { flex: 1 },
  cardEyebrow: { fontSize: 10, fontWeight: fontWeight.semibold, letterSpacing: 0.6, textTransform: 'uppercase' },
  cardValue:   { fontSize: fontSize.base, fontWeight: fontWeight.bold, marginTop: 2 },
  cardSub:     { fontSize: fontSize.xs, marginTop: 2 },

  crewBubble: { alignItems: 'center', paddingHorizontal: spacing.xs, paddingVertical: 4, borderRadius: radius.sm },
  crewNum:    { fontSize: fontSize.md, fontWeight: fontWeight.extrabold },
  crewLabel:  { fontSize: 9, fontWeight: fontWeight.semibold, letterSpacing: 0.6 },

  unreadBubble: { minWidth: 18, height: 18, borderRadius: radius.full, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  unreadText:   { color: '#fff', fontSize: 10, fontWeight: fontWeight.bold },

  chevron: { fontSize: 22, paddingLeft: spacing.xs },
});
