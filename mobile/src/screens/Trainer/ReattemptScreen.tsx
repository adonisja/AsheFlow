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

/**
 * Reattempt management for drivers and captains (ROUTE_SORT_ROLES).
 *
 * Flow:
 *   1. Load truck assignment id from today's dispatch.
 *   2. GET /rts/reattempts/{taId}          — existing assignments (all statuses).
 *   3. GET /rts/reattempts/{taId}/bundle-suggest — unassigned pool grouped by
 *      block_key (only available after 15:00).
 *   4. Captain taps a bundle → picker selects assignee → POST /rts/reattempts
 *      creates an assignment per package in the bundle.
 *   5. Captain can PATCH status on an existing assignment (attempted, delivered,
 *      failed_again).
 */

type CrewMember = {
  employee_id: string;
  name: string;
  role: string;
};

type BundleSuggestion = {
  rts_package_ids: string[];
  tba_numbers: string[];
  block_keys: string[];
  package_count: number;
};

type ReattemptAssignment = {
  id: string;
  rts_package_id: string;
  status: string;
  original_walker_name: string | null;
  assigned_to: string | null;
  assigned_to_name: string | null;
  cutoff_at: string;
  outcome_notes: string | null;
  created_at: string;
};

const STATUS_COLORS: Record<string, string> = {
  pending:      '#E8820C',
  assigned:     '#0EA5D8',
  attempted:    '#8B5CF6',
  delivered:    '#0FA870',
  failed_again: '#E8443A',
};

const STATUS_LABELS: Record<string, string> = {
  pending:      'Pending',
  assigned:     'Assigned',
  attempted:    'Attempted',
  delivered:    'Delivered',
  failed_again: 'Failed again',
};

const OUTCOME_STATUSES = ['attempted', 'delivered', 'failed_again'] as const;

export default function ReattemptScreen() {
  const c = useColors();
  const { fetchId } = useEmployeeId();
  const s = styles(c);

  const [loading,     setLoading]     = useState(true);
  const [refreshing,  setRefreshing]  = useState(false);
  const [taId,        setTaId]        = useState<string | null>(null);
  const [crew,        setCrew]        = useState<CrewMember[]>([]);
  const [assignments, setAssignments] = useState<ReattemptAssignment[]>([]);
  const [bundles,     setBundles]     = useState<BundleSuggestion[]>([]);
  const [poolError,   setPoolError]   = useState<string | null>(null);

  // UI state
  const [assignModal, setAssignModal]   = useState<BundleSuggestion | null>(null);
  const [assigning,   setAssigning]     = useState(false);
  const [pickedEmp,   setPickedEmp]     = useState<CrewMember | null>(null);
  const [statusModal, setStatusModal]   = useState<ReattemptAssignment | null>(null);
  const [patching,    setPatching]      = useState(false);

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
      const truckAssignments: { id?: string; assignment_id?: string; truck_id: string }[] = disp.data?.truck_assignments ?? [];

      const myTruckEntry = Object.entries(crews).find(([, members]) =>
        members.some(m => m.employee_id === eid));
      if (!myTruckEntry) { setTaId(null); return; }
      const [myTruckId, myCrew] = myTruckEntry;
      setCrew(myCrew.filter(m => m.role !== 'driver'));

      const ta = truckAssignments.find(t => t.truck_id === myTruckId);
      const assignmentId = ta?.id ?? ta?.assignment_id ?? null;
      if (!assignmentId) { setTaId(null); return; }
      setTaId(assignmentId);

      const [assignRes, bundleRes] = await Promise.allSettled([
        apiClient.get(`/rts/reattempts/${assignmentId}`),
        apiClient.get(`/rts/reattempts/${assignmentId}/bundle-suggest`),
      ]);

      setAssignments(assignRes.status === 'fulfilled' ? (assignRes.value.data ?? []) : []);

      if (bundleRes.status === 'fulfilled') {
        setBundles(bundleRes.value.data ?? []);
        setPoolError(null);
      } else {
        setBundles([]);
        const err = (bundleRes.reason as any)?.response?.data?.detail ?? null;
        setPoolError(typeof err === 'string' ? err : null);
      }
    } catch {
      setTaId(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // ── Assign a bundle to a crew member ────────────────────────────────────

  const openAssign = (bundle: BundleSuggestion) => {
    setPickedEmp(crew[0] ?? null);
    setAssignModal(bundle);
  };

  const confirmAssign = async () => {
    if (!assignModal || !pickedEmp) return;
    setAssigning(true);
    try {
      await Promise.all(
        assignModal.rts_package_ids.map(pid =>
          apiClient.post('/rts/reattempts', {
            rts_package_id: pid,
            assigned_to: pickedEmp.employee_id,
          }),
        ),
      );
      setAssignModal(null);
      await load();
      Alert.alert(
        'Assigned',
        `${assignModal.package_count} package${assignModal.package_count === 1 ? '' : 's'} assigned to ${pickedEmp.name}.`,
      );
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not create the reattempt assignment.'));
    } finally {
      setAssigning(false);
    }
  };

  // ── Update assignment status ─────────────────────────────────────────────

  const patchStatus = async (id: string, newStatus: string) => {
    setPatching(true);
    try {
      await apiClient.patch(`/rts/reattempts/${id}`, { status: newStatus });
      setStatusModal(null);
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not update the status.'));
    } finally {
      setPatching(false);
    }
  };

  // ── Derived ──────────────────────────────────────────────────────────────

  const pending   = assignments.filter(a => a.status === 'pending' || a.status === 'assigned');
  const completed = assignments.filter(a => a.status === 'delivered' || a.status === 'failed_again' || a.status === 'attempted');

  const cutoffTime = assignments[0]?.cutoff_at
    ? new Date(assignments[0].cutoff_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : '6:30 PM';

  if (!loading && !taId) {
    return (
      <ScreenShell title="Reattempts" subtitle="No truck assignment today."
        refreshing={refreshing} onRefresh={() => load({ refresh: true })}>
        <View style={s.center}>
          <Text style={{ fontSize: 40 }}>📦</Text>
          <Text style={s.emptyTitle}>Not on a truck today</Text>
          <Text style={s.emptySub}>Reattempt management opens once dispatch assigns you to a truck.</Text>
        </View>
      </ScreenShell>
    );
  }

  return (
    <ScreenShell
      title="Reattempts"
      subtitle={`Same-day redelivery · cutoff ${cutoffTime}`}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load({ refresh: true })}
    >
      {/* Bundle suggestions — the captain's primary action */}
      <Text style={s.sectionLabel}>READY TO ASSIGN · {bundles.length}</Text>

      {poolError ? (
        <View style={[s.card, { backgroundColor: c.card, borderColor: '#E8820C44' }]}>
          <Text style={[s.cardSub, { color: c.mutedForeground, marginBottom: 0 }]}>⏳ {poolError}</Text>
        </View>
      ) : bundles.length === 0 ? (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={[s.cardSub, { color: c.mutedForeground, marginBottom: 0 }]}>
            {assignments.length > 0
              ? 'All reattemptable packages are already assigned.'
              : 'No reattemptable packages yet — they appear as walkers return.'}
          </Text>
        </View>
      ) : (
        bundles.map((b, i) => (
          <BundleCard key={i} bundle={b} c={c} s={s} onAssign={() => openAssign(b)} />
        ))
      )}

      {/* Active assignments */}
      {pending.length > 0 && (
        <>
          <Text style={s.sectionLabel}>IN PROGRESS · {pending.length}</Text>
          {pending.map(a => (
            <AssignmentCard key={a.id} assignment={a} c={c} s={s} onPress={() => setStatusModal(a)} />
          ))}
        </>
      )}

      {/* Closed assignments */}
      {completed.length > 0 && (
        <>
          <Text style={s.sectionLabel}>CLOSED · {completed.length}</Text>
          {completed.map(a => (
            <AssignmentCard key={a.id} assignment={a} c={c} s={s} onPress={() => setStatusModal(a)} />
          ))}
        </>
      )}

      {/* Assign bundle modal */}
      {assignModal && (
        <Modal transparent animationType="slide" onRequestClose={() => setAssignModal(null)}>
          <View style={ms.backdrop}>
            <View style={[ms.sheet, { backgroundColor: c.card }]}>
              <Text style={[ms.title, { color: c.foreground }]}>
                Assign {assignModal.package_count} package{assignModal.package_count === 1 ? '' : 's'}
              </Text>

              {/* Block keys */}
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: spacing.sm }}>
                {assignModal.block_keys.map(bk => (
                  <View key={bk} style={{ backgroundColor: c.primaryLight, borderRadius: radius.xs, paddingHorizontal: 8, paddingVertical: 3 }}>
                    <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.primary }}>{bk}</Text>
                  </View>
                ))}
              </View>

              {/* TBAs */}
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: spacing.md }}>
                {assignModal.tba_numbers.map(tba => (
                  <View key={tba} style={{ backgroundColor: c.surfaceMuted, borderRadius: radius.sm, paddingHorizontal: 6, paddingVertical: 2, borderWidth: 1, borderColor: c.border }}>
                    <Text style={{ fontSize: fontSize.xs, color: c.foreground, fontVariant: ['tabular-nums'] }}>…{tba.slice(-8)}</Text>
                  </View>
                ))}
              </View>

              {/* Assignee picker */}
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, marginBottom: spacing.xs }}>ASSIGN TO</Text>
              <ScrollView style={{ maxHeight: 220, marginBottom: spacing.md }}>
                {crew.length === 0 ? (
                  <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground, fontStyle: 'italic' }}>No crew members found.</Text>
                ) : crew.map(m => (
                  <TouchableOpacity
                    key={m.employee_id}
                    style={[ms.crewRow, { borderBottomColor: c.border }, pickedEmp?.employee_id === m.employee_id && { backgroundColor: c.primaryLight }]}
                    onPress={() => setPickedEmp(m)}
                  >
                    <View style={[ms.radio, { borderColor: pickedEmp?.employee_id === m.employee_id ? c.primary : c.border }]}>
                      {pickedEmp?.employee_id === m.employee_id && <View style={[ms.radioDot, { backgroundColor: c.primary }]} />}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground }}>{m.name}</Text>
                      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'capitalize' }}>{m.role}</Text>
                    </View>
                  </TouchableOpacity>
                ))}
              </ScrollView>

              <View style={ms.btnRow}>
                <TouchableOpacity style={[ms.cancelBtn, { borderColor: c.border }]} onPress={() => setAssignModal(null)} disabled={assigning}>
                  <Text style={{ color: c.mutedForeground, fontWeight: '600', fontSize: 13 }}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[ms.sendBtn, { backgroundColor: pickedEmp ? c.primary : c.border }]}
                  onPress={confirmAssign}
                  disabled={assigning || !pickedEmp}
                >
                  {assigning
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>Assign</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </Modal>
      )}

      {/* Status update modal */}
      {statusModal && (
        <Modal transparent animationType="slide" onRequestClose={() => setStatusModal(null)}>
          <View style={ms.backdrop}>
            <View style={[ms.sheet, { backgroundColor: c.card }]}>
              <Text style={[ms.title, { color: c.foreground }]}>Update outcome</Text>
              <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.md }}>
                Assigned to {statusModal.assigned_to_name ?? 'Unassigned'}
                {statusModal.original_walker_name ? ` · originally ${statusModal.original_walker_name}` : ''}
              </Text>
              {OUTCOME_STATUSES.map(st => (
                <TouchableOpacity
                  key={st}
                  style={[ms.crewRow, { borderBottomColor: c.border }]}
                  onPress={() => patchStatus(statusModal.id, st)}
                  disabled={patching}
                >
                  <View style={[
                    { width: 10, height: 10, borderRadius: 5, backgroundColor: STATUS_COLORS[st] ?? c.mutedForeground, marginRight: spacing.sm },
                  ]} />
                  <Text style={{ fontSize: fontSize.sm, color: c.foreground, flex: 1 }}>{STATUS_LABELS[st]}</Text>
                  {patching && <ActivityIndicator size="small" color={c.primary} />}
                </TouchableOpacity>
              ))}
              <TouchableOpacity style={[ms.cancelBtn, { borderColor: c.border, marginTop: spacing.md, alignSelf: 'stretch', alignItems: 'center' }]} onPress={() => setStatusModal(null)} disabled={patching}>
                <Text style={{ color: c.mutedForeground, fontWeight: '600', fontSize: 13 }}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
      )}
    </ScreenShell>
  );
}

// ── Bundle card ────────────────────────────────────────────────────────────

function BundleCard({ bundle, c, s, onAssign }: {
  bundle: BundleSuggestion; c: ThemeColors; s: ReturnType<typeof styles>; onAssign: () => void;
}) {
  return (
    <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
      <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm }}>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: spacing.xs }}>
            {bundle.block_keys.length > 0
              ? bundle.block_keys.map(bk => (
                  <View key={bk} style={{ backgroundColor: c.primaryLight, borderRadius: radius.xs, paddingHorizontal: 6, paddingVertical: 2 }}>
                    <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.primary }}>{bk}</Text>
                  </View>
                ))
              : <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, fontStyle: 'italic' }}>No block key</Text>
            }
          </View>
          <Text style={[s.cardSub, { marginBottom: spacing.xs }]}>
            {bundle.package_count} package{bundle.package_count === 1 ? '' : 's'}
          </Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 5 }}>
            {bundle.tba_numbers.slice(0, 6).map(tba => (
              <View key={tba} style={{ backgroundColor: c.surfaceMuted, borderRadius: radius.sm, paddingHorizontal: 6, paddingVertical: 2 }}>
                <Text style={{ fontSize: 10, color: c.foreground, fontVariant: ['tabular-nums'] }}>…{tba.slice(-8)}</Text>
              </View>
            ))}
            {bundle.tba_numbers.length > 6 && (
              <Text style={{ fontSize: 10, color: c.mutedForeground, alignSelf: 'center' }}>+{bundle.tba_numbers.length - 6} more</Text>
            )}
          </View>
        </View>
        <TouchableOpacity
          style={{ backgroundColor: c.primary, borderRadius: radius.md, paddingHorizontal: spacing.sm + 4, paddingVertical: spacing.sm, alignSelf: 'flex-start' }}
          onPress={onAssign}
        >
          <Text style={{ color: '#fff', fontSize: fontSize.xs, fontWeight: fontWeight.bold }}>Assign</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

// ── Assignment card ────────────────────────────────────────────────────────

function AssignmentCard({ assignment: a, c, s, onPress }: {
  assignment: ReattemptAssignment; c: ThemeColors; s: ReturnType<typeof styles>; onPress: () => void;
}) {
  const statusColor = STATUS_COLORS[a.status] ?? c.mutedForeground;
  const isCloseable = a.status === 'assigned' || a.status === 'attempted';

  return (
    <TouchableOpacity
      style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}
      onPress={onPress}
      activeOpacity={0.75}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground }}>
            {a.assigned_to_name ?? 'Unassigned'}
          </Text>
          {a.original_walker_name && (
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>
              Originally: {a.original_walker_name}
            </Text>
          )}
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 1 }}>
            Cutoff {new Date(a.cutoff_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          </Text>
          {a.outcome_notes && (
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, fontStyle: 'italic', marginTop: 2 }}>{a.outcome_notes}</Text>
          )}
        </View>
        <View style={{ alignItems: 'flex-end', gap: 4 }}>
          <View style={{ backgroundColor: statusColor + '1E', borderRadius: radius.full, paddingHorizontal: spacing.sm, paddingVertical: 3 }}>
            <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: statusColor }}>{STATUS_LABELS[a.status] ?? a.status}</Text>
          </View>
          {isCloseable && (
            <Text style={{ fontSize: 10, color: c.mutedForeground }}>Tap to update</Text>
          )}
        </View>
      </View>
    </TouchableOpacity>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────

const ms = StyleSheet.create({
  backdrop:   { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  sheet:      { borderTopLeftRadius: radius.lg * 1.5, borderTopRightRadius: radius.lg * 1.5, padding: spacing.lg, paddingBottom: spacing.xl },
  title:      { fontSize: fontSize.md, fontWeight: fontWeight.bold, marginBottom: spacing.sm },
  crewRow:    { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.sm + 2, borderBottomWidth: 1, paddingHorizontal: 4, borderRadius: radius.sm },
  radio:      { width: 18, height: 18, borderRadius: 9, borderWidth: 2, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  radioDot:   { width: 8, height: 8, borderRadius: 4 },
  btnRow:     { flexDirection: 'row', gap: spacing.sm },
  cancelBtn:  { flex: 1, borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  sendBtn:    { flex: 2, borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
});

const styles = (c: ThemeColors) => StyleSheet.create({
  center:       { alignItems: 'center', marginTop: 64, gap: spacing.sm, paddingHorizontal: spacing.lg },
  emptyTitle:   { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground },
  emptySub:     { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center' },
  sectionLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, letterSpacing: 0.8, marginBottom: spacing.xs, marginTop: spacing.xs },
  card:         { borderRadius: radius.lg, borderWidth: 1, padding: spacing.md, marginBottom: spacing.sm },
  cardSub:      { fontSize: fontSize.sm, color: c.mutedForeground, marginBottom: spacing.sm },
});
