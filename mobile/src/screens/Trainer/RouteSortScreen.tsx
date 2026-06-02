import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── Types ─────────────────────────────────────────────────────────────────────

type AssignmentMember = {
  id: string;
  employee_id: string;
  employee_name: string;
  role: string;
};

type TruckAssignment = {
  id: string;
  truck_id: string;
  date: string;
  status: string;
  sort_initiated_by: string | null;
  sort_committed_at: string | null;
};

type WalkerTrip = {
  id: string;
  trip_number: number;
  bag_ids: string[];
  tba_numbers: string[];
  status: string;
};

type WalkerRoute = {
  id: string;
  walker_id: string;
  total_packages: number;
  total_bags: number;
  planned_trips: number;
  trips: WalkerTrip[];
};

type CommitResult = {
  routes: WalkerRoute[];
  packages_sorted: number;
  packages_dropped: number;
  dropped_tbas: string[];
  sort_initiated_by_name: string | null;
  sort_committed_at: string | null;
};

type OVRow = { sort_zone: string; size_tier: 'XL' | 'L' | 'M' | 'S'; paired_bag_id: string };

const SIZE_TIERS: OVRow['size_tier'][] = ['XL', 'L', 'M', 'S'];

// ── Helpers ───────────────────────────────────────────────────────────────────

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// ── Main component ────────────────────────────────────────────────────────────

export default function RouteSortScreen() {
  const c = useColors();
  const { user } = useAuth();
  const { fetchId } = useEmployeeId();
  const s = styles(c);

  // ── State ──
  const [loading,      setLoading]      = useState(true);
  const [assignment,   setAssignment]   = useState<TruckAssignment | null>(null);
  const [members,      setMembers]      = useState<AssignmentMember[]>([]);
  const [lockedResult, setLockedResult] = useState<CommitResult | null>(null);
  const [lockedByName, setLockedByName] = useState<string | null>(null);

  // Walker picker
  const [walkerIds,    setWalkerIds]    = useState<string[]>([]);

  // OV rows
  const [ovs,          setOvs]          = useState<OVRow[]>([]);

  // Submitting
  const [committing,   setCommitting]   = useState(false);

  // ── Load today's assignment for this trainer ──
  const load = useCallback(async () => {
    const eid = await fetchId();
    if (!eid) return;
    setLoading(true);
    try {
      // Today's dispatch — find the truck assignment this trainer is on
      const dispRes = await apiClient.get(`/dispatch/${today()}`);
      const dispatch = dispRes.data;
      const myMember = dispatch?.assignment_members?.find(
        (m: any) => m.employee_id === eid
      );
      if (!myMember) { setAssignment(null); setLoading(false); return; }

      const assignmentId = myMember.truck_assignment_id;

      // Fetch full assignment (includes sort_initiated_by etc.)
      const aRes = await apiClient.get(`/dispatch/assignments/${assignmentId}`);
      const a: TruckAssignment = aRes.data;
      setAssignment(a);

      // All members on this truck
      const allMembers: AssignmentMember[] = dispatch.assignment_members.filter(
        (m: any) => m.truck_assignment_id === assignmentId
      );
      setMembers(allMembers);

      // Pre-select walkers (trainee counts as walker for sort)
      const walkers = allMembers
        .filter(m => m.role === 'walker' || m.role === 'trainee')
        .map(m => m.employee_id);
      setWalkerIds(walkers);

      // If already locked, load committed routes
      if (a.sort_initiated_by) {
        const routesRes = await apiClient.get(`/walker-routes/assignment/${assignmentId}`);
        // Fetch initiator name from members list
        const initiator = allMembers.find(m => m.employee_id === a.sort_initiated_by);
        setLockedByName(initiator?.employee_name ?? 'another trainer');
        setLockedResult({
          routes:                routesRes.data,
          packages_sorted:       0,
          packages_dropped:      0,
          dropped_tbas:          [],
          sort_initiated_by_name: initiator?.employee_name ?? null,
          sort_committed_at:     a.sort_committed_at,
        });
      }
    } catch {
      setAssignment(null);
    } finally {
      setLoading(false);
    }
  }, [fetchId]);

  useEffect(() => { load(); }, [load]);

  // ── OV helpers ──
  function addOV() {
    setOvs(prev => [...prev, { sort_zone: '', size_tier: 'XL', paired_bag_id: '' }]);
  }
  function removeOV(i: number) {
    setOvs(prev => prev.filter((_, idx) => idx !== i));
  }
  function updateOV<K extends keyof OVRow>(i: number, key: K, val: OVRow[K]) {
    setOvs(prev => prev.map((row, idx) => idx === i ? { ...row, [key]: val } : row));
  }

  // ── Toggle walker selection ──
  function toggleWalker(id: string) {
    setWalkerIds(prev =>
      prev.includes(id) ? prev.filter(w => w !== id) : [...prev, id]
    );
  }

  // ── Commit ──
  async function handleCommit() {
    if (!assignment) return;
    if (walkerIds.length === 0) {
      Alert.alert('No walkers selected', 'Select at least one walker or trainee to sort routes.');
      return;
    }
    const invalidOvs = ovs.filter(o => !o.sort_zone.trim() || !o.paired_bag_id.trim());
    if (invalidOvs.length > 0) {
      Alert.alert('Incomplete OV entries', 'Fill in sort zone and bag ID for all OV rows, or remove them.');
      return;
    }

    Alert.alert(
      'Commit Route Sort',
      `Sort routes for ${walkerIds.length} walker(s)? This cannot be undone — only one sort per assignment is allowed.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Commit', style: 'destructive',
          onPress: async () => {
            setCommitting(true);
            try {
              const res = await apiClient.post('/walker-routes/commit', {
                truck_assignment_id: assignment.id,
                route_date:          assignment.date,
                walker_count:        walkerIds.length,
                walker_ids:          walkerIds,
                ovs:                 ovs.filter(o => o.sort_zone.trim()),
              });
              setLockedResult(res.data);
              setLockedByName(res.data.sort_initiated_by_name ?? user?.firstName ?? 'You');
              Alert.alert('Sort committed', `${res.data.packages_sorted} packages distributed across ${walkerIds.length} routes.`);
            } catch (err: any) {
              const status = err?.response?.status;
              const detail = err?.response?.data?.detail;
              if (status === 409) {
                Alert.alert('Already committed', detail ?? 'Another trainer already ran the sort.');
                load();
              } else {
                Alert.alert('Error', detail ?? 'Could not commit sort. Try again.');
              }
            } finally {
              setCommitting(false);
            }
          },
        },
      ]
    );
  }

  // ── Render ──
  const s2 = styles(c);

  if (loading) {
    return (
      <View style={s2.center}>
        <ActivityIndicator size="large" color={c.primary} />
      </View>
    );
  }

  if (!assignment) {
    return (
      <ScreenShell edges={[]} noHeader title="Route Sort" subtitle="">
        <View style={s2.center}>
          <Text style={{ fontSize: 40 }}>🗺️</Text>
          <Text style={[s2.emptyTitle]}>No assignment today</Text>
          <Text style={[s2.emptySub]}>You are not on a truck assignment for today.</Text>
        </View>
      </ScreenShell>
    );
  }

  // ── Locked view (sort already committed) ──
  if (lockedResult) {
    return (
      <ScrollView style={s2.scroll} contentContainerStyle={{ padding: spacing.md }}>
        <View style={[s2.lockBanner, { backgroundColor: c.primary + '22', borderColor: c.primary }]}>
          <Text style={[s2.lockBannerIcon]}>🔒</Text>
          <View style={{ flex: 1 }}>
            <Text style={[s2.lockTitle, { color: c.primary }]}>Sort committed</Text>
            <Text style={[s2.lockSub, { color: c.foreground }]}>
              By {lockedByName}
              {lockedResult.sort_committed_at
                ? ` · ${new Date(lockedResult.sort_committed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
                : ''}
            </Text>
          </View>
        </View>

        <Text style={[s2.sectionTitle, { marginTop: spacing.lg }]}>Routes</Text>
        {lockedResult.routes.map((route, i) => (
          <RouteCard key={route.id} route={route} index={i} c={c} />
        ))}

        {lockedResult.packages_dropped > 0 && (
          <View style={[s2.droppedBox, { borderColor: c.border }]}>
            <Text style={[s2.droppedTitle, { color: c.mutedForeground }]}>
              {lockedResult.packages_dropped} package(s) excluded (no address)
            </Text>
          </View>
        )}
      </ScrollView>
    );
  }

  // ── Form: select walkers, add OVs, commit ──
  const walkersOnTruck = members.filter(m => m.role === 'walker' || m.role === 'trainee');

  return (
    <ScrollView style={s2.scroll} contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>

      <View style={[s2.infoCard, { borderColor: c.border }]}>
        <Text style={[s2.infoLabel, { color: c.mutedForeground }]}>Assignment</Text>
        <Text style={[s2.infoValue, { color: c.foreground }]}>
          {assignment.date} · {assignment.status.toUpperCase()}
        </Text>
      </View>

      {/* Walker selection */}
      <Text style={s2.sectionTitle}>Walkers / Trainees</Text>
      <Text style={[s2.hint, { color: c.mutedForeground }]}>
        Select who is present on this truck today.
      </Text>
      {walkersOnTruck.length === 0 ? (
        <Text style={[s2.emptyText, { color: c.mutedForeground }]}>No walkers or trainees on this assignment.</Text>
      ) : (
        walkersOnTruck.map(m => {
          const selected = walkerIds.includes(m.employee_id);
          return (
            <TouchableOpacity
              key={m.employee_id}
              style={[s2.memberRow, { borderColor: selected ? c.primary : c.border, backgroundColor: selected ? c.primary + '18' : c.surface }]}
              onPress={() => toggleWalker(m.employee_id)}
              activeOpacity={0.7}
            >
              <View style={[s2.checkBox, { borderColor: selected ? c.primary : c.border, backgroundColor: selected ? c.primary : 'transparent' }]}>
                {selected && <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>✓</Text>}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s2.memberName, { color: c.foreground }]}>{m.employee_name}</Text>
                <Text style={[s2.memberRole, { color: c.mutedForeground }]}>{m.role}</Text>
              </View>
            </TouchableOpacity>
          );
        })
      )}

      {/* OV pairings */}
      <View style={s2.ovHeader}>
        <Text style={s2.sectionTitle}>OV Pairings</Text>
        <TouchableOpacity onPress={addOV} style={[s2.addBtn, { backgroundColor: c.primary }]}>
          <Text style={{ color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold }}>+ Add OV</Text>
        </TouchableOpacity>
      </View>
      <Text style={[s2.hint, { color: c.mutedForeground }]}>
        Oversized items that must travel with a specific bag. Physical observation required.
      </Text>
      {ovs.map((ov, i) => (
        <View key={i} style={[s2.ovRow, { borderColor: c.border, backgroundColor: c.surface }]}>
          <View style={{ flex: 1, gap: spacing.xs }}>
            <TextInput
              style={[s2.input, { borderColor: c.border, color: c.foreground, backgroundColor: c.background }]}
              placeholder="Sort zone (e.g. A-12)"
              placeholderTextColor={c.mutedForeground}
              value={ov.sort_zone}
              onChangeText={v => updateOV(i, 'sort_zone', v)}
            />
            <TextInput
              style={[s2.input, { borderColor: c.border, color: c.foreground, backgroundColor: c.background }]}
              placeholder="Paired bag ID (e.g. Green 5270)"
              placeholderTextColor={c.mutedForeground}
              value={ov.paired_bag_id}
              onChangeText={v => updateOV(i, 'paired_bag_id', v)}
            />
            <View style={{ flexDirection: 'row', gap: spacing.xs }}>
              {SIZE_TIERS.map(tier => (
                <TouchableOpacity
                  key={tier}
                  style={[s2.tierBtn, {
                    borderColor:     ov.size_tier === tier ? c.primary : c.border,
                    backgroundColor: ov.size_tier === tier ? c.primary : c.surface,
                  }]}
                  onPress={() => updateOV(i, 'size_tier', tier)}
                >
                  <Text style={{ color: ov.size_tier === tier ? '#fff' : c.mutedForeground, fontSize: fontSize.xs, fontWeight: fontWeight.semibold }}>
                    {tier}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
          <TouchableOpacity onPress={() => removeOV(i)} style={s2.removeOvBtn}>
            <Text style={{ color: '#EF4444', fontSize: 18 }}>✕</Text>
          </TouchableOpacity>
        </View>
      ))}

      {/* Commit button */}
      <TouchableOpacity
        style={[s2.commitBtn, { backgroundColor: c.primary, opacity: committing ? 0.7 : 1 }]}
        onPress={handleCommit}
        disabled={committing}
        activeOpacity={0.8}
      >
        {committing
          ? <ActivityIndicator size="small" color="#fff" />
          : <Text style={s2.commitBtnText}>Commit Route Sort</Text>
        }
      </TouchableOpacity>

      <View style={{ height: spacing.xl }} />
    </ScrollView>
  );
}

// ── Route card sub-component ──────────────────────────────────────────────────

function RouteCard({ route, index, c }: { route: WalkerRoute; index: number; c: any }) {
  const [open, setOpen] = useState(false);
  const s = styles(c);
  return (
    <TouchableOpacity
      style={[s.routeCard, { borderColor: c.border, backgroundColor: c.surface }]}
      onPress={() => setOpen(o => !o)}
      activeOpacity={0.8}
    >
      <View style={s.routeCardHeader}>
        <Text style={[s.routeCardTitle, { color: c.foreground }]}>Walker {index + 1}</Text>
        <Text style={[s.routeCardMeta, { color: c.mutedForeground }]}>
          {route.total_packages} pkgs · {route.total_bags} bags · {route.planned_trips} trips
        </Text>
        <Text style={{ color: c.mutedForeground, fontSize: 12 }}>{open ? '▲' : '▼'}</Text>
      </View>
      {open && (
        <View style={{ marginTop: spacing.sm, gap: spacing.xs }}>
          {route.trips.map(trip => (
            <View key={trip.id} style={[s.tripRow, { borderColor: c.border }]}>
              <Text style={[s.tripLabel, { color: c.foreground }]}>Trip {trip.trip_number}</Text>
              <Text style={[s.tripDetail, { color: c.mutedForeground }]}>
                Bags: {trip.bag_ids.join(', ')}
              </Text>
            </View>
          ))}
        </View>
      )}
    </TouchableOpacity>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  scroll:          { flex: 1, backgroundColor: c.background },
  center:          { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: c.background },
  emptyTitle:      { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginTop: spacing.sm },
  emptySub:        { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center', paddingHorizontal: spacing.xl },
  emptyText:       { fontSize: fontSize.sm, paddingVertical: spacing.sm },
  sectionTitle:    { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginBottom: spacing.xs },
  hint:            { fontSize: fontSize.xs, marginBottom: spacing.sm },

  infoCard:        { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, backgroundColor: c.surface },
  infoLabel:       { fontSize: fontSize.xs, fontWeight: fontWeight.medium, marginBottom: 2 },
  infoValue:       { fontSize: fontSize.base, fontWeight: fontWeight.semibold },

  memberRow:       { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderRadius: radius.md, marginBottom: spacing.xs },
  checkBox:        { width: 22, height: 22, borderRadius: 4, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  memberName:      { fontSize: fontSize.base, fontWeight: fontWeight.medium },
  memberRole:      { fontSize: fontSize.xs, textTransform: 'capitalize' },

  ovHeader:        { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  addBtn:          { paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.sm },
  ovRow:           { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm, flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  input:           { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs + 2, fontSize: fontSize.sm },
  tierBtn:         { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: radius.sm, borderWidth: 1 },
  removeOvBtn:     { paddingLeft: spacing.xs, paddingTop: spacing.xs },

  commitBtn:       { borderRadius: radius.md, padding: spacing.md, alignItems: 'center', marginTop: spacing.sm },
  commitBtnText:   { color: '#fff', fontSize: fontSize.base, fontWeight: fontWeight.bold },

  lockBanner:      { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderWidth: 1.5, borderRadius: radius.md, padding: spacing.md },
  lockBannerIcon:  { fontSize: 24 },
  lockTitle:       { fontSize: fontSize.base, fontWeight: fontWeight.bold },
  lockSub:         { fontSize: fontSize.sm, marginTop: 2 },

  routeCard:       { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm },
  routeCardHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  routeCardTitle:  { fontSize: fontSize.base, fontWeight: fontWeight.semibold, flex: 1 },
  routeCardMeta:   { fontSize: fontSize.xs },
  tripRow:         { borderWidth: 1, borderRadius: radius.sm, padding: spacing.xs, borderLeftWidth: 3 },
  tripLabel:       { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  tripDetail:      { fontSize: fontSize.xs, marginTop: 2 },

  droppedBox:      { borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm, marginTop: spacing.sm },
  droppedTitle:    { fontSize: fontSize.xs },
});
