import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  Alert, Modal, ScrollView, LayoutAnimation, Platform, UIManager,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import RouteStopsList, { type RouteStop } from '@components/route/RouteStopsList';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

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

// AssignmentMember row (ADR-197) — carries the id + live status the crew-status
// control needs; assigned_crews from /dispatch only gives employee_id/name/role.
type AssignmentMemberRow = {
  id: string;
  employee_id: string;
  role: string;
  status: string;            // active | departed | transferred
};

// Enriched per-member crew status (ADR-197 Phase B /crew-status): availability
// + trip count, keyed by employee_id for the Crew card chips.
type CrewStatusEntry = {
  employee_id: string;
  availability: 'available' | 'on_route_early' | 'on_route_returning' | 'done' | 'off_crew';
  route_completion_pct: number | null;
  trip_count: number;
};

// The stop a walker is currently on, per route (ADR-197 lifecycle: in_progress).
type CurrentStop = { stop_sequence: number; normalised_address: string; total: number };

type MisrouteFlag = {
  id: string;
  tba_number: string;
  destination_block_key: string | null;
  normalised_address: string | null;
  suggested_route_id: string | null;
  resolved: boolean;
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
  paired_trainee_id: string | null;
  block_keys: string[];
  normalised_addresses: string[];
  stops: RouteStop[] | null;   // null = route predates ADR-194 → fall back to flat lists
  misrouted_packages: MisrouteFlag[];
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

// Availability chip (ADR-197). label + {bg,fg} colors per availability state.
const AVAIL_LABEL: Record<CrewStatusEntry['availability'], string> = {
  available: 'Available',
  on_route_early: 'On route',
  on_route_returning: 'Returning',
  done: 'Done',
  off_crew: 'Off crew',
};
const AVAIL_CHIP: Record<CrewStatusEntry['availability'], { bg: string; fg: string }> = {
  available:          { bg: '#D1FAE5', fg: '#047857' },
  on_route_early:     { bg: '#FEF3C7', fg: '#B45309' },
  on_route_returning: { bg: '#E0F2FE', fg: '#0369A1' },
  done:               { bg: '#D1FAE5', fg: '#047857' },
  off_crew:           { bg: '#E5E7EB', fg: '#6B7280' },
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
  const [members,    setMembers]    = useState<AssignmentMemberRow[]>([]);   // ADR-197 crew-status rows
  const [crewStatus, setCrewStatus] = useState<Record<string, CrewStatusEntry>>({});  // by employee_id
  const [currentStops, setCurrentStops] = useState<Record<string, CurrentStop>>({});  // by employee_id
  const [departingId, setDepartingId] = useState<string | null>(null);
  const [routes,     setRoutes]     = useState<RouteResp[]>([]);
  const [committing, setCommitting] = useState(false);
  const [proposing,  setProposing]  = useState(false);
  const [proposal,   setProposal]   = useState<Proposal[] | null>(null);
  const [conflicts,  setConflicts]  = useState<string[]>([]);
  const [overridden, setOverridden] = useState<Set<number>>(new Set());
  const [sending,    setSending]    = useState(false);
  const [pickerFor,  setPickerFor]  = useState<number | null>(null);   // route_number being reassigned
  const [traineeArrivedAt, setTraineeArrivedAt] = useState<string | null>(null);
  const [rebalancing, setRebalancing] = useState(false);

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
      const myRoutes: RouteResp[] = routesRes.status === 'fulfilled' ? (routesRes.value.data ?? []) : [];
      setRoutes(myRoutes);

      // Assignment members: the AP-arrival stamp (ADR-145) AND the crew-status
      // rows (ADR-197) come from the same endpoint — fetch once.
      const pairedTrainee = myCrew.find(m => m.role === 'trainee' && m.paired_trainer_id);
      if (assignmentId) {
        try {
          const res = await apiClient.get(`/assignment-members/${assignmentId}`);
          const rows = (res.data ?? []) as any[];
          setMembers(rows.map(m => ({ id: m.id, employee_id: m.employee_id, role: m.role, status: m.status ?? 'active' })));
          const row = pairedTrainee ? rows.find(m => m.employee_id === pairedTrainee.employee_id) : null;
          setTraineeArrivedAt(row?.ap_arrived_at ?? null);
        } catch { setMembers([]); setTraineeArrivedAt(null); }
      } else {
        setMembers([]);
        setTraineeArrivedAt(null);
      }

      // Crew-status enrichment (ADR-197 Phase B): availability chip + trip count
      // per member. Scoped to this truck (field caller → own truck). Best-effort.
      try {
        const cs = await apiClient.get(`/crew-status/${today}`);
        const myTruck = (cs.data?.trucks ?? []).find((t: any) => t.truck_assignment_id === assignmentId);
        const map: Record<string, CrewStatusEntry> = {};
        for (const mm of (myTruck?.members ?? [])) {
          map[mm.employee_id] = {
            employee_id: mm.employee_id,
            availability: mm.availability,
            route_completion_pct: mm.route_completion_pct ?? null,
            trip_count: mm.trip_count ?? 0,
          };
        }
        setCrewStatus(map);
      } catch { setCrewStatus({}); }

      // In-progress current stop (ADR-197 lifecycle) for each active route, keyed
      // by the walker on it. Only the OUT-NOW routes need it; best-effort per route.
      const activeRoutes = myRoutes.filter(r => (r.status === 'assigned' || r.status === 'in_progress') && !r.returned_at);
      const stopEntries = await Promise.all(activeRoutes.map(async (r) => {
        try {
          const sres = await apiClient.get(`/rts/stops/${r.id}`);
          const stops = (sres.data ?? []) as any[];
          const inProgress = stops.find(st => st.status === 'in_progress');
          if (!inProgress || !r.assigned_to) return null;
          const cur: CurrentStop = {
            stop_sequence: inProgress.stop_sequence,
            normalised_address: inProgress.normalised_address,
            total: stops.length,
          };
          return [r.assigned_to, cur] as const;
        } catch { return null; }
      }));
      const stopMap: Record<string, CurrentStop> = {};
      for (const e of stopEntries) { if (e) stopMap[e[0]] = e[1]; }
      setCurrentStops(stopMap);
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

  const markDeparted = (member: AssignmentMemberRow, name: string) => {
    Alert.alert(
      `Mark ${name} done for the day?`,
      'They finish their shift and leave this truck\'s crew. This keeps the record (unlike removing them) and updates the live crew count used to build remaining routes.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Mark Done for the Day',
          style: 'destructive',
          onPress: async () => {
            setDepartingId(member.id);
            try {
              await apiClient.patch(`/assignment-members/${member.id}/status`, { status: 'departed' });
              await load();
            } catch (e) {
              Alert.alert('Error', errorText(e, 'Could not update crew status.'));
            } finally {
              setDepartingId(null);
            }
          },
        },
      ],
    );
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

  const runRebalance = async () => {
    if (!taId) return;
    setRebalancing(true);
    try {
      // Pair is DERIVED server-side from the dispatch pairing.
      const res = await apiClient.post('/walker-routes/arrival-confirm', {
        truck_assignment_id: taId,
        route_date: todayStr(),
      });
      const absorbed = res.data?.absorbed_route_numbers?.length ?? 0;
      Alert.alert(
        'Rebalance complete',
        `Paired route expanded to ${res.data?.paired_capacity_limit ?? '1.5×'} half-slots`
        + (absorbed ? ` — absorbed ${absorbed} route${absorbed === 1 ? '' : 's'}.` : '.'),
      );
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not run the rebalance.'));
    } finally {
      setRebalancing(false);
    }
  };

  // ── Derived ──────────────────────────────────────────────────────────────

  const unassigned = routes.filter(r => r.status === 'unassigned');
  const active     = routes.filter(r => r.status === 'assigned' || r.status === 'in_progress');
  const completed  = routes.filter(r => r.status === 'completed');
  const pickerOptions = crew.filter(m => m.role !== 'driver');
  const pairedTrainee = crew.find(m => m.role === 'trainee' && m.paired_trainer_id);
  const rebalanced = routes.some(r => r.paired_trainee_id);

  // Route lookup by id — shared by misroute resolution + wave proposal drill-down
  const routesById = new Map(routes.map(r => [r.id, r]));
  const misroutes = routes.flatMap(r =>
    (r.misrouted_packages ?? [])
      .filter(f => !f.resolved)
      .map(f => {
        const sug = f.suggested_route_id ? routesById.get(f.suggested_route_id) ?? null : null;
        // Guard: a package never "belongs on" the route it was flagged from.
        return { flag: f, source: r, suggested: sug && sug.id !== r.id ? sug : null };
      }),
  );

  const [resolvingFlag, setResolvingFlag] = useState<string | null>(null);
  const resolveMisroute = async (flagId: string, sourceRouteId: string, destRouteId: string) => {
    setResolvingFlag(flagId);
    try {
      await apiClient.patch(`/walker-routes/routes/${sourceRouteId}/misroutes/${flagId}/resolve`, {
        destination_route_id: destRouteId,
      });
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not resolve the misroute.'));
    } finally {
      setResolvingFlag(null);
    }
  };

  if (!loading && !taId) {
    return (
      <ScreenShell title="AP Sort" subtitle="No truck assignment today."
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

      {/* Paired arrival & rebalance (ADR-145): trainee confirms arrival from
          their app; this card completes the 1.5× route expansion. */}
      {routes.length > 0 && pairedTrainee && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: rebalanced ? c.border : '#0FA87055' }]}>
          {rebalanced ? (
            <Text style={[s.cardSub, { marginBottom: 0 }]}>
              🤝 Paired route active — {pairedTrainee.name} rides with you at 1.5× capacity.
            </Text>
          ) : (
            <>
              <Text style={s.cardTitle}>Paired arrival — {pairedTrainee.name}</Text>
              <Text style={s.cardSub}>
                {traineeArrivedAt
                  ? `📍 Arrived ${new Date(traineeArrivedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} — run the rebalance to expand your shared route to 1.5×.`
                  : 'Waiting for your trainee to confirm arrival in their app — you can rebalance anyway if they\'re standing next to you.'}
              </Text>
              <TouchableOpacity
                style={[s.primaryBtn, { backgroundColor: traineeArrivedAt ? '#0FA870' : c.primary }]}
                onPress={runRebalance}
                disabled={rebalancing}
              >
                {rebalancing
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={s.primaryBtnText}>🤝 Confirm Arrival & Rebalance (1.5×)</Text>}
              </TouchableOpacity>
            </>
          )}
        </View>
      )}

      {/* Misrouted packages — resolve at the AP before walkers depart. The
          sort computed where each belongs; one tap moves the package data
          with it (pull it from the wrong tote as you tap). */}
      {misroutes.length > 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: '#E8820C55' }]}>
          <Text style={s.cardTitle}>⚠ Misrouted packages · {misroutes.length}</Text>
          <Text style={s.cardSub}>Pull each from its current tote and hand it to the right walker.</Text>
          {misroutes.slice(0, 12).map(({ flag, source, suggested }) => (
            <View key={flag.id} style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs + 2, borderTopWidth: 1, borderTopColor: c.border }}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: fontSize.xs, color: c.foreground, fontVariant: ['tabular-nums'] }}>
                  …{flag.tba_number.slice(-8)} <Text style={{ color: c.mutedForeground }}>in #{source.route_number}</Text>
                </Text>
                <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }} numberOfLines={1}>
                  {flag.normalised_address ?? flag.destination_block_key ?? 'unknown block'}
                  {suggested ? ` → #${suggested.route_number} ${suggested.assigned_to_name ?? ''}` : ' → no covering route (captain review)'}
                </Text>
              </View>
              {suggested && (
                <TouchableOpacity
                  style={{ backgroundColor: c.primary, borderRadius: radius.md, paddingHorizontal: spacing.sm + 2, paddingVertical: spacing.xs + 2 }}
                  onPress={() => resolveMisroute(flag.id, source.id, suggested.id)}
                  disabled={resolvingFlag === flag.id}
                >
                  {resolvingFlag === flag.id
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Text style={{ color: '#fff', fontSize: fontSize.xs, fontWeight: fontWeight.bold }}>Move to #{suggested.route_number}</Text>}
                </TouchableOpacity>
              )}
            </View>
          ))}
          {misroutes.length > 12 && (
            <Text style={[s.cardSub, { marginTop: spacing.xs, marginBottom: 0 }]}>…and {misroutes.length - 12} more — resolve these first, then refresh.</Text>
          )}
        </View>
      )}

      {/* Crew status (ADR-197): mark a walker/trainer/trainee departed when they
          leave for the day. Preserves the record (unlike removal) and keeps the
          live crew count accurate for building the remaining routes. */}
      {members.length > 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={s.cardTitle}>Crew</Text>
          {members
            .filter(m => m.role !== 'driver')
            .map(m => {
              const name = crew.find(cm => cm.employee_id === m.employee_id)?.name ?? m.role;
              const off = m.status !== 'active';
              const cs = crewStatus[m.employee_id];
              const chip = cs ? AVAIL_CHIP[cs.availability] : null;
              const pct = cs?.route_completion_pct != null ? ` · ${Math.round(cs.route_completion_pct * 100)}%` : '';
              const stop = currentStops[m.employee_id];
              return (
                <View key={m.id} style={{ paddingVertical: spacing.xs + 2, borderTopWidth: 1, borderTopColor: c.border }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontSize: fontSize.sm, color: off ? c.mutedForeground : c.foreground, textDecorationLine: off ? 'line-through' : 'none' }}>
                        {name}
                      </Text>
                      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'capitalize' }}>
                        {m.role}
                        {off ? ` · ${m.status}` : ''}
                        {cs && cs.trip_count > 0 ? ` · ${cs.trip_count} trip${cs.trip_count === 1 ? '' : 's'}` : ''}
                      </Text>
                    </View>
                    {chip && (
                      <View style={{ backgroundColor: chip.bg, borderRadius: radius.full, paddingHorizontal: spacing.sm, paddingVertical: 2 }}>
                        <Text style={{ fontSize: fontSize.xs, color: chip.fg, fontWeight: fontWeight.semibold }}>
                          {AVAIL_LABEL[cs!.availability]}{pct}
                        </Text>
                      </View>
                    )}
                    {!off && (
                      <TouchableOpacity
                        style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.sm + 2, paddingVertical: spacing.xs + 2 }}
                        onPress={() => markDeparted(m, name)}
                        disabled={departingId === m.id}
                      >
                        {departingId === m.id
                          ? <ActivityIndicator size="small" color={c.mutedForeground} />
                          : <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, fontWeight: fontWeight.semibold }}>Mark Done</Text>}
                      </TouchableOpacity>
                    )}
                  </View>
                  {stop && (
                    <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 }}>
                      📍 On stop {stop.stop_sequence}/{stop.total}: {stop.normalised_address}
                    </Text>
                  )}
                </View>
              );
            })}
        </View>
      )}

      {/* Route lists */}
      {[{ label: 'OUT NOW', data: active }, { label: 'UNASSIGNED', data: unassigned }, { label: 'COMPLETED', data: completed }]
        .filter(g => g.data.length > 0)
        .map(g => (
          <View key={g.label}>
            <Text style={s.sectionLabel}>{g.label} · {g.data.length}</Text>
            {g.data.map(r => (
              <RouteRow key={r.id} route={r} c={c} s={s} />
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

              <ScrollView style={{ maxHeight: 420 }}>
                {[...proposal].sort((a, b) => a.route_number - b.route_number).map(p => {
                  const routeData = routesById.get(p.route_id);
                  const blockKeys = routeData?.block_keys ?? [];
                  const addresses = routeData?.normalised_addresses ?? [];
                  const pkgCount  = routeData?.package_count ?? null;
                  return (
                    <ProposalRow
                      key={p.route_number}
                      proposal={p}
                      blockKeys={blockKeys}
                      addresses={addresses}
                      stops={routeData?.stops ?? null}
                      packageCount={pkgCount ?? null}
                      overridden={overridden.has(p.route_number)}
                      onAssigneePress={() => setPickerFor(p.route_number)}
                      c={c}
                      s={s}
                    />
                  );
                })}
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

// ── RouteRow — expandable route card showing blocks + addresses ───────────────

function RouteRow({ route, c, s }: { route: RouteResp; c: ThemeColors; s: ReturnType<typeof styles> }) {
  const [expanded, setExpanded] = useState(false);
  const effortColor = EFFORT_COLORS[route.effort_class] ?? c.primary;

  // Delivered stops (ADR-194). Chips and drill-down come from here so flagged
  // riders (shown in the misroute card instead) don't masquerade as coverage.
  // Old routes (stops null) fall back to the flat carried lists.
  const stops = route.stops ?? null;
  const chipBlocks = stops ? [...new Set(stops.map(st => st.block_key))] : route.block_keys;

  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setExpanded(e => !e);
  };

  return (
    <View style={[s.routeRow, { backgroundColor: c.card, borderColor: c.border, flexDirection: 'column', padding: 0 }]}>
      <TouchableOpacity
        style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm }}
        onPress={toggle}
        activeOpacity={0.7}
      >
        <View style={[s.routeNum, { backgroundColor: effortColor + '1E' }]}>
          <Text style={[s.routeNumText, { color: effortColor }]}>{route.route_number}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[s.routeName, { color: c.foreground }]}>
            {route.assigned_to_name ?? 'Unassigned'}
          </Text>
          <Text style={[s.routeMeta, { color: c.mutedForeground }]}>
            {route.package_count} pkgs · {route.effort_class} · wave {route.wave_number}
            {stops ? ` · ${stops.length} stop${stops.length === 1 ? '' : 's'}` : ''}
            {route.returned_at ? ' · returned' : ''}
          </Text>
          {chipBlocks.length > 0 && (
            <Text style={[s.routeMeta, { color: c.mutedForeground, marginTop: 2 }]} numberOfLines={1}>
              {chipBlocks.slice(0, 3).join(' · ')}{chipBlocks.length > 3 ? ` +${chipBlocks.length - 3}` : ''}
            </Text>
          )}
        </View>
        <Text style={[s.routeStatus, { color: c.mutedForeground }]}>{route.status.replace('_', ' ')}</Text>
        <Text style={{ color: c.mutedForeground, fontSize: 11 }}>{expanded ? '▲' : '▼'}</Text>
      </TouchableOpacity>

      {expanded && (
        <View style={{ paddingHorizontal: spacing.sm, paddingBottom: spacing.sm, paddingLeft: 50 }}>
          {stops && stops.length > 0 ? (
            <RouteStopsList stops={stops} c={c} />
          ) : (
            <View style={{ gap: 4 }}>
              {route.normalised_addresses.map((addr, i) => (
                <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <View style={{ width: 4, height: 4, borderRadius: 2, backgroundColor: c.mutedForeground, flexShrink: 0 }} />
                  <Text style={{ fontSize: fontSize.xs, color: c.foreground }} numberOfLines={1}>{addr}</Text>
                </View>
              ))}
            </View>
          )}
        </View>
      )}
    </View>
  );
}

// ── ProposalRow — expandable wave-proposal entry with block / address drill-down ─

function ProposalRow({
  proposal, blockKeys, addresses, stops, packageCount, overridden, onAssigneePress, c, s,
}: {
  proposal: Proposal;
  blockKeys: string[];
  addresses: string[];
  stops: RouteStop[] | null;
  packageCount: number | null;
  overridden: boolean;
  onAssigneePress: () => void;
  c: ThemeColors;
  s: ReturnType<typeof styles>;
}) {
  const [expanded, setExpanded] = useState(false);
  const chipBlocks = stops ? [...new Set(stops.map(st => st.block_key))] : blockKeys;

  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setExpanded(e => !e);
  };

  const effortColor = EFFORT_COLORS[proposal.effort_class] ?? c.primary;

  return (
    <View style={{ borderBottomWidth: 1, borderBottomColor: c.border }}>
      {/* Header row — tap left to expand, tap right to reassign */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.sm }}>
        <TouchableOpacity onPress={toggle} activeOpacity={0.7}>
          <View style={[s.routeNum, { backgroundColor: effortColor + '1E' }]}>
            <Text style={[s.routeNumText, { color: effortColor }]}>{proposal.route_number}</Text>
          </View>
        </TouchableOpacity>
        <TouchableOpacity style={{ flex: 1 }} onPress={toggle} activeOpacity={0.7}>
          <Text style={[ms.propName, { color: c.foreground }]}>{proposal.employee_name}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginTop: 1, flexWrap: 'wrap' }}>
            <Text style={[ms.propMeta, { color: c.mutedForeground }]}>
              {proposal.effort_class}
              {packageCount != null ? ` · ${packageCount} pkg${packageCount === 1 ? '' : 's'}` : ''}
              {stops ? ` · ${stops.length} stop${stops.length === 1 ? '' : 's'}` : ''}
            </Text>
            {chipBlocks.length > 0 && (
              <Text style={[ms.propMeta, { color: c.mutedForeground }]}>
                · {chipBlocks.slice(0, 2).join(', ')}{chipBlocks.length > 2 ? ` +${chipBlocks.length - 2}` : ''}
              </Text>
            )}
          </View>
        </TouchableOpacity>
        <TouchableOpacity onPress={onAssigneePress} style={{ paddingHorizontal: spacing.xs }}>
          <Text style={{ fontSize: fontSize.xs, color: overridden ? '#E8820C' : c.mutedForeground, fontWeight: fontWeight.semibold }}>
            {overridden ? 'edited ✎' : 'auto ✎'}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={toggle} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
          <Text style={{ color: c.mutedForeground, fontSize: 11 }}>{expanded ? '▲' : '▼'}</Text>
        </TouchableOpacity>
      </View>

      {/* Expanded drill-down: block section → address → TBA grid (ADR-194);
          flat address list only for routes that predate the stops column */}
      {expanded && (
        <View style={{ paddingBottom: spacing.sm, paddingLeft: 42 }}>
          {stops && stops.length > 0 ? (
            <RouteStopsList stops={stops} c={c} />
          ) : addresses.length > 0 ? (
            <View style={{ gap: spacing.xs }}>
              {addresses.map((addr, i) => (
                <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <View style={{ width: 4, height: 4, borderRadius: 2, backgroundColor: c.mutedForeground, flexShrink: 0 }} />
                  <Text style={{ fontSize: fontSize.xs, color: c.foreground, flex: 1 }} numberOfLines={1}>{addr}</Text>
                </View>
              ))}
            </View>
          ) : (
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, fontStyle: 'italic' }}>No address data yet</Text>
          )}
        </View>
      )}
    </View>
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
