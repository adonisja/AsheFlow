import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  Alert, Modal, ScrollView,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

/** AP Sort — mobile-first (drivers and trainers run this AT the anchor point).
 *
 * Rebuilt on the current API (the old screen called /walker-routes/assignment
 * and /walker-routes/commit, which no longer exist):
 *   zone-status (ADR-185 driver-readable commit gate) → commit-sort →
 *   wave-distribution auto-propose (ADR-187/189) → review/override → send.
 */

type CrewMember = {
  employee_id: string;
  name: string;
  role: string;
  paired_trainer_id: string | null;
};

type RouteResp = {
  id: string;
  route_number: number;
  status: string;
  effort_class: string;
  package_count: number;
  wave_number: number;
  assigned_to: string | null;
  assigned_to_name: string | null;
  returned_at: string | null;
};

type Proposal = {
  route_number: number;
  route_id: string;
  employee_id: string;
  employee_name: string;
  effort_class: string;
  auto_proposed: boolean;
};

const EFFORT_COLORS: Record<string, string> = {
  easy: '#0FA870', standard: '#0EA5D8', heavy: '#E8820C', very_heavy: '#E8443A',
};

export default function RouteSortScreen() {
  const c = useColors();
  const { fetchId } = useEmployeeId();
  const s = styles(c);

  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [taId,       setTaId]       = useState<string | null>(null);
  const [truckName,  setTruckName]  = useState<string>('');
  const [zoned,      setZoned]      = useState(false);
  const [zonePkgs,   setZonePkgs]   = useState(0);
  const [crew,       setCrew]       = useState<CrewMember[]>([]);
  const [routes,     setRoutes]     = useState<RouteResp[]>([]);
  const [committing, setCommitting] = useState(false);
  const [proposing,  setProposing]  = useState(false);
  const [proposal,   setProposal]   = useState<Proposal[] | null>(null);
  const [conflicts,  setConflicts]  = useState<string[]>([]);
  const [overridden, setOverridden] = useState<Set<number>>(new Set());
  const [sending,    setSending]    = useState(false);
  const [pickerFor,  setPickerFor]  = useState<number | null>(null);   // route_number being reassigned

  const todayStr = () => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  };

  const load = useCallback(async (opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true);
    const today = todayStr();
    try {
      const eid = await fetchId();
      const disp = await apiClient.get(`/dispatch/${today}`);
      const crews: Record<string, CrewMember[]> = disp.data?.assigned_crews ?? {};
      const truckAssignments: { id?: string; truck_id: string }[] = disp.data?.truck_assignments ?? [];

      const myTruckEntry = Object.entries(crews).find(([, members]) =>
        members.some(m => m.employee_id === eid));
      if (!myTruckEntry) { setTaId(null); return; }
      const [myTruckId, myCrew] = myTruckEntry;
      setCrew(myCrew);

      const ta: any = truckAssignments.find(t => t.truck_id === myTruckId);
      const assignmentId = ta?.id ?? ta?.assignment_id ?? null;
      if (!assignmentId) { setTaId(null); return; }
      setTaId(assignmentId);

      const [zoneRes, routesRes] = await Promise.allSettled([
        apiClient.get(`/sort/${today}/zone-status`),
        apiClient.get(`/walker-routes/${assignmentId}/routes`),
      ]);
      if (zoneRes.status === 'fulfilled') {
        const mine = (zoneRes.value.data?.trucks ?? []).find((t: any) => t.truck_id === myTruckId);
        setZoned(!!mine?.zoned);
        setZonePkgs(mine?.package_count ?? 0);
        setTruckName(mine?.truck_name ?? '');
      }
      setRoutes(routesRes.status === 'fulfilled' ? (routesRes.value.data ?? []) : []);
    } catch {
      setTaId(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // ── Commit sort ──────────────────────────────────────────────────────────

  const commitSort = async () => {
    if (!taId) return;
    setCommitting(true);
    try {
      const res = await apiClient.post('/walker-routes/commit-sort', {
        truck_assignment_id: taId,
        route_date: todayStr(),
      });
      Alert.alert('Sort committed', `${res.data.packages_sorted} packages sorted into ${res.data.routes?.length ?? 0} routes.`);
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not commit the sort.'));
    } finally {
      setCommitting(false);
    }
  };

  // ── Wave distribution ────────────────────────────────────────────────────

  const propose = async () => {
    if (!taId) return;
    setProposing(true);
    try {
      const res = await apiClient.post('/walker-routes/wave-distribution', {
        truck_assignment_id: taId,
        route_date: todayStr(),
        auto_assign: true,
        assignments: [],
        trainer_id: null,
        trainee_id: null,
        trainee_phase: null,
      });
      setProposal(res.data.proposed_assignments ?? []);
      setConflicts(res.data.conflicts ?? []);
      setOverridden(new Set());
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not build a wave proposal.'));
    } finally {
      setProposing(false);
    }
  };

  const overrideAssignee = (routeNumber: number, member: CrewMember) => {
    setProposal(prev => prev?.map(p =>
      p.route_number === routeNumber
        ? { ...p, employee_id: member.employee_id, employee_name: member.name }
        : p) ?? null);
    setOverridden(prev => new Set(prev).add(routeNumber));
    setPickerFor(null);
  };

  const sendWave = async () => {
    if (!taId || !proposal || proposal.length === 0) return;
    setSending(true);
    try {
      // Pairing sync: the manual branch requires trainer_id when a trainee is
      // assigned — derive from dispatch pairing (same as web's D6 derive).
      const pairedTrainee = crew.find(m => m.role === 'trainee' && m.paired_trainer_id);
      await apiClient.post('/walker-routes/wave-distribution', {
        truck_assignment_id: taId,
        route_date: todayStr(),
        auto_assign: false,
        assignments: proposal.map(p => ({
          route_number: p.route_number,
          employee_id: p.employee_id,
          // D9.2 telemetry: accepted-as-proposed vs human-overridden
          auto_proposed: overridden.has(p.route_number) ? false : true,
        })),
        trainer_id: pairedTrainee?.paired_trainer_id ?? null,
        trainee_id: pairedTrainee?.employee_id ?? null,
        trainee_phase: null,
      });
      const sent = proposal.length;
      setProposal(null);
      await load();
      Alert.alert('Wave sent', `${sent} route${sent === 1 ? '' : 's'} assigned. Walkers see them on My Route.`);
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not send the wave.'));
    } finally {
      setSending(false);
    }
  };

  // ── Derived ──────────────────────────────────────────────────────────────

  const unassigned = routes.filter(r => r.status === 'unassigned');
  const active     = routes.filter(r => r.status === 'assigned' || r.status === 'in_progress');
  const completed  = routes.filter(r => r.status === 'completed');
  const pickerOptions = crew.filter(m => m.role !== 'driver');

  if (!loading && !taId) {
    return (
      <ScreenShell edges={[]} noHeader title="AP Sort" subtitle="No truck assignment today."
        refreshing={refreshing} onRefresh={() => load({ refresh: true })}>
        <View style={s.center}>
          <Text style={{ fontSize: 40 }}>🗺️</Text>
          <Text style={s.emptyTitle}>Not on a truck today</Text>
          <Text style={s.emptySub}>AP Sort opens once dispatch assigns you to a truck.</Text>
        </View>
      </ScreenShell>
    );
  }

  return (
    <ScreenShell
      edges={[]} noHeader
      title="AP Sort"
      subtitle={truckName ? `${truckName} · ${todayStr()}` : todayStr()}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load({ refresh: true })}
    >
      {/* Phase: not yet committed */}
      {routes.length === 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          {zoned ? (
            <>
              <Text style={s.cardTitle}>Ready to sort</Text>
              <Text style={s.cardSub}>{zonePkgs} packages zoned to this truck by station sort.</Text>
              <TouchableOpacity style={[s.primaryBtn, { backgroundColor: c.primary }]} onPress={commitSort} disabled={committing}>
                {committing
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={s.primaryBtnText}>Commit Sort — build routes</Text>}
              </TouchableOpacity>
            </>
          ) : (
            <>
              <Text style={s.cardTitle}>Waiting on station sort</Text>
              <Text style={s.cardSub}>This truck has no zoned packages yet — check back after the station finishes sorting.</Text>
            </>
          )}
        </View>
      )}

      {/* Phase: routes exist — wave control */}
      {routes.length > 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          <View style={s.summaryRow}>
            <Summary label="Unassigned" value={unassigned.length} color={unassigned.length > 0 ? '#E8820C' : c.mutedForeground} c={c} />
            <Summary label="Out now" value={active.length} color="#0EA5D8" c={c} />
            <Summary label="Done" value={completed.length} color="#0FA870" c={c} />
          </View>
          {unassigned.length > 0 && (
            <TouchableOpacity style={[s.primaryBtn, { backgroundColor: c.primary }]} onPress={propose} disabled={proposing}>
              {proposing
                ? <ActivityIndicator color="#fff" />
                : <Text style={s.primaryBtnText}>⚡ Distribute Wave ({unassigned.length} route{unassigned.length === 1 ? '' : 's'} waiting)</Text>}
            </TouchableOpacity>
          )}
        </View>
      )}

      {/* Route lists */}
      {[{ label: 'OUT NOW', data: active }, { label: 'UNASSIGNED', data: unassigned }, { label: 'COMPLETED', data: completed }]
        .filter(g => g.data.length > 0)
        .map(g => (
          <View key={g.label}>
            <Text style={s.sectionLabel}>{g.label} · {g.data.length}</Text>
            {g.data.map(r => (
              <View key={r.id} style={[s.routeRow, { backgroundColor: c.card, borderColor: c.border }]}>
                <View style={[s.routeNum, { backgroundColor: (EFFORT_COLORS[r.effort_class] ?? c.primary) + '1E' }]}>
                  <Text style={[s.routeNumText, { color: EFFORT_COLORS[r.effort_class] ?? c.primary }]}>{r.route_number}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[s.routeName, { color: c.foreground }]}>
                    {r.assigned_to_name ?? 'Unassigned'}
                  </Text>
                  <Text style={[s.routeMeta, { color: c.mutedForeground }]}>
                    {r.package_count} pkgs · {r.effort_class} · wave {r.wave_number}
                    {r.returned_at ? ' · returned' : ''}
                  </Text>
                </View>
                <Text style={[s.routeStatus, { color: c.mutedForeground }]}>{r.status.replace('_', ' ')}</Text>
              </View>
            ))}
          </View>
        ))}

      {/* ── Wave proposal sheet ── */}
      {proposal && (
        <Modal transparent animationType="slide" onRequestClose={() => setProposal(null)}>
          <View style={ms.backdrop}>
            <View style={[ms.sheet, { backgroundColor: c.card }]}>
              <Text style={[ms.title, { color: c.foreground }]}>Wave proposal · {proposal.length} route{proposal.length === 1 ? '' : 's'}</Text>
              <Text style={[ms.hint, { color: c.mutedForeground }]}>Tap a row to change who takes it.</Text>

              {conflicts.length > 0 && (
                <View style={[ms.conflictBox, { backgroundColor: '#E8820C15', borderColor: '#E8820C44' }]}>
                  {conflicts.map((cf, i) => (
                    <Text key={i} style={[ms.conflictText, { color: '#B45309' }]}>⚠ {cf}</Text>
                  ))}
                </View>
              )}

              <ScrollView style={{ maxHeight: 340 }}>
                {[...proposal].sort((a, b) => a.route_number - b.route_number).map(p => (
                  <TouchableOpacity
                    key={p.route_number}
                    style={[ms.propRow, { borderBottomColor: c.border }]}
                    onPress={() => setPickerFor(p.route_number)}
                  >
                    <View style={[s.routeNum, { backgroundColor: (EFFORT_COLORS[p.effort_class] ?? c.primary) + '1E' }]}>
                      <Text style={[s.routeNumText, { color: EFFORT_COLORS[p.effort_class] ?? c.primary }]}>{p.route_number}</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={[ms.propName, { color: c.foreground }]}>{p.employee_name}</Text>
                      <Text style={[ms.propMeta, { color: c.mutedForeground }]}>{p.effort_class}</Text>
                    </View>
                    <Text style={[ms.propTag, { color: overridden.has(p.route_number) ? '#E8820C' : c.mutedForeground }]}>
                      {overridden.has(p.route_number) ? 'edited' : 'auto'}
                    </Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>

              <View style={ms.btnRow}>
                <TouchableOpacity style={[ms.cancelBtn, { borderColor: c.border }]} onPress={() => setProposal(null)} disabled={sending}>
                  <Text style={{ color: c.mutedForeground, fontWeight: '600', fontSize: 13 }}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[ms.sendBtn, { backgroundColor: c.primary }]} onPress={sendWave} disabled={sending}>
                  {sending
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>Send Wave</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </View>

          {/* Assignee picker overlays the sheet */}
          {pickerFor !== null && (
            <Modal transparent animationType="fade" onRequestClose={() => setPickerFor(null)}>
              <TouchableOpacity style={ms.backdrop} activeOpacity={1} onPress={() => setPickerFor(null)}>
                <View style={[ms.picker, { backgroundColor: c.card }]}>
                  <Text style={[ms.title, { color: c.foreground }]}>Route {pickerFor} → who takes it?</Text>
                  <ScrollView style={{ maxHeight: 320 }}>
                    {pickerOptions.map(m => (
                      <TouchableOpacity key={m.employee_id} style={[ms.propRow, { borderBottomColor: c.border }]}
                        onPress={() => overrideAssignee(pickerFor, m)}>
                        <Text style={[ms.propName, { color: c.foreground, flex: 1 }]}>{m.name}</Text>
                        <Text style={[ms.propMeta, { color: c.mutedForeground, textTransform: 'capitalize' }]}>{m.role}</Text>
                      </TouchableOpacity>
                    ))}
                  </ScrollView>
                </View>
              </TouchableOpacity>
            </Modal>
          )}
        </Modal>
      )}
    </ScreenShell>
  );
}

function Summary({ label, value, color, c }: { label: string; value: number; color: string; c: ThemeColors }) {
  return (
    <View style={{ flex: 1, alignItems: 'center' }}>
      <Text style={{ fontSize: fontSize.xl, fontWeight: fontWeight.extrabold, color }}>{value}</Text>
      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>{label}</Text>
    </View>
  );
}

const ms = StyleSheet.create({
  backdrop:    { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  sheet:       { borderTopLeftRadius: radius.lg * 1.5, borderTopRightRadius: radius.lg * 1.5, padding: spacing.lg, paddingBottom: spacing.xl },
  picker:      { borderTopLeftRadius: radius.lg * 1.5, borderTopRightRadius: radius.lg * 1.5, padding: spacing.lg, paddingBottom: spacing.xl },
  title:       { fontSize: fontSize.md, fontWeight: fontWeight.bold, marginBottom: 2 },
  hint:        { fontSize: fontSize.xs, marginBottom: spacing.sm },
  conflictBox: { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm },
  conflictText:{ fontSize: fontSize.xs, lineHeight: 17 },
  propRow:     { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.sm, borderBottomWidth: 1 },
  propName:    { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  propMeta:    { fontSize: fontSize.xs },
  propTag:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  btnRow:      { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  cancelBtn:   { flex: 1, borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  sendBtn:     { flex: 2, borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
});

const styles = (c: ThemeColors) => StyleSheet.create({
  center:     { alignItems: 'center', marginTop: 64, gap: spacing.sm, paddingHorizontal: spacing.lg },
  emptyTitle: { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground },
  emptySub:   { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center' },

  card:       { borderRadius: radius.lg, borderWidth: 1, padding: spacing.md, marginBottom: spacing.md },
  cardTitle:  { fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground },
  cardSub:    { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: 2, marginBottom: spacing.sm },
  primaryBtn: { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  primaryBtnText: { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  summaryRow: { flexDirection: 'row', marginBottom: spacing.sm },

  sectionLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, letterSpacing: 0.8, marginBottom: spacing.xs, marginTop: spacing.xs },
  routeRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderRadius: radius.md, borderWidth: 1, padding: spacing.sm, marginBottom: 6 },
  routeNum:   { width: 34, height: 34, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  routeNumText: { fontSize: fontSize.sm, fontWeight: fontWeight.extrabold },
  routeName:  { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  routeMeta:  { fontSize: fontSize.xs, marginTop: 1 },
  routeStatus:{ fontSize: fontSize.xs, textTransform: 'capitalize' },
});
