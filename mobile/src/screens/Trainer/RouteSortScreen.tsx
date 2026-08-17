import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  Alert, Modal, ScrollView, LayoutAnimation,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import RouteStopsList, { type RouteStop } from '@components/route/RouteStopsList';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, getRoleColor, type ThemeColors, type FieldRole } from '@theme/index';
import { useLayoutTransition } from '@hooks/useLayoutTransition';
import { Badge, Button, Avatar } from '@components/ui/primitives';

// The old-architecture LayoutAnimation opt-in was removed here: it is a no-op
// under the New Architecture and logged a warning on every launch. See
// hooks/useLayoutTransition.ts for the full reasoning.

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
  availability: 'not_arrived' | 'available' | 'on_route_early' | 'on_route_returning' | 'done' | 'off_crew';
  route_completion_pct: number | null;
  trip_count: number;
};

// The stop a walker is currently on, per route (ADR-197 lifecycle: in_progress).
type CurrentStop = { stop_sequence: number; normalised_address: string; total: number };

type MisrouteFlag = {
  id: string;
  tba_number: string;
  current_bag_id: string;          // the tote the package is wrongly in — helps locate it
  destination_block_key: string | null;
  normalised_address: string | null;
  suggested_route_id: string | null;
  resolved: boolean;
};

// ADR-214: an out-of-zone package flagged for return to station.
type Removal = {
  id: string;
  bag_id: string;
  tba: string | null;
  package_count: number;
  reason: string;                 // 'out_of_zone'
  status: string;                 // flagged | removed
  locator: string | null;
  owner_route_number: number | null;
};

type RouteResp = {
  id: string;
  route_number: number;
  status: string;
  effort_class: string;
  package_count: number;
  wave_number: number;
  // ADR-212: membership. executor = assignee-of-record; supervisors = trainers.
  executor: { id: string; name: string } | null;
  supervisors: { id: string; name: string }[];
  returned_at: string | null;
  // ADR-229: set when help was requested on this route — gates the captain's
  // "cover remaining stops" emergency split on an in-progress route.
  help_requested_at: string | null;
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

// Effort class → themed color (ADR-207). Maps to semantic tokens so it tracks
// light/dark: easy=success, standard=info, heavy=warning, very_heavy=danger.
function effortColor(effortClass: string, c: ThemeColors): string {
  switch (effortClass) {
    case 'easy':       return c.success;
    case 'standard':   return c.info;
    case 'heavy':      return c.warning;
    case 'very_heavy': return c.danger;
    default:           return c.primary;
  }
}

// Availability chip (ADR-197). label + Badge tone per availability state — tones
// resolve to themed colors (light/dark) via the Badge primitive (ADR-207).
const AVAIL_LABEL: Record<CrewStatusEntry['availability'], string> = {
  not_arrived: 'Not Present',
  available: 'Available',
  on_route_early: 'On route',
  on_route_returning: 'Returning',
  done: 'Done',
  off_crew: 'Off crew',
};
type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'primary' | 'gold' | 'teal' | 'slate' | 'neutral' | 'muted';
const AVAIL_TONE: Record<CrewStatusEntry['availability'], BadgeTone> = {
  not_arrived:        'muted',
  available:          'success',
  on_route_early:     'warning',
  on_route_returning: 'info',
  done:               'success',
  off_crew:           'neutral',
};

export default function RouteSortScreen() {
  const c = useColors();
  const { fetchId } = useEmployeeId();
  const s = styles(c);
  const nav = useNavigation<any>();   // ADR-216 phase 2: push CrewMemberDetail

  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [taId,       setTaId]       = useState<string | null>(null);
  const [truckName,  setTruckName]  = useState<string>('');
  const [zoned,      setZoned]      = useState(false);
  /* ADR-274 D9 — a hub's packages come from its OWN manifest, never the station
     sort. Same readiness flag, different evidence, so only the copy changes. */
  const [isHub,      setIsHub]      = useState(false);
  const [zonePkgs,   setZonePkgs]   = useState(0);
  const [crew,       setCrew]       = useState<CrewMember[]>([]);
  const [members,    setMembers]    = useState<AssignmentMemberRow[]>([]);   // ADR-197 crew-status rows
  const [crewStatus, setCrewStatus] = useState<Record<string, CrewStatusEntry>>({});  // by employee_id
  const [currentStops, setCurrentStops] = useState<Record<string, CurrentStop>>({});  // by employee_id
  const [departingId, setDepartingId] = useState<string | null>(null);
  const [rollCallId, setRollCallId] = useState<string | null>(null);   // employee_id being roll-called
  const [viewerId, setViewerId] = useState<string | null>(null);       // this device's employee id
  // ADR-228: per-member uniform/cart-cover draft compliance, by employee_id. Only
  // the DRIVER captures it (it's their crew record); saved live as the roster fills.
  const [compliance, setCompliance] = useState<Record<string, { uniform_pass: boolean; cart_cover_pass: boolean; status: string }>>({});
  // Per-field "has the captain actually set this pill" — the row stores both fields
  // as non-null booleans, so a persisted row can't say "uniform set, cart-cover not".
  // We track it client-side so tapping Uniform never implies Cart cover was reviewed
  // (item 2). A loaded row counts both as touched; a fresh tap touches just that field.
  const [complianceTouched, setComplianceTouched] = useState<Record<string, { uniform_pass: boolean; cart_cover_pass: boolean }>>({});
  const [savingCompliance, setSavingCompliance] = useState<string | null>(null);
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
  const [splitting, setSplitting] = useState(false);
  const [removals, setRemovals] = useState<Removal[]>([]);   // ADR-214 out-of-zone
  const [apView, setApView] = useState<'sort' | 'crew'>('sort');   // segmented sub-view
  // Live route actions on an ALREADY-assigned route (ADR-226): reassign picker
  // targets a route.id (distinct from pickerFor, which edits the pre-send wave
  // proposal); dropId tracks the in-flight unassign.
  const [reassignRoute, setReassignRoute] = useState<{ id: string; number: number } | null>(null);
  const [routeActionId, setRouteActionId] = useState<string | null>(null);

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
      setViewerId(eid);

      // ADR-228: the Crew Roster is shared by the truck's captains (driver +
      // trainers), so any of them sees/edits compliance. It's keyed to the truck's
      // DRIVER, so pre-load the driver's records into the toggles.
      const viewerRole = myCrew.find(m => m.employee_id === eid)?.role;
      const driverMember = myCrew.find(m => m.role === 'driver');
      const viewerIsCaptain = viewerRole === 'driver' || viewerRole === 'trainer';
      if (viewerIsCaptain && driverMember) {
        try {
          const compRes = await apiClient.get(`/shift-ops/crew-compliance/${driverMember.employee_id}`, { params: { target_date: today } });
          const map: Record<string, { uniform_pass: boolean; cart_cover_pass: boolean; status: string }> = {};
          const touched: Record<string, { uniform_pass: boolean; cart_cover_pass: boolean }> = {};
          for (const r of (compRes.data ?? [])) {
            map[r.employee_id] = { uniform_pass: r.uniform_pass, cart_cover_pass: r.cart_cover_pass, status: r.status };
            touched[r.employee_id] = { uniform_pass: true, cart_cover_pass: true };  // persisted row = both reviewed
          }
          setCompliance(map);
          setComplianceTouched(touched);
        } catch { /* best-effort */ }
      }

      const ta: any = truckAssignments.find(t => t.truck_id === myTruckId);
      const assignmentId = ta?.id ?? ta?.assignment_id ?? null;
      if (!assignmentId) { setTaId(null); return; }
      setTaId(assignmentId);

      const [zoneRes, routesRes, removalsRes] = await Promise.allSettled([
        apiClient.get(`/sort/${today}/zone-status`),
        apiClient.get(`/walker-routes/${assignmentId}/routes`),
        apiClient.get(`/sort/${today}/removals`),
      ]);
      if (zoneRes.status === 'fulfilled') {
        const mine = (zoneRes.value.data?.trucks ?? []).find((t: any) => t.truck_id === myTruckId);
        setZoned(!!mine?.zoned);
        setIsHub(!!mine?.is_hub);
        setZonePkgs(mine?.package_count ?? 0);
        setTruckName(mine?.truck_name ?? '');
      }
      const myRoutes: RouteResp[] = routesRes.status === 'fulfilled' ? (routesRes.value.data ?? []) : [];
      setRoutes(myRoutes);

      // ADR-214: out-of-zone removals — packages to pull at the AP and return to
      // station (NOT misroutes). Scoped to this truck by the endpoint.
      const rem = removalsRes.status === 'fulfilled'
        ? ((removalsRes.value.data?.removals ?? []) as Removal[]).filter(r => r.reason === 'out_of_zone')
        : [];
      setRemovals(rem);

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

      // Crew-status enrichment (ADR-197 Phase B): availability chip + trip count +
      // CURRENT STOP per member, all from ONE call. Previously the current stop
      // required a per-route /rts/stops fan-out (N requests, N=route count) which
      // was the Route-Sort hang risk on big trucks — crew-status now returns it.
      const stopMap: Record<string, CurrentStop> = {};
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
          if (mm.current_stop_sequence != null) {
            stopMap[mm.employee_id] = {
              stop_sequence: mm.current_stop_sequence,
              normalised_address: mm.current_stop_address,
              total: mm.current_stop_total ?? 0,
            };
          }
        }
        setCrewStatus(map);
      } catch { setCrewStatus({}); }
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

  // Roll call (ADR-198): mark a not-arrived member in (Present — server derives
  // early/present/late from the clock) or Absent (ncns). Flips them off Not
  // Arrived into the working crew status — the soft presence gate for routes.
  // ADR-228: save one member's uniform/cart-cover as a draft, live. Optimistic —
  // update local state immediately, PUT the draft, roll back on failure.
  const setComplianceField = async (employeeId: string, field: 'uniform_pass' | 'cart_cover_pass', value: boolean) => {
    const prev = compliance[employeeId] ?? { uniform_pass: true, cart_cover_pass: true, status: 'draft' };
    const prevTouched = complianceTouched[employeeId] ?? { uniform_pass: false, cart_cover_pass: false };
    const next = { ...prev, [field]: value };
    const nextTouched = { ...prevTouched, [field]: true };  // only THIS pill becomes set (item 2)
    setCompliance(m => ({ ...m, [employeeId]: next }));
    setComplianceTouched(m => ({ ...m, [employeeId]: nextTouched }));
    setSavingCompliance(employeeId);
    try {
      // driver_id is resolved server-side from the caller's truck (any captain).
      // The row stores both booleans (columns are non-null); an untapped field
      // rides along at its default until the captain taps it too.
      await apiClient.put('/shift-ops/crew-compliance/draft', {
        date: todayStr(), employee_id: employeeId,
        uniform_pass: next.uniform_pass, cart_cover_pass: next.cart_cover_pass,
      });
    } catch (e) {
      setCompliance(m => ({ ...m, [employeeId]: prev }));   // roll back
      setComplianceTouched(m => ({ ...m, [employeeId]: prevTouched }));
      Alert.alert('Error', errorText(e, 'Could not save compliance.'));
    } finally {
      setSavingCompliance(null);
    }
  };

  // ADR-228: bulk "mark all present crew compliant" — creates a pass record for
  // every present member who has NO record yet, so the captain doesn't tap 2×N
  // pills just to satisfy the Check-In #1 gate. Exceptions get flipped to ✗
  // individually afterward. Only touches unrecorded members (never overwrites an
  // existing pass/fail).
  const markAllCompliant = async (employeeIds: string[]) => {
    if (employeeIds.length === 0) return;
    setSavingCompliance('__bulk__');
    try {
      const today = todayStr();
      for (const employeeId of employeeIds) {
        await apiClient.put('/shift-ops/crew-compliance/draft', {
          date: today, employee_id: employeeId,
          uniform_pass: true, cart_cover_pass: true,
        });
        setCompliance(m => ({ ...m, [employeeId]: { uniform_pass: true, cart_cover_pass: true, status: 'draft' } }));
        setComplianceTouched(m => ({ ...m, [employeeId]: { uniform_pass: true, cart_cover_pass: true } }));
      }
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not save compliance.'));
    } finally {
      setSavingCompliance(null);
    }
  };

  const takeRollCall = async (employeeId: string, absent: boolean) => {
    setRollCallId(employeeId);
    try {
      await apiClient.post('/roll-call', { employee_id: employeeId, date: todayStr(), ncns: absent });
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not record roll call.'));
    } finally {
      setRollCallId(null);
    }
  };

  // Marking someone NCNS (no-call-no-show) removes them from the crew for the
  // day — confirm before applying, since it's a consequential, hard-to-notice tap.
  const confirmNCNS = (employeeId: string, name: string) => {
    Alert.alert(
      'Mark NCNS?',
      `Mark ${name} as a no-call-no-show? They'll be removed from today's crew. You can only undo this by contacting dispatch.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Mark NCNS', style: 'destructive', onPress: () => takeRollCall(employeeId, true) },
      ],
    );
  };

  // Live reassign of an ALREADY-assigned route to another present crew member
  // (PATCH /reassign). Distinct from overrideAssignee (which edits the pre-send
  // wave proposal). Backend enforces the present-only gate too.
  const liveReassign = async (routeId: string, member: CrewMember) => {
    setRouteActionId(routeId);
    try {
      await apiClient.patch(`/walker-routes/routes/${routeId}/reassign`, { new_employee_id: member.employee_id });
      setReassignRoute(null);
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not reassign the route.'));
    } finally {
      setRouteActionId(null);
    }
  };

  // Drop an assigned route back into the pool (PATCH /unassign). Confirm first —
  // it pulls the route off the crew member and re-opens it for the next wave.
  const dropRoute = (routeId: string, routeNumber: number, holderName: string) => {
    Alert.alert(
      'Drop route?',
      `Take route #${routeNumber} off ${holderName} and return it to the pool? It becomes unassigned and can be re-distributed.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Drop', style: 'destructive',
          onPress: async () => {
            setRouteActionId(routeId);
            try {
              await apiClient.patch(`/walker-routes/routes/${routeId}/unassign`);
              await load();
            } catch (e) {
              Alert.alert('Error', errorText(e, 'Could not drop the route.'));
            } finally {
              setRouteActionId(null);
            }
          },
        },
      ],
    );
  };

  // ADR-229: emergency cover — peel the undelivered stops off an in-progress
  // route (walker injured/emergency, already flagged via request-help) into a new
  // unassigned covering route the captain can wave/reassign to present crew.
  const coverRemaining = (routeId: string, routeNumber: number, holderName: string) => {
    Alert.alert(
      'Cover remaining stops?',
      `Take the undelivered stops on route #${routeNumber} off ${holderName} and spin them into a new route for someone else to cover? ${holderName}'s route closes at what they've delivered.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Cover', style: 'destructive',
          onPress: async () => {
            setRouteActionId(routeId);
            try {
              const res = await apiClient.post(`/walker-routes/routes/${routeId}/cover-remaining`, {});
              const moved = res.data?.stops_moved ?? 0;
              const covNum = res.data?.covering_route?.route_number;
              await load();
              Alert.alert(
                'Coverage route created',
                `${moved} remaining stop${moved === 1 ? '' : 's'} moved to route #${covNum ?? '?'} — assign it from the wave / crew list.`,
              );
            } catch (e) {
              Alert.alert('Error', errorText(e, 'Could not cover the remaining stops.'));
            } finally {
              setRouteActionId(null);
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

  // ADR-213: split the pair — the trainee keeps their route (reverts to solo);
  // the trainer takes the nearest unassigned route. Confirm first (irreversible-ish
  // rebalance of totes) then POST /split with the trainee's (paired) route id.
  const runSplit = () => {
    const paired = routes.find(r => r.supervisors.length > 0);
    if (!paired) return;
    Alert.alert(
      'Split the pair?',
      `${pairedTrainee?.name ?? 'Your trainee'} will keep their route on their own, and you'll `
      + 'take the nearest open route. Overflow packages move to your route.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Split',
          style: 'destructive',
          onPress: async () => {
            setSplitting(true);
            try {
              const res = await apiClient.post(`/walker-routes/routes/${paired.id}/split`, {});
              const moved = res.data?.overflow_totes_moved ?? 0;
              const trNum = res.data?.trainer_route?.route_number;
              Alert.alert(
                'Split complete',
                `You're now on route #${trNum ?? '?'}`
                + (moved ? ` — ${moved} overflow tote${moved === 1 ? '' : 's'} moved to your route.` : '.'),
              );
              await load();
            } catch (e) {
              Alert.alert('Error', errorText(e, 'Could not split the pair.'));
            } finally {
              setSplitting(false);
            }
          },
        },
      ],
    );
  };

  // ── Derived ──────────────────────────────────────────────────────────────

  const unassigned = routes.filter(r => r.status === 'unassigned');
  const active     = routes.filter(r => r.status === 'assigned' || r.status === 'in_progress');
  const completed  = routes.filter(r => r.status === 'completed');
  // ADR-228: any captain on the truck (driver or trainer) shares the Crew Roster
  // and can record uniform/cart-cover. The record keys to the truck's driver
  // server-side, so the caller need not be the driver.
  const viewerRole = viewerId ? crew.find(m => m.employee_id === viewerId)?.role : undefined;
  const isCaptain = viewerRole === 'driver' || viewerRole === 'trainer';
  // ADR-228 item 3: once Check-In #1 finalizes the roster it flips every draft
  // compliance row to 'submitted'. When there's at least one record and none are
  // still 'draft', the check-in is done — hide the compliance pills to lean out
  // the crew card (the review is over; the record has shipped to Dispatch).
  const complianceRows = Object.values(compliance);
  const complianceSubmitted = complianceRows.length > 0 && complianceRows.every(r => r.status === 'submitted');

  // Reassign candidates: non-driver crew who are PRESENT — you can't hand a route
  // to someone who hasn't arrived (matches the backend presence gate). Present =
  // crew-status availability is anything but not_arrived / off_crew. If a member
  // has no crew-status entry yet, treat as not-present (conservative).
  const pickerOptions = crew.filter(m => {
    if (m.role === 'driver') return false;
    const av = crewStatus[m.employee_id]?.availability;
    return av != null && av !== 'not_arrived' && av !== 'off_crew';
  });
  const pairedTrainee = crew.find(m => m.role === 'trainee' && m.paired_trainer_id);
  // ADR-212: a route is "rebalanced"/paired-active when a supervisor is attached.
  const rebalanced = routes.some(r => r.supervisors.length > 0);

  // Route lookup by id — shared by misroute resolution + wave proposal drill-down
  const routesById = new Map(routes.map(r => [r.id, r]));
  // ADR-216 phase 2: a crew member's route = the one they execute. Lets a crew
  // card open that route's detail.
  const routeByExecutor = new Map(routes.filter(r => r.executor).map(r => [r.executor!.id, r]));
  // A paired trainer isn't an executor (ADR-212) — they SUPERVISE the trainee's
  // route. Map trainer employee_id → the route they supervise, so their crew row
  // shows "Supervising #N" instead of looking route-less/confusing.
  const routeBySupervisor = new Map<string, RouteResp>();
  for (const r of routes) for (const s of (r.supervisors ?? [])) routeBySupervisor.set(s.id, r);
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

  const crewCount = members.filter(m => m.role !== 'driver').length;

  return (
    <ScreenShell
      title="AP Sort"
      subtitle={truckName ? `${truckName} · ${todayStr()}` : todayStr()}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load({ refresh: true })}
      belowHeader={members.length > 0 ? (
        // Segmented sub-view (mirrors the Incident tab's Report/History bar):
        // fold the Crew Roster off the main sort scroll into its own view.
        <View style={s.subTabBar}>
          {(['sort', 'crew'] as const).map(v => (
            <TouchableOpacity key={v} style={[s.subTab, apView === v && s.subTabActive]} onPress={() => setApView(v)}>
              <Text style={[s.subTabText, apView === v && s.subTabTextActive]}>
                {v === 'sort' ? 'Sort' : `Crew Roster${crewCount ? ` (${crewCount})` : ''}`}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      ) : undefined}
    >
      {apView === 'sort' && (<>
      {/* Phase: not yet committed */}
      {routes.length === 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          {zoned ? (
            <>
              <Text style={s.cardTitle}>Ready to sort</Text>
              <Text style={s.cardSub}>
                {isHub
                  ? `${zonePkgs} packages on this hub's manifest.`
                  : `${zonePkgs} packages zoned to this truck by station sort.`}
              </Text>
              <TouchableOpacity style={[s.primaryBtn, { backgroundColor: c.primary }]} onPress={commitSort} disabled={committing}>
                {committing
                  ? <ActivityIndicator color={c.primaryForeground} />
                  : <Text style={s.primaryBtnText}>Commit Sort — build routes</Text>}
              </TouchableOpacity>
            </>
          ) : (
            <>
              <Text style={s.cardTitle}>
                {isHub ? 'Waiting on the hub manifest' : 'Waiting on station sort'}
              </Text>
              <Text style={s.cardSub}>
                {isHub
                  ? 'No manifest uploaded for this hub yet. Dispatch uploads it on the Sort page.'
                  : 'This truck has no zoned packages yet — check back after the station finishes sorting.'}
              </Text>
            </>
          )}
        </View>
      )}

      {/* Phase: routes exist — wave control */}
      {routes.length > 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          <View style={s.summaryRow}>
            <Summary label="Unassigned" value={unassigned.length} color={unassigned.length > 0 ? c.warning : c.mutedForeground} c={c} />
            <Summary label="Out now" value={active.length} color={c.info} c={c} />
            <Summary label="Done" value={completed.length} color={c.success} c={c} />
          </View>
          {unassigned.length > 0 && (
            <TouchableOpacity style={[s.primaryBtn, { backgroundColor: c.primary }]} onPress={propose} disabled={proposing}>
              {proposing
                ? <ActivityIndicator color={c.primaryForeground} />
                : <Text style={s.primaryBtnText}>⚡ Distribute Wave ({unassigned.length} route{unassigned.length === 1 ? '' : 's'} waiting)</Text>}
            </TouchableOpacity>
          )}
        </View>
      )}

      {/* Out-of-zone removals (ADR-214) — packages outside the company zone.
          These are NOT misroutes; pull them and return to station (they were
          flagged at the sort, not something a route should cover). */}
      {removals.length > 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.danger + '55' }]}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: 2 }}>
            <Text style={{ fontSize: fontSize.md }}>📤</Text>
            <Text style={[s.cardTitle, { flex: 1 }]}>Return to station — out of zone</Text>
            <Badge tone="danger">{removals.length}</Badge>
          </View>
          <Text style={s.cardSub}>
            These packages are outside the delivery zone. Pull them from their tote and hand
            them to the driver for return — they are not on any route.
          </Text>
          {removals.slice(0, 20).map(r => (
            <View key={r.id} style={{ paddingVertical: spacing.xs, borderTopWidth: 1, borderTopColor: c.border }}>
              <Text style={{ fontSize: fontSize.sm, color: c.foreground, fontWeight: fontWeight.semibold }}>
                {r.tba ?? r.bag_id}{r.package_count > 1 ? ` · ${r.package_count} pkgs` : ''}
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>
                {r.status === 'removed' ? '✓ pulled' : 'flagged — pull & return'}
                {r.owner_route_number != null ? ` · from #${r.owner_route_number}` : ''}
                {r.locator ? ` · ${r.locator}` : ''}
              </Text>
            </View>
          ))}
        </View>
      )}

      {/* Misrouted packages — resolve at the AP before walkers depart. The
          sort computed where each belongs; one tap moves the package data
          with it (pull it from the wrong tote as you tap). */}
      {misroutes.length > 0 && (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.warning + '55' }]}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: 2 }}>
            <Text style={{ fontSize: fontSize.md }}>⚠️</Text>
            <Text style={[s.cardTitle, { flex: 1 }]}>Misrouted packages</Text>
            <Badge tone="warning">{misroutes.length}</Badge>
          </View>
          <Text style={s.cardSub}>Each package is in the wrong tote. Pull it from the FROM walker and hand it to the TO walker.</Text>
          {misroutes.slice(0, 12).map(({ flag, source, suggested }) => {
            const routeBadge = (num: number, name: string | null) => (
              <View style={{ backgroundColor: c.card, borderRadius: radius.sm, borderWidth: 1, borderColor: c.borderStrong,
                paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, alignItems: 'center', minWidth: 84 }}>
                <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.extrabold, color: c.foreground }}>#{num}</Text>
                <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }} numberOfLines={1}>{name ?? 'Unassigned'}</Text>
              </View>
            );
            return (
              <View key={flag.id} style={[s.misrouteRow, { borderColor: c.border, backgroundColor: c.surfaceMuted }]}>
                {/* Headline: where the package actually belongs (full GeoClient
                    address — no line cap; it's building-level, not excessively long) */}
                <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground }}>
                  📍 {flag.normalised_address ?? flag.destination_block_key ?? 'Unknown address'}
                </Text>
                {/* TBA (bold — the value already begins with 'TBA', no separate tag)
                    on the left; the tote it's currently in as a pill on the right
                    (future: pill tinted by the bag's color). */}
                <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm, marginTop: 2, marginBottom: spacing.sm }}>
                  {/* Secondary reference id — muted mono so it doesn't compete with
                      the bold address headline above it. */}
                  <Text selectable style={{ flex: 1, fontSize: fontSize.xs, fontWeight: fontWeight.medium, color: c.mutedForeground, fontVariant: ['tabular-nums'], letterSpacing: 0.3 }} numberOfLines={1}>
                    {flag.tba_number}
                  </Text>
                  {flag.current_bag_id ? (
                    <View style={s.bagPill}>
                      <Text selectable style={s.bagPillText}>{flag.current_bag_id}</Text>
                    </View>
                  ) : null}
                </View>
                {/* FROM → TO hand-off — balanced tri-column: FROM and TO share the
                    width around a fixed centered arrow, so it fills the row cleanly. */}
                <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                  <View style={{ flex: 1, alignItems: 'center', gap: 2 }}>
                    <Text style={{ fontSize: 9, color: c.mutedForeground, fontWeight: fontWeight.bold, letterSpacing: 0.6 }}>FROM</Text>
                    {routeBadge(source.route_number, source.executor?.name ?? null)}
                  </View>
                  <Text style={{ width: 40, textAlign: 'center', fontSize: fontSize.xxl, color: c.warning, fontWeight: fontWeight.bold }}>→</Text>
                  <View style={{ flex: 1, alignItems: 'center', gap: 2 }}>
                    <Text style={{ fontSize: 9, color: c.mutedForeground, fontWeight: fontWeight.bold, letterSpacing: 0.6 }}>TO</Text>
                    {suggested
                      ? routeBadge(suggested.route_number, suggested.executor?.name ?? null)
                      : <View style={{ paddingHorizontal: spacing.sm, paddingVertical: spacing.xs }}>
                          <Text style={{ fontSize: fontSize.xs, color: c.warning, fontWeight: fontWeight.semibold }}>Captain review</Text>
                        </View>}
                  </View>
                </View>
                {/* Action */}
                <View style={{ marginTop: spacing.sm }}>
                  {suggested ? (
                    <Button variant="primary" fullWidth
                      loading={resolvingFlag === flag.id}
                      onPress={() => resolveMisroute(flag.id, source.id, suggested.id)}>
                      {`Move to #${suggested.route_number}${suggested.executor?.name ? ` · ${suggested.executor?.name}` : ''}`}
                    </Button>
                  ) : (
                    <View style={{ backgroundColor: c.warning + '15', borderRadius: radius.md, borderWidth: 1, borderColor: c.warning + '40', padding: spacing.sm }}>
                      <Text style={{ fontSize: fontSize.xs, color: c.warning, fontWeight: fontWeight.semibold, textAlign: 'center' }}>
                        No covering route — flag for captain to reassign
                      </Text>
                    </View>
                  )}
                </View>
              </View>
            );
          })}
          {misroutes.length > 12 && (
            <Text style={[s.cardSub, { marginTop: spacing.sm, marginBottom: 0 }]}>…and {misroutes.length - 12} more — resolve these first, then refresh.</Text>
          )}
        </View>
      )}
      </>)}

      {/* Crew Roster — folded into its own sub-view (segmented bar above). Mark a
          walker/trainer/trainee departed when they leave; roll call; open a
          member's route detail. */}
      {apView === 'crew' && members.length > 0 && (() => {
        // Present members (non-driver, arrived) with no compliance record yet —
        // the exact set the Check-In #1 gate will flag. Drives the bulk shortcut.
        const presentUnrecorded = members
          .filter(m => m.role !== 'driver' && m.status === 'active')
          .filter(m => {
            const av = crewStatus[m.employee_id]?.availability;
            return av != null && av !== 'not_arrived' && av !== 'off_crew';
          })
          .filter(m => compliance[m.employee_id] == null)
          .map(m => m.employee_id);
        return (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.xs }}>
            <Text style={[s.cardTitle, { marginBottom: 0 }]}>Crew</Text>
            {isCaptain && !complianceSubmitted && presentUnrecorded.length > 0 && (
              <TouchableOpacity
                disabled={savingCompliance === '__bulk__'}
                onPress={() => markAllCompliant(presentUnrecorded)}
                style={{ paddingVertical: spacing.xs, paddingHorizontal: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: c.success }}
              >
                <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.success }}>
                  {savingCompliance === '__bulk__' ? 'Saving…' : `✓ Mark ${presentUnrecorded.length} compliant`}
                </Text>
              </TouchableOpacity>
            )}
          </View>
          {members
            .filter(m => m.role !== 'driver')
            .map(m => {
              const name = crew.find(cm => cm.employee_id === m.employee_id)?.name ?? m.role;
              const off = m.status !== 'active';
              const cs = crewStatus[m.employee_id];
              const tone = cs ? AVAIL_TONE[cs.availability] : null;
              const pct = cs?.route_completion_pct != null ? ` · ${Math.round(cs.route_completion_pct * 100)}%` : '';
              const stop = currentStops[m.employee_id];
              // ADR-228: compliance is captured for PRESENT crew (arrived), by the driver.
              const present = !off && !!cs && cs.availability !== 'not_arrived' && cs.availability !== 'off_crew';
              // A record must EXIST to count — the backend gate flags any present
              // member with no CrewCompliance row. Don't default to pass, or the
              // pills read ✓ while nothing is persisted (looks done, isn't). Each
              // pill's neutral/✓/✗ is driven by its own touched flag (item 2).
              const comp = compliance[m.employee_id] ?? { uniform_pass: true, cart_cover_pass: true, status: 'draft' };
              const compTouched = complianceTouched[m.employee_id] ?? { uniform_pass: false, cart_cover_pass: false };
              const initials = name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
              // ADR-216 phase 2: tapping a crew member with a route opens their
              // per-employee detail. Executor → their own route; a paired trainer
              // (no executor route) → the route they SUPERVISE (so they read as
              // "supervising #N", not route-less).
              const execRoute = routeByExecutor.get(m.employee_id);
              const supRoute = execRoute ? undefined : routeBySupervisor.get(m.employee_id);
              const memberRoute = execRoute ?? supRoute;
              const routeLabel = execRoute ? ` · route #${execRoute.route_number}`
                : supRoute ? ` · supervising #${supRoute.route_number}` : '';
              return (
                <View key={m.id} style={[s.crewRow, { borderColor: c.border, backgroundColor: c.surfaceMuted, opacity: off ? 0.6 : 1 }]}>
                  <TouchableOpacity
                    activeOpacity={memberRoute ? 0.6 : 1}
                    disabled={!memberRoute}
                    onPress={() => memberRoute && nav.navigate('CrewMemberDetail', { routeId: memberRoute.id, memberName: name })}
                    style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}
                  >
                    <Avatar initials={initials} name={name} color={getRoleColor(m.role as FieldRole, c)} size={40} />
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, textDecorationLine: off ? 'line-through' : 'none' }}>
                        {name}
                      </Text>
                      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'capitalize', marginTop: 1 }}>
                        {m.role}
                        {off ? ` · ${m.status}` : ''}
                        {routeLabel}
                        {cs && cs.trip_count > 0 ? ` · ${cs.trip_count} trip${cs.trip_count === 1 ? '' : 's'}` : ''}
                      </Text>
                    </View>
                    {/* Current state tag — always shown, separated from any actions. */}
                    {tone && (
                      <Badge tone={tone} dot>{AVAIL_LABEL[cs!.availability]}{pct}</Badge>
                    )}
                    {memberRoute && (
                      <Text style={{ fontSize: fontSize.lg, color: c.mutedForeground, marginLeft: 2 }}>›</Text>
                    )}
                  </TouchableOpacity>

                  {/* Done-for-day action — only for an AVAILABLE member (arrived, no
                      active route). You can't send home someone who's Not Present /
                      absent, and someone mid-route isn't done yet. Own row so it
                      reads as a button, not the state. */}
                  {!off && cs?.availability === 'available' && (
                    <View style={{ marginTop: spacing.sm }}>
                      <Button variant="outline" size="sm" fullWidth
                        loading={departingId === m.id}
                        onPress={() => markDeparted(m, name)}>
                        Mark Done for the Day
                      </Button>
                    </View>
                  )}

                  {/* Roll-call actions — a separate row beneath the state tag so the
                      action verbs ("Mark As Present" / "Mark NCNS") read as buttons,
                      not as the current state. Only while the member is Not Present. */}
                  {!off && cs?.availability === 'not_arrived' && (
                    <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm }}>
                      <View style={{ flex: 1 }}>
                        <Button variant="success" size="sm" fullWidth
                          loading={rollCallId === m.employee_id}
                          onPress={() => takeRollCall(m.employee_id, false)}>
                          Mark As Present
                        </Button>
                      </View>
                      <View style={{ flex: 1 }}>
                        <Button variant="danger" size="sm" fullWidth
                          disabled={rollCallId === m.employee_id}
                          onPress={() => confirmNCNS(m.employee_id, name)}>
                          Mark NCNS
                        </Button>
                      </View>
                    </View>
                  )}
                  {/* Reassign / Drop — only on an executor route that hasn't started
                      yet (assigned). Once the walker's out (in_progress), the route
                      can't be dropped; reassign is still handled via back-at-truck.
                      Makes "pass a route" / "drop a route" discoverable (was a hidden
                      tap-the-name gesture only in the wave proposal). */}
                  {execRoute && execRoute.status === 'assigned' && (
                    <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm }}>
                      <View style={{ flex: 1 }}>
                        <Button variant="outline" size="sm" fullWidth
                          disabled={routeActionId === execRoute.id}
                          onPress={() => setReassignRoute({ id: execRoute.id, number: execRoute.route_number })}>
                          Reassign
                        </Button>
                      </View>
                      <View style={{ flex: 1 }}>
                        <Button variant="outline" size="sm" fullWidth
                          loading={routeActionId === execRoute.id}
                          onPress={() => dropRoute(execRoute.id, execRoute.route_number, name)}>
                          Drop
                        </Button>
                      </View>
                    </View>
                  )}
                  {/* ADR-229: emergency cover — only on an IN-PROGRESS route where
                      the walker has already raised request-help. Peels the remaining
                      stops into a new coverable route (Reassign/Drop above are for a
                      route that hasn't started; this is the mid-route lifeline). */}
                  {execRoute && execRoute.status === 'in_progress' && execRoute.help_requested_at && (
                    <View style={{ marginTop: spacing.sm }}>
                      <Button variant="danger" size="sm" fullWidth
                        loading={routeActionId === execRoute.id}
                        onPress={() => coverRemaining(execRoute.id, execRoute.route_number, name)}>
                        🚑 Cover remaining stops
                      </Button>
                    </View>
                  )}
                  {/* ADR-228: any captain (driver or trainer) records uniform +
                      cart-cover for each present member, live on the shared roster.
                      Saved as draft; Check-In #1 finalizes + ships it to Dispatch.
                      Applies to every present member, trainers included. */}
                  {isCaptain && present && !complianceSubmitted && (
                    <>
                      {!(compTouched.uniform_pass && compTouched.cart_cover_pass) && (
                        <Text style={{ fontSize: fontSize.xs, color: c.warning, marginTop: spacing.sm, marginBottom: -spacing.xs / 2 }}>
                          Tap each to record — not checked yet.
                        </Text>
                      )}
                      <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm }}>
                        {([['uniform_pass', 'Uniform'], ['cart_cover_pass', 'Cart cover']] as const).map(([field, label]) => {
                          const set = compTouched[field];          // per-field (item 2)
                          const pass = comp[field];
                          // Untapped → neutral ○ (tapping sets THIS field to pass, not both).
                          // Tapped → ✓/✗ toggling only its own value.
                          const tint = !set ? c.mutedForeground : pass ? c.success : c.danger;
                          const glyph = !set ? '○' : pass ? '✓' : '✗';
                          return (
                            <TouchableOpacity
                              key={field}
                              disabled={savingCompliance === m.employee_id || savingCompliance === '__bulk__'}
                              onPress={() => setComplianceField(m.employee_id, field, set ? !pass : true)}
                              style={{
                                flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                                gap: spacing.xs, paddingVertical: spacing.xs + 2, borderRadius: radius.md, borderWidth: 1,
                                borderColor: tint,
                                backgroundColor: tint + (set ? '15' : '08'),
                              }}
                            >
                              <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.bold, color: tint }}>
                                {glyph} {label}
                              </Text>
                            </TouchableOpacity>
                          );
                        })}
                      </View>
                    </>
                  )}
                  {/* Paired arrival & rebalance (ADR-212) — folded into the paired
                      trainee's own crew row so it reads as "this trainee joins you"
                      rather than a floating card. The trainer confirms the pair is
                      present; the backend attaches the trainer as supervisor on the
                      TRAINEE's route and lifts the 1.5× ceiling. */}
                  {routes.length > 0 && pairedTrainee?.employee_id === m.employee_id && (
                    rebalanced ? (
                      <View style={{ marginTop: spacing.sm, gap: spacing.xs }}>
                        <Text style={{ fontSize: fontSize.xs, color: c.success, fontWeight: fontWeight.semibold }}>
                          🤝 Riding with you at 1.5× capacity
                        </Text>
                        {/* ADR-213: split off if the pair can run two solo routes. */}
                        <Button variant="secondary" size="sm" fullWidth loading={splitting} onPress={runSplit}>
                          ✂️ Split — take my own route
                        </Button>
                      </View>
                    ) : (
                      <View style={{ marginTop: spacing.sm, gap: spacing.xs }}>
                        <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>
                          {traineeArrivedAt
                            ? `📍 Arrived ${new Date(traineeArrivedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} — rebalance to share your route at 1.5×.`
                            : 'Waiting on arrival — rebalance anyway if they\'re next to you.'}
                        </Text>
                        <Button variant={traineeArrivedAt ? 'success' : 'primary'} size="sm" fullWidth
                          loading={rebalancing} onPress={runRebalance}>
                          🤝 Confirm Arrival & Rebalance (1.5×)
                        </Button>
                      </View>
                    )
                  )}
                  {stop && (
                    <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 }}>
                      📍 On stop {stop.stop_sequence}/{stop.total}{stop.normalised_address ? `: ${stop.normalised_address}` : ''}
                    </Text>
                  )}
                </View>
              );
            })}
        </View>
        );
      })()}

      {/* Live reassign picker (ADR-226) — pass an already-assigned route to another
          PRESENT crew member. pickerOptions is already present-gated. */}
      {reassignRoute !== null && (
        <Modal transparent animationType="fade" onRequestClose={() => setReassignRoute(null)}>
          <TouchableOpacity style={ms.backdrop} activeOpacity={1} onPress={() => setReassignRoute(null)}>
            <View style={[ms.picker, { backgroundColor: c.card }]}>
              <Text style={[ms.title, { color: c.foreground }]}>Route {reassignRoute.number} → who takes it?</Text>
              {pickerOptions.length === 0 ? (
                <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground, padding: spacing.sm }}>
                  No other present crew to take this route.
                </Text>
              ) : (
                <ScrollView style={{ maxHeight: 320 }}>
                  {pickerOptions.map(m => (
                    <TouchableOpacity key={m.employee_id} style={[ms.propRow, { borderBottomColor: c.border }]}
                      disabled={routeActionId === reassignRoute.id}
                      onPress={() => liveReassign(reassignRoute.id, m)}>
                      <Text style={[ms.propName, { color: c.foreground, flex: 1 }]}>{m.name}</Text>
                      <Text style={[ms.propMeta, { color: c.mutedForeground, textTransform: 'capitalize' }]}>{m.role}</Text>
                    </TouchableOpacity>
                  ))}
                </ScrollView>
              )}
            </View>
          </TouchableOpacity>
        </Modal>
      )}

      {apView === 'sort' && (<>
      {/* Route lists */}
      {/* ADR-216 phase 2: OUT NOW folded into the Crew card (each assigned member's
          route opens from their card). Only UNASSIGNED (no crew member yet) and
          COMPLETED remain as standalone lists. */}
      {[{ label: 'UNASSIGNED', data: unassigned }, { label: 'COMPLETED', data: completed }]
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
                <View style={[ms.conflictBox, { backgroundColor: c.warning + '15', borderColor: c.warning + '44' }]}>
                  {conflicts.map((cf, i) => (
                    <Text key={i} style={[ms.conflictText, { color: c.warning }]}>⚠ {cf}</Text>
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
                    ? <ActivityIndicator color={c.primaryForeground} size="small" />
                    : <Text style={{ color: c.primaryForeground, fontWeight: '700', fontSize: 13 }}>Send Wave</Text>}
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
      </>)}
    </ScreenShell>
  );
}

// ── RouteRow — expandable route card showing blocks + addresses ───────────────

function RouteRow({ route, c, s }: { route: RouteResp; c: ThemeColors; s: ReturnType<typeof styles> }) {
  const [expanded, setExpanded] = useState(false);
  const effortC = effortColor(route.effort_class, c);

  // Delivered stops (ADR-194). Chips and drill-down come from here so flagged
  // riders (shown in the misroute card instead) don't masquerade as coverage.
  // Old routes (stops null) fall back to the flat carried lists.
  const stops = route.stops ?? null;
  const chipBlocks = stops ? [...new Set(stops.map(st => st.block_key))] : route.block_keys;

  const animateNext = useLayoutTransition();
  const toggle = () => {
    animateNext();
    setExpanded(e => !e);
  };

  return (
    <View style={[s.routeRow, { backgroundColor: c.card, borderColor: c.border, flexDirection: 'column', padding: 0 }]}>
      <TouchableOpacity
        style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm }}
        onPress={toggle}
        activeOpacity={0.7}
      >
        <View style={[s.routeNum, { backgroundColor: effortC + '1E' }]}>
          <Text style={[s.routeNumText, { color: effortC }]}>{route.route_number}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[s.routeName, { color: c.foreground }]}>
            {route.executor?.name ?? 'Unassigned'}
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

  const animateNext = useLayoutTransition();
  const toggle = () => {
    animateNext();
    setExpanded(e => !e);
  };

  const effortC = effortColor(proposal.effort_class, c);

  return (
    <View style={{ borderBottomWidth: 1, borderBottomColor: c.border }}>
      {/* Header row — tap left to expand, tap right to reassign */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.sm }}>
        <TouchableOpacity onPress={toggle} activeOpacity={0.7}>
          <View style={[s.routeNum, { backgroundColor: effortC + '1E' }]}>
            <Text style={[s.routeNumText, { color: effortC }]}>{proposal.route_number}</Text>
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
          <Text style={{ fontSize: fontSize.xs, color: overridden ? c.warning : c.mutedForeground, fontWeight: fontWeight.semibold }}>
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
  // Segmented sub-view bar (mirrors the Incident tab's Report/History bar).
  subTabBar:      { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: c.border, backgroundColor: c.surface },
  subTab:         { flex: 1, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  subTabActive:   { borderBottomWidth: 2, borderBottomColor: c.primary },
  subTabText:     { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium },
  subTabTextActive: { color: c.primary, fontWeight: fontWeight.semibold },
  // bag_id pill on a misroute row (future: bg tinted by the bag's color).
  bagPill:        { backgroundColor: c.surface, borderWidth: 1, borderColor: c.border, borderRadius: radius.full ?? 999, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  bagPillText:    { fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.foreground, letterSpacing: 0.3 },
  crewRow:    { borderRadius: radius.md, borderWidth: 1, padding: spacing.sm + 2, marginTop: spacing.sm },
  misrouteRow:{ borderRadius: radius.md, borderWidth: 1, padding: spacing.md, marginTop: spacing.sm },
  cardSub:    { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: 2, marginBottom: spacing.sm },
  primaryBtn: { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  // `primaryForeground`, not '#fff'. On dark theme `primary` is a LIGHT navy
  // (#7E95F1), so white text measures 2.82:1 — a WCAG failure on the button
  // that commits the sort. The token is 6.66:1 and follows the theme.
  // Found on device 2026-08-04.
  primaryBtnText: { color: c.primaryForeground, fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  summaryRow: { flexDirection: 'row', marginBottom: spacing.sm },

  sectionLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, letterSpacing: 0.8, marginBottom: spacing.xs, marginTop: spacing.xs },
  routeRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderRadius: radius.md, borderWidth: 1, padding: spacing.sm, marginBottom: 6 },
  routeNum:   { width: 34, height: 34, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  routeNumText: { fontSize: fontSize.sm, fontWeight: fontWeight.extrabold },
  routeName:  { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  routeMeta:  { fontSize: fontSize.xs, marginTop: 1 },
  routeStatus:{ fontSize: fontSize.xs, textTransform: 'capitalize' },
});
