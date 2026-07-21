import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  Alert, Modal, TextInput, ScrollView, LayoutAnimation, Platform, UIManager,
} from 'react-native';

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import RouteStopsList, { type RouteStop } from '@components/route/RouteStopsList';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

/** Walker/trainee route execution — rebuilt on the CURRENT API (the previous
 * version called /walker-routes/assignment + /trips which no longer exist, so
 * the screen permanently showed the empty state).
 *
 * Flow: GET /walker-routes/me/routes → active route →
 *       GET /rts/stops/{route_id}/next-suggestion (ordered remaining stops
 *       with urgency signals) → complete stops / flag RTS / report missing →
 *       PATCH status completed → POST back-at-truck (enters the wave pool).
 */

type RouteResp = {
  id: string;
  route_number: number;
  status: string;                 // assigned | in_progress | completed
  effort_class: string;
  package_count: number;
  block_keys: string[];
  normalised_addresses: string[];
  stops: RouteStop[] | null;      // null = route predates ADR-194 → fall back to flat lists
  returned_at: string | null;
  wave_number: number;
  // ADR-212: membership. executor = assignee-of-record; supervisors = trainers.
  executor: { id: string; name: string } | null;
  supervisors: { id: string; name: string }[];
};

type StopSignal = { signal: string; reason: string; urgency: number };
type BagGroup = { bag_id: string; tba_numbers: string[] };
type Stop = {
  normalised_address: string;
  block_key: string;
  tba_numbers: string[];
  bags: BagGroup[];
  packages_total: number;
  signals: StopSignal[];
  urgency_score: number;
  building_type?: string | null;
  operational_note?: string | null;
};

const RTS_TYPES: { value: string; label: string }[] = [
  { value: 'no_access',                          label: 'No access' },
  { value: 'business_closed',                    label: 'Business closed' },
  { value: 'package_damaged',                    label: 'Package damaged' },
  { value: 'inclement_weather',                  label: 'Inclement weather' },
  { value: 'customer_requested_future_delivery', label: 'Customer requested future delivery' },
  { value: 'customer_cancelled_order',           label: 'Customer cancelled order' },
];

const BUILDING_TYPES: { value: string; label: string }[] = [
  { value: 'receptionist',     label: 'Receptionist' },
  { value: 'walkup',           label: 'Walk-up' },
  { value: 'elevator',         label: 'Elevator building' },
  { value: 'doorman',          label: 'Doorman' },
  { value: 'mailroom',         label: 'Mailroom' },
  { value: 'biz_freight',      label: 'Business — freight entrance' },
  { value: 'biz_security',     label: 'Business — security desk' },
  { value: 'biz_loading_dock', label: 'Business — loading dock' },
];

// Building signal → themed color (ADR-207). Urgent-close signals = danger,
// timing/wait warnings = warning, informational = info/primary.
function signalColor(signal: string, c: ThemeColors): string {
  switch (signal) {
    case 'closing_soon':
    case 'closed_today':      return c.danger;
    case 'break_approaching':
    case 'high_wait':         return c.warning;
    case 'not_open_yet':      return c.info;
    case 'rts_history':       return c.primary;
    default:                  return c.mutedForeground;
  }
}

export default function MyRouteScreen() {
  const c = useColors();
  const { fetchId } = useEmployeeId();
  const { hasRole } = useAuth();
  const s = styles(c);

  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [route,      setRoute]      = useState<RouteResp | null>(null);
  const [stops,      setStops]      = useState<Stop[]>([]);
  const [acting,     setActing]     = useState(false);
  const [completingStop, setCompletingStop] = useState<string | null>(null);
  const [startedAddress, setStartedAddress] = useState<string | null>(null);   // ADR-197: stop in progress
  const [rtsTarget,  setRtsTarget]  = useState<{ tba: string; kind: 'rts' | 'missing' } | null>(null);
  const [bpTarget,   setBpTarget]   = useState<Stop | null>(null);

  const load = useCallback(async (opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true);
    try {
      const eid = await fetchId();
      const now = new Date();
      const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
      const res = await apiClient.get(`/walker-routes/me/routes?route_date=${today}`);
      const routes: RouteResp[] = res.data ?? [];

      // ADR-212: "Mine" = every route I participate in (executor or supervisor).
      // me/routes returns the whole TRUCK for trainers; a trainer on a pair is now
      // a SUPERVISOR participant on the trainee's route, so this single filter
      // covers both the solo and the paired-trainer case (no dispatch-pairing
      // fallback needed).
      const mine = routes.filter(r =>
        r.executor?.id === eid || r.supervisors.some(s => s.id === eid),
      );

      const active =
        mine.find(r => r.status === 'in_progress')
        ?? mine.find(r => r.status === 'assigned')
        ?? mine.find(r => r.status === 'completed' && !r.returned_at)
        ?? null;
      setRoute(active);
      if (active && active.status !== 'assigned') {
        const sug = await apiClient.get(`/rts/stops/${active.id}/next-suggestion`);
        setStops(sug.data ?? []);
      } else {
        setStops([]);
      }
    } catch {
      setRoute(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // ── Route-level actions ──────────────────────────────────────────────────

  const patchStatus = async (status: string) => {
    if (!route) return;
    setActing(true);
    try {
      await apiClient.patch(`/walker-routes/routes/${route.id}/status`, { status });
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not update route status.'));
    } finally {
      setActing(false);
    }
  };

  const requestHelp = () => {
    if (!route) return;
    Alert.alert(
      'Request help?',
      'Your trainer gets an alert with your route context (dispatch if you have no trainer today).',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Send Help Request',
          style: 'destructive',
          onPress: async () => {
            try {
              const res = await apiClient.post(`/walker-routes/routes/${route.id}/request-help`);
              Alert.alert('Help is coming', res.data?.detail ?? 'Your trainer has been notified.');
            } catch (e) {
              Alert.alert('Error', errorText(e, 'Could not send the request. Call the station.'));
            }
          },
        },
      ],
    );
  };

  const backAtTruck = async () => {
    if (!route) return;
    setActing(true);
    try {
      await apiClient.post(`/walker-routes/routes/${route.id}/back-at-truck`);
      await load();
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not record your return.'));
    } finally {
      setActing(false);
    }
  };

  // ── Stop-level actions ───────────────────────────────────────────────────

  const startStop = async (stop: Stop) => {
    if (!route) return;
    // Optimistically mark started so dispatch/captain tracking lights up and the
    // walker sees the in-progress state immediately (ADR-197). Server call is
    // best-effort — a failure just clears the local flag, it never blocks work.
    setStartedAddress(stop.normalised_address);
    try {
      await apiClient.post('/rts/stops/start', {
        route_id: route.id,
        tba_numbers: stop.tba_numbers,
      });
    } catch {
      setStartedAddress(null);
    }
  };

  const completeStop = async (stop: Stop) => {
    if (!route) return;
    setCompletingStop(stop.normalised_address);
    try {
      await apiClient.post('/rts/stops', {
        route_id: route.id,
        tba_numbers: stop.tba_numbers,
        completed_at: new Date().toISOString(),
      });
      if (startedAddress === stop.normalised_address) setStartedAddress(null);
      const sug = await apiClient.get(`/rts/stops/${route.id}/next-suggestion`);
      setStops(sug.data ?? []);
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not complete the stop.'));
    } finally {
      setCompletingStop(null);
    }
  };

  const submitRts = async (tba: string, rtsType: string, explanation: string) => {
    if (!route) return;
    await apiClient.post('/rts/packages', {
      route_id: route.id,
      tba_number: tba,
      rts_type: rtsType,
      rts_explanation: explanation,
    });
    setRtsTarget(null);
    const sug = await apiClient.get(`/rts/stops/${route.id}/next-suggestion`);
    setStops(sug.data ?? []);
  };

  const submitMissing = async (tba: string) => {
    if (!route) return;
    await apiClient.post('/rts/missing', { route_id: route.id, tba_number: tba });
    setRtsTarget(null);
    const sug = await apiClient.get(`/rts/stops/${route.id}/next-suggestion`);
    setStops(sug.data ?? []);
  };

  // ── Render ───────────────────────────────────────────────────────────────

  if (!loading && !route) {
    return (
      <ScreenShell title="My Route" subtitle="No route assigned yet."
        refreshing={refreshing} onRefresh={() => load({ refresh: true })}>
        <View style={s.center}>
          <Text style={{ fontSize: 40 }}>🗺️</Text>
          <Text style={s.emptyTitle}>No route yet</Text>
          <Text style={s.emptySub}>Routes appear after the trainer distributes the wave at the anchor point.</Text>
        </View>
      </ScreenShell>
    );
  }

  const remainingPkgs = stops.reduce((n, st) => n + st.packages_total, 0);
  const nextStop = stops[0] ?? null;
  const laterStops = stops.slice(1);
  const allDelivered = route?.status === 'in_progress' && stops.length === 0;

  return (
    <ScreenShell
      title="My Route"
      subtitle={route ? `Route ${route.route_number} · Wave ${route.wave_number}` : undefined}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load({ refresh: true })}
    >
      {/* Hero — route identity + phase-appropriate primary action */}
      {route && (
        <View style={s.heroCard}>
          <View style={s.heroRow}>
            <View style={{ flex: 1 }}>
              <Text style={s.heroLabel}>ROUTE {route.route_number}</Text>
              <Text style={s.heroTitle}>
                {route.status === 'assigned' ? 'Ready to start'
                  : route.status === 'in_progress' ? `${stops.length} stop${stops.length === 1 ? '' : 's'} remaining`
                  : route.returned_at ? 'Done for this wave' : 'Head back to the truck'}
              </Text>
              <Text style={s.heroSub}>
                {route.status === 'in_progress'
                  ? `${remainingPkgs} package${remainingPkgs === 1 ? '' : 's'} to deliver`
                  : `${route.package_count} packages · ${route.effort_class}`}
              </Text>
            </View>
            <View style={[s.effortChip, { backgroundColor: c.primaryLight }]}>
              <Text style={[s.effortChipText, { color: c.primary }]}>{route.effort_class}</Text>
            </View>
          </View>

          {route.status === 'assigned' && (
            <TouchableOpacity style={[s.primaryBtn, { backgroundColor: c.primary }]} onPress={() => patchStatus('in_progress')} disabled={acting}>
              {acting ? <ActivityIndicator color="#fff" /> : <Text style={s.primaryBtnText}>Start Route</Text>}
            </TouchableOpacity>
          )}
          {allDelivered && (
            <TouchableOpacity style={[s.primaryBtn, { backgroundColor: c.success }]} onPress={() => patchStatus('completed')} disabled={acting}>
              {acting ? <ActivityIndicator color="#fff" /> : <Text style={s.primaryBtnText}>✓ All delivered — Complete Route</Text>}
            </TouchableOpacity>
          )}
          {route.status === 'completed' && !route.returned_at && (
            <TouchableOpacity style={[s.primaryBtn, { backgroundColor: c.primary }]} onPress={backAtTruck} disabled={acting}>
              {acting ? <ActivityIndicator color="#fff" /> : <Text style={s.primaryBtnText}>🚚 Back at Truck</Text>}
            </TouchableOpacity>
          )}
          {route.returned_at && (
            <View style={[s.doneBanner, { backgroundColor: c.success + '15' }]}>
              <Text style={[s.doneBannerText, { color: c.success }]}>
                ✓ Returned {new Date(route.returned_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} — you're in the pool for the next wave
              </Text>
            </View>
          )}

          {/* Route territory — block keys + address list so the walker knows
              what they have before they start, and can reference it en route */}
          {(route.block_keys?.length > 0 || route.normalised_addresses?.length > 0 || (route.stops?.length ?? 0) > 0) && (
            <RouteTerritorySection
              blockKeys={route.block_keys ?? []}
              addresses={route.normalised_addresses ?? []}
              routeStops={route.stops ?? null}
              c={c}
            />
          )}

          {/* ADR-187 D8 — trainee lifeline, all phases (trainer may not be
              physically present even in 1–3) */}
          {hasRole('trainee') && route.status === 'in_progress' && (
            <TouchableOpacity style={[s.helpBtn, { borderColor: c.danger + '55' }]} onPress={requestHelp}>
              <Text style={s.helpBtnText}>🆘 Request Help from my Trainer</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {/* Next stop — the one decision the walker needs, made prominent */}
      {route?.status === 'in_progress' && nextStop && (
        <StopCard
          stop={nextStop} featured c={c}
          completing={completingStop === nextStop.normalised_address}
          started={startedAddress === nextStop.normalised_address}
          onStart={() => startStop(nextStop)}
          onComplete={() => completeStop(nextStop)}
          onFlag={(tba, kind) => setRtsTarget({ tba, kind })}
          onBuildingInfo={() => setBpTarget(nextStop)}
        />
      )}

      {/* Later stops, in suggested order */}
      {laterStops.length > 0 && (
        <>
          <Text style={s.sectionLabel}>UP NEXT · {laterStops.length}</Text>
          {laterStops.map(st => (
            <StopCard
              key={st.normalised_address}
              stop={st} c={c}
              completing={completingStop === st.normalised_address}
              onComplete={() => completeStop(st)}
              onFlag={(tba, kind) => setRtsTarget({ tba, kind })}
              onBuildingInfo={() => setBpTarget(st)}
            />
          ))}
        </>
      )}

      {/* RTS / missing modal */}
      {rtsTarget && (
        <FlagModal
          target={rtsTarget}
          c={c}
          onClose={() => setRtsTarget(null)}
          onSubmitRts={submitRts}
          onSubmitMissing={submitMissing}
        />
      )}

      {/* Building profile at the door — feeds the sort algorithm's workload
          intelligence and the next walker's operational notes */}
      {bpTarget && (
        <BuildingProfileModal stop={bpTarget} c={c} onClose={() => setBpTarget(null)} />
      )}
    </ScreenShell>
  );
}

// ── Route territory section — block keys + address list ───────────────────

function RouteTerritorySection({ blockKeys, addresses, routeStops, c }: {
  blockKeys: string[]; addresses: string[]; routeStops: RouteStop[] | null; c: ThemeColors;
}) {
  const [expanded, setExpanded] = useState(false);

  // Delivered stops (ADR-194) drive the territory; flat lists are the
  // fallback for routes that predate the stops column.
  const chipBlocks = routeStops ? [...new Set(routeStops.map(st => st.block_key))] : blockKeys;
  const stopCount = routeStops ? routeStops.length : addresses.length;

  return (
    <View style={{ marginTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.border + '88', paddingTop: spacing.sm }}>
      <TouchableOpacity
        onPress={() => { LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut); setExpanded(e => !e); }}
        style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}
        activeOpacity={0.7}
      >
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, flexWrap: 'wrap', flex: 1 }}>
          <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, marginRight: 4 }}>TERRITORY</Text>
          {chipBlocks.slice(0, 3).map(bk => (
            <View key={bk} style={{ backgroundColor: c.primaryLight, borderRadius: radius.xs, paddingHorizontal: 6, paddingVertical: 2 }}>
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.primary }}>{bk}</Text>
            </View>
          ))}
          {chipBlocks.length > 3 && (
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>+{chipBlocks.length - 3}</Text>
          )}
        </View>
        <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginLeft: spacing.sm }}>
          {expanded ? '▲ Hide' : `▼ ${stopCount} stop${stopCount === 1 ? '' : 's'}`}
        </Text>
      </TouchableOpacity>

      {expanded && (
        <View style={{ marginTop: spacing.sm }}>
          {routeStops && routeStops.length > 0 ? (
            <RouteStopsList stops={routeStops} c={c} />
          ) : (
            <View style={{ gap: 6 }}>
              {addresses.map((addr, i) => (
                <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <View style={{ width: 4, height: 4, borderRadius: 2, backgroundColor: c.mutedForeground, flexShrink: 0, marginTop: 1 }} />
                  <Text style={{ fontSize: fontSize.xs, color: c.foreground }}>{addr}</Text>
                </View>
              ))}
            </View>
          )}
        </View>
      )}
    </View>
  );
}

// ── Building profile modal ─────────────────────────────────────────────────

function BuildingProfileModal({ stop, c, onClose }: {
  stop: Stop; c: ThemeColors; onClose: () => void;
}) {
  const [buildingType, setBuildingType] = useState('walkup');
  const [note, setNote]                 = useState('');
  const [submitting, setSubmitting]     = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      await apiClient.post('/building-profiles/', {
        normalised_address: stop.normalised_address,
        block_key: stop.block_key,
        building_type: buildingType,
        raw_note: note.trim() || undefined,
      });
      onClose();
      Alert.alert('Thanks!', 'Building info submitted — it helps route this address better.');
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not submit building info.'));
      setSubmitting(false);
    }
  };

  return (
    <Modal transparent animationType="fade" onRequestClose={onClose}>
      <View style={ms.backdrop}>
        <View style={[ms.sheet, { backgroundColor: c.card }]}>
          <Text style={[ms.title, { color: c.foreground }]}>🏢 Building info</Text>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.sm }}>
            {stop.normalised_address}
          </Text>
          <ScrollView style={{ maxHeight: 260 }}>
            {BUILDING_TYPES.map(t => (
              <TouchableOpacity key={t.value} style={ms.reasonRow} onPress={() => setBuildingType(t.value)}>
                <View style={[ms.radio, { borderColor: buildingType === t.value ? c.primary : c.border }]}>
                  {buildingType === t.value && <View style={[ms.radioDot, { backgroundColor: c.primary }]} />}
                </View>
                <Text style={[ms.reasonText, { color: c.foreground }]}>{t.label}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <TextInput
            style={[ms.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
            value={note}
            onChangeText={setNote}
            placeholder="Anything the next walker should know? (optional)"
            placeholderTextColor={c.mutedForeground}
            multiline
          />
          <View style={ms.btnRow}>
            <TouchableOpacity style={[ms.cancelBtn, { borderColor: c.border }]} onPress={onClose} disabled={submitting}>
              <Text style={{ color: c.mutedForeground, fontWeight: '600', fontSize: 13 }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[ms.submitBtn, { backgroundColor: c.primary }]} onPress={submit} disabled={submitting}>
              {submitting
                ? <ActivityIndicator color="#fff" size="small" />
                : <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>Submit</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// ── Stop card ──────────────────────────────────────────────────────────────

function StopCard({ stop, featured, completing, started, onStart, onComplete, onFlag, onBuildingInfo, c }: {
  stop: Stop; featured?: boolean; completing: boolean;
  started?: boolean;
  onStart?: () => void;
  onComplete: () => void;
  onFlag: (tba: string, kind: 'rts' | 'missing') => void;
  onBuildingInfo: () => void;
  c: ThemeColors;
}) {
  const [expanded, setExpanded] = useState(!!featured);
  const topSignal = stop.signals?.[0] ?? null;

  return (
    <View style={[
      cs.card,
      { backgroundColor: c.card, borderColor: featured ? c.primary + '77' : c.border, borderWidth: featured ? 1.5 : 1 },
    ]}>
      <TouchableOpacity style={cs.header} onPress={() => setExpanded(e => !e)} activeOpacity={0.7}>
        <View style={{ flex: 1 }}>
          {featured && (
            <Text style={[cs.nextLabel, { color: started ? c.success : c.primary }]}>
              {started ? '● IN PROGRESS' : 'NEXT STOP'}
            </Text>
          )}
          <Text style={[cs.address, { color: c.foreground }]}>{stop.normalised_address}</Text>
          <Text style={[cs.meta, { color: c.mutedForeground }]}>
            {stop.packages_total} pkg{stop.packages_total === 1 ? '' : 's'}
            {stop.building_type ? ` · ${stop.building_type.replace(/_/g, ' ')}` : ''}
          </Text>
        </View>
        <Text style={{ color: c.mutedForeground, fontSize: 12 }}>{expanded ? '▲' : '▼'}</Text>
      </TouchableOpacity>

      {/* Urgency signals */}
      {stop.signals?.length > 0 && (
        <View style={cs.signalRow}>
          {stop.signals.slice(0, 2).map(sig => (
            <View key={sig.signal} style={[cs.signalChip, { backgroundColor: signalColor(sig.signal, c) + '1A' }]}>
              <Text style={[cs.signalText, { color: signalColor(sig.signal, c) }]}>{sig.reason}</Text>
            </View>
          ))}
        </View>
      )}

      {/* Operational note from BuildingProfile */}
      {expanded && stop.operational_note && (
        <View style={[cs.noteBox, { backgroundColor: c.surfaceMuted }]}>
          <Text style={[cs.noteText, { color: c.foreground }]}>📝 {stop.operational_note}</Text>
        </View>
      )}

      {/* Packages grouped by bag — long-press a TBA to flag it */}
      {expanded && (
        <View style={cs.bagWrap}>
          {stop.bags.map(bag => (
            <View key={bag.bag_id} style={cs.bagRow}>
              <Text style={[cs.bagLabel, { color: c.mutedForeground }]}>{bag.bag_id}</Text>
              <View style={cs.tbaWrap}>
                {bag.tba_numbers.map(tba => (
                  <TouchableOpacity
                    key={tba}
                    style={[cs.tbaChip, { backgroundColor: c.surfaceMuted, borderColor: c.border }]}
                    onLongPress={() => onFlag(tba, 'rts')}
                    onPress={() => onFlag(tba, 'rts')}
                  >
                    <Text style={[cs.tbaText, { color: c.foreground }]}>{tba.slice(-6)}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          ))}
          <Text style={[cs.tbaHint, { color: c.mutedForeground }]}>Tap a package to flag RTS or missing</Text>
        </View>
      )}

      {expanded && (
        <>
          {/* Start this stop (ADR-197) — only the featured next stop, and only
              until it's marked in progress. Lets dispatch/captain see where the
              walker is; the walker taps it as they arrive at the building. */}
          {featured && onStart && !started && (
            <TouchableOpacity
              style={[cs.startBtn, { borderColor: c.primary }]}
              onPress={onStart}
            >
              <Text style={[cs.startBtnText, { color: c.primary }]}>📍 Start this stop</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity
            style={[cs.completeBtn, { backgroundColor: c.success }]}
            onPress={onComplete}
            disabled={completing}
          >
            {completing
              ? <ActivityIndicator color="#fff" size="small" />
              : <Text style={cs.completeBtnText}>✓ Delivered — Complete Stop</Text>}
          </TouchableOpacity>
          {/* Only offer the report when no verified profile exists yet */}
          {!stop.building_type && (
            <TouchableOpacity style={cs.bpBtn} onPress={onBuildingInfo}>
              <Text style={[cs.bpBtnText, { color: c.mutedForeground }]}>🏢 Report building info</Text>
            </TouchableOpacity>
          )}
        </>
      )}
    </View>
  );
}

// ── RTS / missing modal ────────────────────────────────────────────────────

function FlagModal({ target, c, onClose, onSubmitRts, onSubmitMissing }: {
  target: { tba: string; kind: 'rts' | 'missing' };
  c: ThemeColors;
  onClose: () => void;
  onSubmitRts: (tba: string, rtsType: string, explanation: string) => Promise<void>;
  onSubmitMissing: (tba: string) => Promise<void>;
}) {
  const [kind, setKind]           = useState<'rts' | 'missing'>(target.kind);
  const [rtsType, setRtsType]     = useState('no_access');
  const [explanation, setExpl]    = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      if (kind === 'missing') {
        await onSubmitMissing(target.tba);
      } else {
        if (!explanation.trim()) {
          Alert.alert('Required', 'Please describe why this package is going back.');
          setSubmitting(false);
          return;
        }
        await onSubmitRts(target.tba, rtsType, explanation.trim());
      }
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not flag the package. Try again.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal transparent animationType="fade" onRequestClose={onClose}>
      <View style={ms.backdrop}>
        <View style={[ms.sheet, { backgroundColor: c.card }]}>
          <Text style={[ms.title, { color: c.foreground }]}>Flag package …{target.tba.slice(-6)}</Text>

          {/* Kind toggle */}
          <View style={ms.kindRow}>
            {(['rts', 'missing'] as const).map(k => (
              <TouchableOpacity
                key={k}
                style={[ms.kindBtn, { borderColor: c.border }, kind === k && { backgroundColor: c.primaryLight, borderColor: c.primary }]}
                onPress={() => setKind(k)}
              >
                <Text style={[ms.kindText, { color: kind === k ? c.primary : c.mutedForeground }]}>
                  {k === 'rts' ? 'Return to station' : 'Missing from tote'}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {kind === 'rts' && (
            <>
              <ScrollView style={{ maxHeight: 220 }}>
                {RTS_TYPES.map(t => (
                  <TouchableOpacity key={t.value} style={ms.reasonRow} onPress={() => setRtsType(t.value)}>
                    <View style={[ms.radio, { borderColor: rtsType === t.value ? c.primary : c.border }]}>
                      {rtsType === t.value && <View style={[ms.radioDot, { backgroundColor: c.primary }]} />}
                    </View>
                    <Text style={[ms.reasonText, { color: c.foreground }]}>{t.label}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <TextInput
                style={[ms.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
                value={explanation}
                onChangeText={setExpl}
                placeholder="What happened? (required)"
                placeholderTextColor={c.mutedForeground}
                multiline
              />
            </>
          )}
          {kind === 'missing' && (
            <Text style={[ms.missingHint, { color: c.mutedForeground }]}>
              Couldn't find this package in your tote. Dispatch gets a report to resolve —
              it won't count against your handoff.
            </Text>
          )}

          <View style={ms.btnRow}>
            <TouchableOpacity style={[ms.cancelBtn, { borderColor: c.border }]} onPress={onClose} disabled={submitting}>
              <Text style={{ color: c.mutedForeground, fontWeight: '600', fontSize: 13 }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[ms.submitBtn, { backgroundColor: kind === 'missing' ? c.warning : c.danger }]} onPress={submit} disabled={submitting}>
              {submitting
                ? <ActivityIndicator color="#fff" size="small" />
                : <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>
                    {kind === 'missing' ? 'Report Missing' : 'Flag RTS'}
                  </Text>}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────

const cs = StyleSheet.create({
  card:        { borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.sm },
  header:      { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  nextLabel:   { fontSize: fontSize.xs, fontWeight: fontWeight.bold, letterSpacing: 0.8, marginBottom: 2 },
  address:     { fontSize: fontSize.base, fontWeight: fontWeight.bold },
  meta:        { fontSize: fontSize.xs, marginTop: 2 },
  signalRow:   { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: spacing.xs },
  signalChip:  { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  signalText:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  noteBox:     { borderRadius: radius.md, padding: spacing.sm, marginTop: spacing.sm },
  noteText:    { fontSize: fontSize.xs, lineHeight: 17 },
  bagWrap:     { marginTop: spacing.sm },
  bagRow:      { marginBottom: spacing.xs },
  bagLabel:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, marginBottom: 4 },
  tbaWrap:     { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tbaChip:     { paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.md, borderWidth: 1 },
  tbaText:     { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
  tbaHint:     { fontSize: 10, marginTop: 4, fontStyle: 'italic' },
  completeBtn: { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginTop: spacing.sm },
  completeBtnText: { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  startBtn: { borderRadius: radius.md, borderWidth: 1.5, paddingVertical: spacing.sm + 2, alignItems: 'center', marginTop: spacing.sm },
  startBtnText: { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  bpBtn:       { alignItems: 'center', paddingVertical: spacing.xs + 2, marginTop: 2 },
  bpBtnText:   { fontSize: fontSize.xs, fontWeight: fontWeight.medium },
});

const ms = StyleSheet.create({
  backdrop:   { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  sheet:      { borderTopLeftRadius: radius.lg * 1.5, borderTopRightRadius: radius.lg * 1.5, padding: spacing.lg, paddingBottom: spacing.xl },
  title:      { fontSize: fontSize.md, fontWeight: fontWeight.bold, marginBottom: spacing.md },
  kindRow:    { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md },
  kindBtn:    { flex: 1, borderWidth: 1.5, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center' },
  kindText:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  reasonRow:  { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs + 2 },
  radio:      { width: 18, height: 18, borderRadius: 9, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  radioDot:   { width: 8, height: 8, borderRadius: 4 },
  reasonText: { fontSize: fontSize.sm },
  input:      { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, minHeight: 64, fontSize: fontSize.sm, marginTop: spacing.sm, textAlignVertical: 'top' },
  missingHint:{ fontSize: fontSize.sm, lineHeight: 20, marginBottom: spacing.sm },
  btnRow:     { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  cancelBtn:  { flex: 1, borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  submitBtn:  { flex: 2, borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
});

const styles = (c: ThemeColors) => StyleSheet.create({
  center:     { alignItems: 'center', marginTop: 64, gap: spacing.sm, paddingHorizontal: spacing.lg },
  emptyTitle: { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground },
  emptySub:   { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center' },

  heroCard:   { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.md },
  heroRow:    { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, marginBottom: spacing.sm },
  heroLabel:  { fontSize: fontSize.xs, color: c.mutedForeground, letterSpacing: 0.8, fontWeight: fontWeight.semibold },
  heroTitle:  { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground, marginTop: 2 },
  heroSub:    { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  effortChip: { paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.full },
  effortChipText: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  primaryBtn: { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  primaryBtnText: { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  doneBanner: { borderRadius: radius.md, padding: spacing.sm, alignItems: 'center' },
  doneBannerText: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textAlign: 'center' },
  helpBtn:    { borderWidth: 1.5, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center', marginTop: spacing.sm },
  helpBtnText:{ color: c.danger, fontSize: fontSize.sm, fontWeight: fontWeight.bold },

  sectionLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, letterSpacing: 0.8, marginBottom: spacing.xs, marginTop: spacing.xs },
});
