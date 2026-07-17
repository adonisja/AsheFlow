import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type CrewMember = {
  id: string;
  name: string;
  role: string;
  paired_trainer_id: string | null;
};

type Transfer = {
  to_truck_name: string;
  from_truck_name: string;
  transferred_at: string;
};

type ConfirmStatus = 'pending' | 'confirmed' | 'declined';

/** The truck's current active anchor point (where the crew meets the driver). */
type AnchorPoint = {
  location: string;
  eta: string | null;
  status: string;                 // preliminary | arrived
  sequence: number;               // > 1 → the AP was relocated from an earlier spot
  notes: string | null;
  submitted_at: string;           // when the driver posted this AP
  arrived_at: string | null;
  confirmed_by_name?: string | null;
  is_running_late: boolean;
  expected_departure_at: string | null;
};

type Assignment = {
  truck_name: string;
  role: string;
  // dispatch phase: 'planned' | 'active' | 'completed'
  dispatchPhase: 'planned' | 'active' | 'completed';
  crew: CrewMember[];
  transfer: Transfer | null;
  /** Who I'm paired with (trainee → their trainer, trainer → their trainees). */
  pairedNames: string[];
  confirmations: Record<string, ConfirmStatus>;
  /** TruckAssignment id — needed for the AP-arrival confirmation. */
  assignmentId: string | null;
  /** My ap_arrived_at stamp (paired trainees confirm arrival from here). */
  apArrivedAt: string | null;
  /** The truck's current active anchor point (null until the driver sets one). */
  anchorPoint: AnchorPoint | null;
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

/** Sections longer than this start collapsed — a 20+ walker roster shouldn't
 * bury the page; headers stay tappable to expand. */
const COLLAPSE_THRESHOLD = 6;

export default function TodayAssignmentScreen() {
  const c = useColors();
  const navigation = useNavigation();
  const { fetchId, cachedId } = useEmployeeId();

  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded,   setExpanded]   = useState<Record<string, boolean>>({});
  const [responding, setResponding] = useState<ConfirmStatus | null>(null);

  const todayLocal = new Date();
  const today = `${todayLocal.getFullYear()}-${String(todayLocal.getMonth() + 1).padStart(2, '0')}-${String(todayLocal.getDate()).padStart(2, '0')}`;

  const load = useCallback(async () => {
    const eid = await fetchId();
    if (!eid) return;
    try {
      const [schedRes, dispatchRes, transferRes, confRes] = await Promise.allSettled([
        apiClient.get(`/schedule/${eid}?start_date=${today}&end_date=${today}`),
        apiClient.get(`/dispatch/${today}`),
        apiClient.get(`/truck-transfers/mine?date=${today}`),
        apiClient.get(`/dispatch/${today}/confirmations`),
      ]);

      const entry = schedRes.status === 'fulfilled' ? (schedRes.value.data ?? [])[0] : null;
      if (!entry || entry.status !== 'Assigned' || !entry.truck_name) {
        setAssignment(null);
        return;
      }

      const me = (entry.crew ?? []).find((m: any) => m.id === eid);

      // Determine dispatch phase + my pairing from the dispatch response.
      let dispatchPhase: Assignment['dispatchPhase'] = 'planned';
      const pairedNames: string[] = [];
      let assignmentId: string | null = null;
      let apArrivedAt: string | null = null;
      let myTruckId: string | null = null;
      if (dispatchRes.status === 'fulfilled') {
        const dispatch = dispatchRes.value.data;
        const assignedCrews: Record<string, CrewMember[] & { employee_id?: string }[]> =
          dispatch?.assigned_crews ?? {};
        const truckAssignments: { truck_id: string; status: string }[] = dispatch?.truck_assignments ?? [];

        const myTruckEntry = Object.entries(assignedCrews).find(([, crew]) =>
          (crew as any[]).some((m) => m.employee_id === eid),
        );

        if (myTruckEntry) {
          const [entryTruckId, myCrew] = myTruckEntry as [string, any[]];
          myTruckId = entryTruckId;
          const ta: any = truckAssignments.find((t) => t.truck_id === myTruckId);
          if (ta?.status === 'completed') dispatchPhase = 'completed';
          else if (ta?.status === 'active') dispatchPhase = 'active';
          assignmentId = ta?.assignment_id ?? null;

          // My arrival stamp (ADR-145 flow: trainee confirms from here).
          if (assignmentId) {
            try {
              const members = await apiClient.get(`/assignment-members/${assignmentId}`);
              const me2 = (members.data ?? []).find((m: any) => m.employee_id === eid);
              apArrivedAt = me2?.ap_arrived_at ?? null;
            } catch { /* best-effort */ }
          }

          // Pairing: trainee → their trainer's name; trainer → their trainees.
          const myEntry = myCrew.find((m) => m.employee_id === eid);
          if (myEntry?.role === 'trainee' && myEntry.paired_trainer_id) {
            const trainer = myCrew.find((m) => m.employee_id === myEntry.paired_trainer_id);
            if (trainer) pairedNames.push(trainer.name);
          } else if (myEntry?.role === 'trainer') {
            for (const m of myCrew) {
              if (m.role === 'trainee' && m.paired_trainer_id === eid) pairedNames.push(m.name);
            }
          }
        }
      }

      // The truck's active anchor point (where the crew meets the driver). All
      // crew see it — location, ETA, arrival status, notes, relocation. Best-effort.
      let anchorPoint: AnchorPoint | null = null;
      if (myTruckId) {
        try {
          const apRes = await apiClient.get(`/anchor-points/truck/${myTruckId}/active`);
          const ap = apRes.data;
          anchorPoint = ap ? {
            location: ap.location,
            eta: ap.eta ?? null,
            status: ap.status,
            sequence: ap.sequence ?? 1,
            notes: ap.notes ?? null,
            submitted_at: ap.submitted_at,
            arrived_at: ap.arrived_at ?? null,
            confirmed_by_name: ap.confirmed_by_name ?? null,
            is_running_late: !!ap.is_running_late,
            expected_departure_at: ap.expected_departure_at ?? null,
          } : null;
        } catch { /* best-effort — no AP yet */ }
      }

      // Most recent transfer for today (last element — ordered by transferred_at asc)
      const transferList: Transfer[] = transferRes.status === 'fulfilled' ? transferRes.value.data ?? [] : [];
      const transfer = transferList.length > 0 ? transferList[transferList.length - 1] : null;

      const confirmations: Record<string, ConfirmStatus> =
        confRes.status === 'fulfilled' ? (confRes.value.data?.confirmations ?? confRes.value.data ?? {}) : {};

      setAssignment({
        truck_name: entry.truck_name,
        role: me?.role ?? 'unknown',
        dispatchPhase,
        crew: entry.crew ?? [],
        transfer,
        pairedNames,
        confirmations,
        assignmentId,
        apArrivedAt,
        anchorPoint,
      });
    } catch {
      setAssignment(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [today, fetchId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const [arriving, setArriving] = useState(false);

  const confirmApArrival = async () => {
    if (!assignment?.assignmentId) return;
    setArriving(true);
    try {
      const res = await apiClient.post('/walker-routes/ap-arrival', {
        truck_assignment_id: assignment.assignmentId,
      });
      setAssignment(prev => prev ? { ...prev, apArrivedAt: res.data?.arrived_at ?? new Date().toISOString() } : prev);
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not confirm your arrival.'));
    } finally {
      setArriving(false);
    }
  };

  const respond = async (status: 'confirmed' | 'declined') => {
    const eid = cachedId.current;
    if (!eid || responding) return;
    setResponding(status);
    try {
      await apiClient.post(`/dispatch/${today}/confirmations`, { employee_id: eid, status });
      setAssignment(prev => prev
        ? { ...prev, confirmations: { ...prev.confirmations, [eid]: status } }
        : prev);
    } catch {
      // leave state as-is; pull-to-refresh recovers
    } finally {
      setResponding(null);
    }
  };

  const s = styles(c);

  if (!loading && !assignment) {
    return (
      <ScreenShell title="Today's Assignment" subtitle={today} onBack={navigation.canGoBack() ? () => navigation.goBack() : undefined}>
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

  const myId = cachedId.current ?? '';
  const myStatus: ConfirmStatus = assignment?.confirmations[myId] ?? 'pending';
  const confirmationsKnown = Object.keys(assignment?.confirmations ?? {}).length > 0;

  const isExpanded = (role: string) =>
    expanded[role] ?? (grouped[role].length <= COLLAPSE_THRESHOLD);

  const statusGlyph = (memberId: string) => {
    if (!confirmationsKnown) return null;
    const st = assignment?.confirmations[memberId];
    if (st === 'confirmed') return <Text style={[s.confirmGlyph, { color: '#0FA870' }]}>✓</Text>;
    if (st === 'declined')  return <Text style={[s.confirmGlyph, { color: '#E8443A' }]}>✗</Text>;
    return <Text style={[s.confirmGlyph, { color: c.mutedForeground }]}>·</Text>;
  };

  return (
    <ScreenShell
      title="Today's Assignment"
      subtitle={today}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); load(); }}
      onBack={navigation.canGoBack() ? () => navigation.goBack() : undefined}
    >
      {/* Truck + my role + pairing */}
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

          <View style={s.roleRow}>
            <View style={{ flex: 1 }}>
              <Text style={s.myRoleLabel}>Your Role</Text>
              <View style={[s.myRolePill, { backgroundColor: (ROLE_COLORS[assignment.role] ?? c.primary) + '18' }]}>
                <Text style={[s.myRoleText, { color: ROLE_COLORS[assignment.role] ?? c.primary }]}>
                  {ROLE_LABELS[assignment.role] ?? assignment.role}
                </Text>
              </View>
            </View>
            {assignment.pairedNames.length > 0 && (
              <View style={{ flex: 1 }}>
                <Text style={s.myRoleLabel}>
                  {assignment.role === 'trainer' ? 'Your Trainee' : 'Your Trainer'}
                </Text>
                {assignment.pairedNames.map(n => (
                  <Text key={n} style={s.pairedName}>{n}</Text>
                ))}
              </View>
            )}
          </View>

          {/* ADR-145: paired trainee confirms physical AP arrival — this
              notifies their trainer, who then runs the 1.5× rebalance. */}
          {assignment.role === 'trainee' && assignment.pairedNames.length > 0
            && assignment.dispatchPhase !== 'planned' && (
            assignment.apArrivedAt ? (
              <View style={[s.arrivedBanner, { backgroundColor: c.success + '15' }]}>
                <Text style={[s.arrivedBannerText, { color: c.success }]}>
                  📍 Arrival confirmed {new Date(assignment.apArrivedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} — your trainer has been notified
                </Text>
              </View>
            ) : (
              <TouchableOpacity
                style={[s.arriveBtn, { backgroundColor: c.primary }]}
                onPress={confirmApArrival}
                disabled={arriving}
              >
                {arriving
                  ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={s.arriveBtnText}>📍 I've arrived at the AP</Text>}
              </TouchableOpacity>
            )
          )}
        </View>
      )}

      {/* Anchor Point — where the crew meets the driver. Shown to all crew once
          the driver has set an AP: location + ETA + arrival status + notes, plus
          relocation ("moved to a new spot") and running-late signals. */}
      {assignment?.anchorPoint && (() => {
        const ap = assignment.anchorPoint;
        const arrived = ap.status === 'arrived';
        const fmtT = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        return (
          <View style={[s.apCard, {
            backgroundColor: c.card, borderColor: ap.is_running_late ? '#E8443A' : c.border,
          }]}>
            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
              <Text style={[s.apLabel, { color: c.mutedForeground }]}>ANCHOR POINT</Text>
              <View style={{
                backgroundColor: (arrived ? '#0FA870' : ap.is_running_late ? '#E8443A' : '#0EA5D8') + '22',
                borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2,
              }}>
                <Text style={{ fontSize: 11, fontWeight: '700',
                  color: arrived ? '#0FA870' : ap.is_running_late ? '#E8443A' : '#0EA5D8' }}>
                  {arrived ? 'Arrived' : ap.is_running_late ? 'Running late' : 'En route'}
                </Text>
              </View>
            </View>

            <Text style={[s.apLocation, { color: c.foreground }]}>📍 {ap.location}</Text>

            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 4 }}>
              {ap.submitted_at && (
                <Text style={[s.apMeta, { color: c.mutedForeground }]}>Set {fmtT(ap.submitted_at)}</Text>
              )}
              {ap.eta && !arrived && (
                <Text style={[s.apMeta, { color: c.mutedForeground }]}>ETA {ap.eta}</Text>
              )}
              {arrived && ap.arrived_at && (
                <Text style={[s.apMeta, { color: c.mutedForeground }]}>Arrived {fmtT(ap.arrived_at)}</Text>
              )}
              {arrived && ap.confirmed_by_name && (
                <Text style={[s.apMeta, { color: c.mutedForeground }]}>Confirmed by {ap.confirmed_by_name}</Text>
              )}
              {ap.sequence > 1 && (
                <Text style={[s.apMeta, { color: '#E8820C' }]}>⇄ Relocated (spot #{ap.sequence})</Text>
              )}
              {ap.expected_departure_at && (
                <Text style={[s.apMeta, { color: c.mutedForeground }]}>Leaving ~{fmtT(ap.expected_departure_at)}</Text>
              )}
            </View>

            {ap.notes ? (
              <Text style={[s.apNotes, { color: c.foreground }]}>“{ap.notes}”</Text>
            ) : null}
          </View>
        );
      })()}

      {/* No AP yet — the tab is named "Anchor Point", so say so explicitly rather
          than render nothing. Shown once dispatch is published (before that, the
          planned hint below explains the state). */}
      {assignment && !assignment.anchorPoint && assignment.dispatchPhase !== 'planned' && (
        <View style={s.apPendingCard}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm }}>
            <Text style={[s.apLabel, { color: c.mutedForeground }]}>ANCHOR POINT</Text>
            <View style={[s.apPendingBadge, { backgroundColor: c.surfaceMuted, borderColor: c.border }]}>
              <View style={[s.apPendingDot, { backgroundColor: c.mutedForeground }]} />
              <Text style={[s.apPendingBadgeText, { color: c.mutedForeground }]}>Not set</Text>
            </View>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md }}>
            <View style={[s.apPendingIconWell, { backgroundColor: c.surfaceMuted, borderColor: c.border }]}>
              <Text style={{ fontSize: 22, opacity: 0.5 }}>📍</Text>
            </View>
            <Text style={[s.apPendingText, { color: c.mutedForeground }]}>
              {assignment.truck_name}'s driver hasn't set an anchor point yet. It appears here with the
              meet-up location and ETA once they post it — pull down to refresh.
            </Text>
          </View>
        </View>
      )}

      {/* Pre-publish: make it clear why there's nothing to confirm yet */}
      {assignment?.dispatchPhase === 'planned' && (
        <View style={s.plannedHint}>
          <Text style={s.plannedHintText}>
            Dispatch isn't published yet — attendance confirmation opens once dispatch publishes.
          </Text>
        </View>
      )}

      {/* Attendance confirmation — the one action this page exists for */}
      {assignment?.dispatchPhase === 'active' && (
        myStatus === 'pending' ? (
          <View style={s.confirmCard}>
            <Text style={s.confirmTitle}>Confirm your attendance</Text>
            <Text style={s.confirmSub}>Dispatch is waiting on your response for today.</Text>
            <View style={s.confirmBtnRow}>
              <TouchableOpacity
                style={[s.confirmBtn, { backgroundColor: '#0FA870' }]}
                onPress={() => respond('confirmed')}
                disabled={responding !== null}
              >
                {responding === 'confirmed'
                  ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={s.confirmBtnText}>✓  I'll be there</Text>}
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.confirmBtn, s.declineBtn]}
                onPress={() => respond('declined')}
                disabled={responding !== null}
              >
                {responding === 'declined'
                  ? <ActivityIndicator color="#E8443A" size="small" />
                  : <Text style={[s.confirmBtnText, { color: '#E8443A' }]}>Can't make it</Text>}
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <View style={[s.respondedCard, myStatus === 'confirmed' ? s.respondedOk : s.respondedNo]}>
            <Text style={[s.respondedText, { color: myStatus === 'confirmed' ? '#0FA870' : '#E8443A' }]}>
              {myStatus === 'confirmed' ? "✓ You're confirmed for today" : '✗ You declined today'}
            </Text>
          </View>
        )
      )}

      {/* Transfer banner — shown when employee was moved mid-day */}
      {assignment?.transfer && (
        <View style={s.transferCard}>
          <Text style={s.transferLabel}>TRANSFERRED</Text>
          <Text style={s.transferText}>
            Moved from <Text style={s.transferBold}>{assignment.transfer.from_truck_name}</Text> to{' '}
            <Text style={s.transferBold}>{assignment.transfer.to_truck_name}</Text>
          </Text>
          <Text style={s.transferTime}>
            {new Date(assignment.transfer.transferred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </Text>
        </View>
      )}

      {/* Crew — grouped by role; large sections start collapsed */}
      {roleOrder.map(role => {
        const members = grouped[role];
        const open = isExpanded(role);
        const confirmedCount = confirmationsKnown
          ? members.filter(m => assignment?.confirmations[m.id] === 'confirmed').length
          : null;
        return (
          <View key={role} style={s.section}>
            <TouchableOpacity
              style={s.sectionHeader}
              onPress={() => setExpanded(prev => ({ ...prev, [role]: !open }))}
              activeOpacity={0.7}
            >
              <View style={[s.roleDot, { backgroundColor: ROLE_COLORS[role] ?? c.primary }]} />
              <Text style={s.sectionTitle}>{ROLE_LABELS[role] ?? role}s</Text>
              <Text style={s.sectionCount}>
                {confirmedCount !== null ? `${confirmedCount}/${members.length} confirmed` : members.length}
              </Text>
              <Text style={s.chevron}>{open ? '▾' : '▸'}</Text>
            </TouchableOpacity>
            {open && members.map((m, i) => (
              <View
                key={m.id}
                style={[
                  s.memberRow,
                  i < members.length - 1 && s.memberRowBorder,
                  m.id === myId && s.memberRowMe,
                ]}
              >
                <View style={[s.avatar, { backgroundColor: (ROLE_COLORS[role] ?? c.primary) + '18' }]}>
                  <Text style={[s.avatarText, { color: ROLE_COLORS[role] ?? c.primary }]}>
                    {m.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
                  </Text>
                </View>
                <Text style={[s.memberName, m.id === myId && { color: c.primary, fontWeight: fontWeight.semibold }]}>
                  {m.name}{m.id === myId ? ' (you)' : ''}
                </Text>
                {statusGlyph(m.id)}
              </View>
            ))}
          </View>
        );
      })}
    </ScreenShell>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  heroCard:      { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.md },
  truckRow:      { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  truckIcon:     { width: 48, height: 48, borderRadius: radius.md, backgroundColor: c.primaryLight, alignItems: 'center', justifyContent: 'center' },
  truckEmoji:    { fontSize: 22 },
  truckName:     { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  truckSub:      { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  statusBadge:   { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  statusText:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  divider:       { height: 1, backgroundColor: c.border, marginVertical: spacing.md },
  roleRow:       { flexDirection: 'row', gap: spacing.md },
  myRoleLabel:   { fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.8, fontWeight: fontWeight.semibold, marginBottom: spacing.xs },
  myRolePill:    { alignSelf: 'flex-start', paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.full },
  myRoleText:    { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  pairedName:    { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground, paddingVertical: 2 },

  arriveBtn:        { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginTop: spacing.md },
  arriveBtnText:    { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  arrivedBanner:    { borderRadius: radius.md, padding: spacing.sm, alignItems: 'center', marginTop: spacing.md },
  arrivedBannerText:{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textAlign: 'center' },

  plannedHint:     { backgroundColor: c.surfaceMuted, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.md },
  plannedHintText: { fontSize: fontSize.xs, color: c.mutedForeground, textAlign: 'center' },

  confirmCard:   { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: '#0EA5D855', padding: spacing.md, marginBottom: spacing.md },
  confirmTitle:  { fontSize: fontSize.md, fontWeight: fontWeight.bold, color: c.foreground },
  confirmSub:    { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: 2, marginBottom: spacing.md },
  confirmBtnRow: { flexDirection: 'row', gap: spacing.sm },
  confirmBtn:    { flex: 1, paddingVertical: spacing.sm + 2, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  declineBtn:    { backgroundColor: '#E8443A18', borderWidth: 1, borderColor: '#E8443A44' },
  confirmBtnText:{ fontSize: fontSize.sm, fontWeight: fontWeight.bold, color: '#fff' },
  respondedCard: { borderRadius: radius.lg, borderWidth: 1, padding: spacing.md, marginBottom: spacing.md, alignItems: 'center' },
  respondedOk:   { backgroundColor: '#0FA87011', borderColor: '#0FA87044' },
  respondedNo:   { backgroundColor: '#E8443A11', borderColor: '#E8443A44' },
  respondedText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  section:       { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, marginBottom: spacing.md, overflow: 'hidden' },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, backgroundColor: c.surfaceMuted },
  roleDot:       { width: 8, height: 8, borderRadius: 4 },
  sectionTitle:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.foreground, textTransform: 'uppercase', letterSpacing: 0.8, flex: 1 },
  sectionCount:  { fontSize: fontSize.xs, color: c.mutedForeground, fontWeight: fontWeight.medium },
  chevron:       { fontSize: fontSize.sm, color: c.mutedForeground, marginLeft: spacing.xs },

  memberRow:     { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  memberRowBorder:{ borderBottomWidth: 1, borderBottomColor: c.border },
  memberRowMe:   { backgroundColor: c.primaryLight + '40' },
  avatar:        { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  avatarText:    { fontSize: fontSize.xs, fontWeight: fontWeight.bold },
  memberName:    { fontSize: fontSize.sm, color: c.foreground, flex: 1 },
  confirmGlyph:  { fontSize: fontSize.md, fontWeight: fontWeight.bold, width: 20, textAlign: 'center' },

  transferCard:  { backgroundColor: '#E8820C11', borderRadius: radius.lg, borderWidth: 1, borderColor: '#E8820C44', padding: spacing.md, marginBottom: spacing.md },
  transferLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: '#E8820C', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 2 },
  transferText:  { fontSize: fontSize.sm, color: c.foreground },
  transferBold:  { fontWeight: fontWeight.bold },
  transferTime:  { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },

  apCard:        { borderRadius: radius.lg, borderWidth: 1, padding: spacing.md, marginBottom: spacing.md },
  apLabel:       { fontSize: fontSize.xs, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.8 },
  apLocation:    { fontSize: fontSize.md, fontWeight: fontWeight.semibold, marginTop: spacing.xs },
  apMeta:        { fontSize: fontSize.xs },
  apNotes:       { fontSize: fontSize.sm, fontStyle: 'italic', marginTop: spacing.xs },

  // "Not set" placeholder — muted + dashed to read as an intentionally inactive slot
  apPendingCard:     { borderRadius: radius.lg, borderWidth: 1.5, borderStyle: 'dashed', borderColor: c.border, backgroundColor: c.surfaceMuted, padding: spacing.md, marginBottom: spacing.md },
  apPendingBadge:    { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  apPendingDot:      { width: 6, height: 6, borderRadius: 3 },
  apPendingBadgeText:{ fontSize: 11, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.5 },
  apPendingIconWell: { width: 44, height: 44, borderRadius: radius.md, borderWidth: 1, borderStyle: 'dashed', alignItems: 'center', justifyContent: 'center' },
  apPendingText:     { flex: 1, fontSize: fontSize.sm, lineHeight: 20 },

  emptyCard:     { alignItems: 'center', marginTop: spacing.xxl, gap: spacing.sm },
  emptyIcon:     { fontSize: 48 },
  emptyText:     { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  emptySubtext:  { fontSize: fontSize.sm, color: c.mutedForeground },
});
