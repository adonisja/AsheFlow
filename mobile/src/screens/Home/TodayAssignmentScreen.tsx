import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { useTabSwitch } from '@navigation/index';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type CrewMember = { id: string; name: string; role: string };

type Assignment = {
  truck_name: string;
  role: string;
  // dispatch phase: 'planned' | 'active' | 'completed'
  dispatchPhase: 'planned' | 'active' | 'completed';
  crew: CrewMember[];
};

const ROLE_LABELS: Record<string, string> = {
  driver: 'Driver', trainer: 'Trainer', trainee: 'Trainee', walker: 'Walker',
};

const ROLE_COLORS: Record<string, string> = {
  driver:  '#5B4FE8',
  trainer: '#0FA870',
  trainee: '#0EA5D8',
  walker:  '#E8820C',
};

const ROLE_ORDER = ['driver', 'trainer', 'trainee', 'walker'];

const PHASE_BADGE = {
  planned:   { label: 'Scheduled',  color: '#E8820C', bg: '#E8820C22' },
  active:    { label: 'Confirming', color: '#0EA5D8', bg: '#0EA5D822' },
  completed: { label: 'Confirmed',  color: '#0FA870', bg: '#0FA87022' },
};

export default function TodayAssignmentScreen() {
  const c = useColors();
  const { user } = useAuth();
  const { fetchId, cachedId } = useEmployeeId();
  const switchTab = useTabSwitch();

  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const todayLocal = new Date();
  const today = `${todayLocal.getFullYear()}-${String(todayLocal.getMonth() + 1).padStart(2, '0')}-${String(todayLocal.getDate()).padStart(2, '0')}`;

  const load = useCallback(async () => {
    const eid = await fetchId();
    if (!eid) return;
    try {
      const [schedRes, dispatchRes] = await Promise.allSettled([
        apiClient.get(`/schedule/${eid}?start_date=${today}&end_date=${today}`),
        apiClient.get(`/dispatch/${today}`),
      ]);

      const entry = schedRes.status === 'fulfilled' ? (schedRes.value.data ?? [])[0] : null;
      if (!entry || entry.status !== 'Assigned' || !entry.truck_name) {
        setAssignment(null);
        return;
      }

      const me = (entry.crew ?? []).find((m: any) => m.id === eid);

      // Determine dispatch phase by finding the employee's truck in the dispatch response.
      let dispatchPhase: Assignment['dispatchPhase'] = 'planned';
      if (dispatchRes.status === 'fulfilled') {
        const dispatch = dispatchRes.value.data;
        const assignedCrews: Record<string, { employee_id: string }[]> = dispatch?.assigned_crews ?? {};
        const truckAssignments: { truck_id: string; status: string }[] = dispatch?.truck_assignments ?? [];

        // Find which truck this employee is on
        const myTruckId = Object.entries(assignedCrews).find(([, crew]) =>
          crew.some((m) => m.employee_id === eid),
        )?.[0];

        if (myTruckId) {
          const ta = truckAssignments.find((t) => t.truck_id === myTruckId);
          if (ta?.status === 'completed') dispatchPhase = 'completed';
          else if (ta?.status === 'active') dispatchPhase = 'active';
        }
      }

      setAssignment({
        truck_name: entry.truck_name,
        role: me?.role ?? 'unknown',
        dispatchPhase,
        crew: entry.crew ?? [],
      });
    } catch {
      setAssignment(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [today, fetchId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const s = styles(c);

  if (!loading && !assignment) {
    return (
      <ScreenShell title="Today's Assignment" subtitle={today} onBack={() => switchTab('Home')}>
        <View style={s.emptyCard}>
          <Text style={s.emptyIcon}>🚚</Text>
          <Text style={s.emptyText}>No assignment for today</Text>
          <Text style={s.emptySubtext}>Check back after dispatch runs</Text>
        </View>
      </ScreenShell>
    );
  }

  // Group crew by role for structured display
  const grouped: Record<string, CrewMember[]> = {};
  for (const m of assignment?.crew ?? []) {
    (grouped[m.role] = grouped[m.role] ?? []).push(m);
  }
  const roleOrder = ROLE_ORDER.filter(r => grouped[r]?.length);

  return (
    <ScreenShell
      title="Today's Assignment"
      subtitle={today}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); load(); }}
      onBack={() => switchTab('Home')}
    >
      {/* Truck + my role */}
      {assignment && (
        <View style={s.heroCard}>
          <View style={s.truckRow}>
            <View style={s.truckIcon}>
              <Text style={s.truckEmoji}>🚚</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.truckName}>{assignment.truck_name}</Text>
              <Text style={s.truckSub}>Today's truck</Text>
            </View>
            <View style={[s.statusBadge, { backgroundColor: PHASE_BADGE[assignment.dispatchPhase].bg }]}>
              <Text style={[s.statusText, { color: PHASE_BADGE[assignment.dispatchPhase].color }]}>
                {PHASE_BADGE[assignment.dispatchPhase].label}
              </Text>
            </View>
          </View>

          <View style={s.divider} />

          <Text style={s.myRoleLabel}>Your Role</Text>
          <View style={[s.myRolePill, { backgroundColor: (ROLE_COLORS[assignment.role] ?? c.primary) + '18' }]}>
            <Text style={[s.myRoleText, { color: ROLE_COLORS[assignment.role] ?? c.primary }]}>
              {ROLE_LABELS[assignment.role] ?? assignment.role}
            </Text>
          </View>
        </View>
      )}

      {/* Crew — grouped by role */}
      {roleOrder.map(role => (
        <View key={role} style={s.section}>
          <View style={s.sectionHeader}>
            <View style={[s.roleDot, { backgroundColor: ROLE_COLORS[role] ?? c.primary }]} />
            <Text style={s.sectionTitle}>{ROLE_LABELS[role] ?? role}s</Text>
            <Text style={s.sectionCount}>{grouped[role].length}</Text>
          </View>
          {grouped[role].map((m, i) => (
            <View
              key={m.id}
              style={[
                s.memberRow,
                i < grouped[role].length - 1 && s.memberRowBorder,
                m.id === cachedId.current && s.memberRowMe,
              ]}
            >
              <View style={[s.avatar, { backgroundColor: (ROLE_COLORS[role] ?? c.primary) + '18' }]}>
                <Text style={[s.avatarText, { color: ROLE_COLORS[role] ?? c.primary }]}>
                  {m.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
                </Text>
              </View>
              <Text style={[s.memberName, m.id === cachedId.current && { color: c.primary, fontWeight: fontWeight.semibold }]}>
                {m.name}{m.id === cachedId.current ? ' (you)' : ''}
              </Text>
            </View>
          ))}
        </View>
      ))}
    </ScreenShell>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  heroCard:      { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.lg },
  truckRow:      { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  truckIcon:     { width: 48, height: 48, borderRadius: radius.md, backgroundColor: c.primaryLight, alignItems: 'center', justifyContent: 'center' },
  truckEmoji:    { fontSize: 22 },
  truckName:     { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  truckSub:      { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  statusBadge:   { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  statusText:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  divider:       { height: 1, backgroundColor: c.border, marginVertical: spacing.md },
  myRoleLabel:   { fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.8, fontWeight: fontWeight.semibold, marginBottom: spacing.xs },
  myRolePill:    { alignSelf: 'flex-start', paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.full },
  myRoleText:    { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },

  section:       { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, marginBottom: spacing.md, overflow: 'hidden' },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, backgroundColor: c.surfaceMuted },
  roleDot:       { width: 8, height: 8, borderRadius: 4 },
  sectionTitle:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.foreground, textTransform: 'uppercase', letterSpacing: 0.8, flex: 1 },
  sectionCount:  { fontSize: fontSize.xs, color: c.mutedForeground, fontWeight: fontWeight.medium },

  memberRow:     { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  memberRowBorder:{ borderBottomWidth: 1, borderBottomColor: c.border },
  memberRowMe:   { backgroundColor: c.primaryLight + '40' },
  avatar:        { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  avatarText:    { fontSize: fontSize.xs, fontWeight: fontWeight.bold },
  memberName:    { fontSize: fontSize.sm, color: c.foreground, flex: 1 },

  emptyCard:     { alignItems: 'center', marginTop: spacing.xxl, gap: spacing.sm },
  emptyIcon:     { fontSize: 48 },
  emptyText:     { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  emptySubtext:  { fontSize: fontSize.sm, color: c.mutedForeground },
});
