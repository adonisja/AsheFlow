/**
 * FieldOpsScreen — Driver shift lifecycle, gated step-by-step.
 *
 * OFFSITE (pre-shift)
 *   1. Check-in
 *   2. View dock/gate assignment
 *   3. Pre-trip inspection
 *   4. Log start odometer
 *
 * STATION (loading)
 *   5. Record station arrival (loading) + staging check
 *   6. View & acknowledge package manifest
 *   7. Record departure
 *
 * ROUTE / AP
 *   8. Post initial anchor point + ETA
 *   9. Confirm arrival at AP
 *  10. Check-in 1 (~11:15am): crew compliance + NCNS
 *  11. Walker ratings — unlocked after check-in 1, present walkers only,
 *      drafts persisted in AsyncStorage, submitted with end odometer
 *  12. Check-in 2 (~2pm): routes remaining + help request
 *  13. Check-in 3 (~4pm): routes remaining update
 *  14. Departure request (RTS report) — dispatch must approve
 *
 * STATION (return)
 *  15. Record station arrival (return)
 *  16. Station handoff (totes + RTS count)
 *
 * OFFSITE (end-of-day)
 *  17. Log end odometer + flush walker rating drafts
 *  18. EOD inspection
 *  19. Sign out
 *
 * Completed sections collapse to a summary chip. The active step is
 * expanded and highlighted. Locked future steps are hidden entirely.
 */

import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  ActivityIndicator, RefreshControl,
  TextInput, Alert, Switch, Modal, FlatList, Animated,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { useTabSwitch } from '@navigation/index';
import apiClient from '@api/client';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── helpers ───────────────────────────────────────────────────────────────────
function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function fmtTime(iso?: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const KM = 1.60934, LG = 3.78541;
const toDisp  = (mi: number,  u: Unit) => u === 'metric' ? +(mi * KM).toFixed(1) : mi;
const toMi    = (v: number,   u: Unit) => u === 'metric' ? +(v  / KM).toFixed(2) : v;
const fDisp   = (gal: number, u: Unit) => u === 'metric' ? +(gal * LG).toFixed(2) : gal;
const fToGal  = (v: number,   u: Unit) => u === 'metric' ? +(v  / LG).toFixed(2) : v;
type Unit = 'imperial' | 'metric';

const ITEM_LABELS: Record<string, string> = {
  tires: 'Tires', lights: 'Lights', mirrors: 'Mirrors', brakes: 'Brakes',
  fluids: 'Fluids', horn: 'Horn', wipers: 'Wipers', seatbelts: 'Seatbelts',
  cargo_security: 'Cargo Security', fuel_level: 'Fuel Level',
};
const STAGING_LABELS: Record<string, string> = {
  totes: 'Totes', ov_packages: 'OV Packages',
  phones_rabbits: 'Phones (Rabbits)', chargers: 'Chargers',
};
const STAGING_ITEMS = Object.keys(STAGING_LABELS);
const RTS_REASONS = [
  'Business Closed', 'No Access', 'No Safe Location', 'Customer Request',
  'Wrong Address', 'Damaged Package', 'Other',
];

// ── Full shift state (loaded once, refreshed on actions) ──────────────────────
type CrewMember  = { id: string; name: string; role: string };
type WalkerDraft = { stars: number; comment: string };

type ShiftState = {
  // dispatch confirmation (gate before check-in)
  confirmationStatus: 'pending' | 'confirmed' | 'declined' | null;
  dispatchDate: string | null;
  dispatchMessage: string | null;
  // offsite pre-shift
  checkedIn: boolean; checkedInAt: string | null;
  dockZone: string | null;
  preTripDone: boolean; preTripData: InspData | null;
  fuelLog: FuelLog | null;
  // station loading
  stationLoadArrived: boolean; stationLoadAt: string | null;
  wasStaged: boolean | null; missingItems: string[];
  truckId: string | null;
  taId: string | null;
  manifest: Manifest | null;
  roster: TruckRoster | null; rosterAvailable: boolean;
  departed: boolean; departedAt: string | null;
  // route / AP
  activeAP: AP | null;
  checkIn1: CheckInRecord | null;
  checkIn2: CheckInRecord | null;
  checkIn3: CheckInRecord | null;
  rtsReport: RTSReport | null;
  rtsSummary: RTSSummary | null;
  crew: CrewMember[];
  walkerRatingsSubmitted: Record<string, boolean>; // walkerId → true once posted
  // station return
  stationReturnArrived: boolean; stationReturnAt: string | null;
  stationHandoff: boolean;
  // offsite eod
  eodDone: boolean; eodData: InspData | null;
  returned: boolean; returnedAt: string | null;
};

type InspData  = { has_failures: boolean; items: Record<string, boolean>; notes?: string };
type FuelLog   = { id: string; odometer_start: number; odometer_end: number | null; fuel_added: number | null; notes: string | null };
type Manifest  = { id: string; tote_count: number; ov_count: number; notes: string | null; acknowledged_at: string | null };
type AP        = { id: string; location: string; eta: string | null; status: string; sequence: number };
type CheckInRecord = { check_in_number: number; routes_remaining: number; help_requested: boolean; working_crew_count: number; ncns_count: number; submitted_at: string };
type RTSReport = { id: string; status: string; crew_confirmed: number; total_rts: number; rts_packages: { reason: string; count: number }[]; dispatch_notes: string | null };
// ADR-181 dock flow (tote check-off + driver load confirmation)
type RosterTote  = {
  bag_id: string; package_count: number; ov_count: number;
  checked: boolean; checked_by_name: string | null;
  dock_tags: string[]; pull_tbas: string[]; rider_count: number;
};
type TruckRoster = {
  truck_id: string; zone_label: string; totes: RosterTote[];
  tote_count: number; checked_count: number;
  load_confirmed: boolean; confirmed_at: string | null; short_count: number;
};
// ADR-193 D4 — whole-truck RTS rollup (handoff confirms + report prefill)
type RTSSummaryRoute = {
  route_id: string; route_number: number; walker_name: string | null; route_status: string;
  handoff_exists: boolean; driver_confirmed_at: string | null; discrepancy_flagged: boolean;
  rts_count: number; missing_count: number;
};
type RTSSummary = {
  routes: RTSSummaryRoute[]; reason_totals: Record<string, number>;
  total_rts: number; total_missing: number; unconfirmed_handoffs: number;
};

const RTS_TYPE_LABELS: Record<string, string> = {
  no_access: 'No Access', business_closed: 'Business Closed',
  package_damaged: 'Damaged Package', inclement_weather: 'Inclement Weather',
  customer_requested_future_delivery: 'Customer Request',
  customer_cancelled_order: 'Customer Cancelled',
};

const EMPTY_SHIFT: ShiftState = {
  confirmationStatus: null, dispatchDate: null, dispatchMessage: null,
  checkedIn: false, checkedInAt: null,
  dockZone: null,
  preTripDone: false, preTripData: null,
  fuelLog: null,
  stationLoadArrived: false, stationLoadAt: null,
  wasStaged: null, missingItems: [],
  truckId: null,
  taId: null,
  manifest: null,
  roster: null, rosterAvailable: false,
  departed: false, departedAt: null,
  activeAP: null,
  checkIn1: null, checkIn2: null, checkIn3: null,
  rtsReport: null,
  rtsSummary: null,
  crew: [],
  walkerRatingsSubmitted: {},
  stationReturnArrived: false, stationReturnAt: null,
  stationHandoff: false,
  eodDone: false, eodData: null,
  returned: false, returnedAt: null,
};

// ── Shared UI primitives ──────────────────────────────────────────────────────
function Btn({ label, onPress, disabled, loading: ld, variant = 'primary', c }: {
  label: string; onPress: () => void; disabled?: boolean;
  loading?: boolean; variant?: 'primary' | 'ghost'; c: ThemeColors;
}) {
  const bg = variant === 'ghost' ? 'transparent' : c.primary;
  const border = variant === 'ghost' ? c.border : c.primary;
  return (
    <TouchableOpacity
      style={{ backgroundColor: bg, borderWidth: 1, borderColor: border, borderRadius: radius.md,
        paddingVertical: spacing.sm + 2, alignItems: 'center', opacity: disabled || ld ? 0.4 : 1 }}
      onPress={onPress} disabled={disabled || ld} activeOpacity={0.8}
    >
      {ld
        ? <ActivityIndicator color={variant === 'ghost' ? c.primary : '#fff'} />
        : <Text style={{ color: variant === 'ghost' ? c.primary : '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold }}>{label}</Text>
      }
    </TouchableOpacity>
  );
}

function DonePill({ label, c }: { label: string; c: ThemeColors }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: c.success + '18',
      borderRadius: radius.full, paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
      borderWidth: 1, borderColor: c.success + '40', alignSelf: 'flex-start' }}>
      <Text style={{ color: c.success, fontSize: fontSize.xs, fontWeight: fontWeight.semibold }}>✓ {label}</Text>
    </View>
  );
}

function SectionHeader({ num, title, subtitle, done, doneLabel, c }: {
  num: string; title: string; subtitle?: string;
  done?: boolean; doneLabel?: string; c: ThemeColors;
}) {
  return (
    <View style={{ marginBottom: done ? spacing.xs : spacing.sm }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <View style={{ width: 24, height: 24, borderRadius: 12, backgroundColor: done ? c.success : c.primary,
          alignItems: 'center', justifyContent: 'center' }}>
          <Text style={{ color: '#fff', fontSize: 11, fontWeight: fontWeight.bold }}>{done ? '✓' : num}</Text>
        </View>
        <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, flex: 1 }}>{title}</Text>
      </View>
      {subtitle && !done && (
        <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 4, marginLeft: 32 }}>{subtitle}</Text>
      )}
      {done && doneLabel && (
        <View style={{ marginLeft: 32, marginTop: 4 }}>
          <DonePill label={doneLabel} c={c} />
        </View>
      )}
    </View>
  );
}

function Card({ children, c }: { children: React.ReactNode; c: ThemeColors }) {
  return (
    <View style={{ backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1,
      borderColor: c.border, padding: spacing.md, marginBottom: spacing.md }}>
      {children}
    </View>
  );
}

function LocationDivider({ label, c }: { label: string; c: ThemeColors }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: spacing.md, marginTop: spacing.xs }}>
      <View style={{ flex: 1, height: 1, backgroundColor: c.border }} />
      <View style={{ backgroundColor: c.surfaceMuted, borderRadius: radius.full, paddingHorizontal: spacing.md,
        paddingVertical: 3, marginHorizontal: spacing.sm, borderWidth: 1, borderColor: c.border }}>
        <Text style={{ fontSize: 10, color: c.mutedForeground, fontWeight: fontWeight.semibold,
          textTransform: 'uppercase', letterSpacing: 0.8 }}>{label}</Text>
      </View>
      <View style={{ flex: 1, height: 1, backgroundColor: c.border }} />
    </View>
  );
}

// Collapsed done-step row — replaces the full Card when a step is complete
function CompletedRow({ num, title, summary, c }: {
  num: string; title: string; summary: string; c: ThemeColors;
}) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      paddingVertical: spacing.xs, paddingHorizontal: spacing.sm, marginBottom: spacing.xs }}>
      <View style={{ width: 20, height: 20, borderRadius: 10, backgroundColor: c.success,
        alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        <Text style={{ color: '#fff', fontSize: 10, fontWeight: fontWeight.bold }}>✓</Text>
      </View>
      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, flex: 1 }} numberOfLines={1}>
        <Text style={{ fontWeight: fontWeight.semibold, color: c.foreground }}>{title}</Text>
        {summary ? `  ·  ${summary}` : ''}
      </Text>
    </View>
  );
}

// Pure-JS time picker modal — no native dependency required
function TimePickerModal({ visible, initial, onConfirm, onCancel, c }: {
  visible: boolean; initial: Date; onConfirm: (h: number, m: number) => void;
  onCancel: () => void; c: ThemeColors;
}) {
  const [hour,   setHour]   = useState(initial.getHours());
  const [minute, setMinute] = useState(Math.floor(initial.getMinutes() / 5) * 5);

  const hours   = Array.from({ length: 24 }, (_, i) => i);
  const minutes = Array.from({ length: 12 }, (_, i) => i * 5);

  const colStyle: object = { flex: 1, height: 200 };
  const itemStyle = (selected: boolean): object => ({
    paddingVertical: spacing.sm, alignItems: 'center' as const,
    backgroundColor: selected ? c.primary + '20' : 'transparent',
    borderRadius: radius.sm,
  });
  const itemText = (selected: boolean): object => ({
    fontSize: fontSize.base, fontWeight: selected ? fontWeight.bold : fontWeight.regular,
    color: selected ? c.primary : c.foreground,
  });

  return (
    <Modal transparent visible={visible} animationType="fade" onRequestClose={onCancel}>
      <View style={{ flex: 1, backgroundColor: '#00000066', justifyContent: 'center', alignItems: 'center' }}>
        <View style={{ backgroundColor: c.card, borderRadius: radius.lg, padding: spacing.md,
          width: 260, borderWidth: 1, borderColor: c.border }}>
          <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground,
            textAlign: 'center', marginBottom: spacing.md }}>Pick ETA</Text>
          <View style={{ flexDirection: 'row', gap: spacing.md }}>
            <View style={colStyle}>
              <Text style={{ fontSize: 10, color: c.mutedForeground, textAlign: 'center',
                marginBottom: spacing.xs, textTransform: 'uppercase', letterSpacing: 0.6 }}>Hour</Text>
              <FlatList
                data={hours}
                keyExtractor={String}
                showsVerticalScrollIndicator={false}
                initialScrollIndex={hour}
                getItemLayout={(_, i) => ({ length: 40, offset: 40 * i, index: i })}
                renderItem={({ item }) => (
                  <TouchableOpacity style={itemStyle(item === hour)} onPress={() => setHour(item)}>
                    <Text style={itemText(item === hour)}>
                      {item === 0 ? '12 AM' : item < 12 ? `${item} AM` : item === 12 ? '12 PM' : `${item - 12} PM`}
                    </Text>
                  </TouchableOpacity>
                )}
              />
            </View>
            <View style={colStyle}>
              <Text style={{ fontSize: 10, color: c.mutedForeground, textAlign: 'center',
                marginBottom: spacing.xs, textTransform: 'uppercase', letterSpacing: 0.6 }}>Min</Text>
              <FlatList
                data={minutes}
                keyExtractor={String}
                showsVerticalScrollIndicator={false}
                initialScrollIndex={minutes.indexOf(minute) >= 0 ? minutes.indexOf(minute) : 0}
                getItemLayout={(_, i) => ({ length: 40, offset: 40 * i, index: i })}
                renderItem={({ item }) => (
                  <TouchableOpacity style={itemStyle(item === minute)} onPress={() => setMinute(item)}>
                    <Text style={itemText(item === minute)}>{String(item).padStart(2, '0')}</Text>
                  </TouchableOpacity>
                )}
              />
            </View>
          </View>
          <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md }}>
            <TouchableOpacity onPress={onCancel} style={{ flex: 1, padding: spacing.sm, borderRadius: radius.md,
              borderWidth: 1, borderColor: c.border, alignItems: 'center' }}>
              <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => onConfirm(hour, minute)} style={{ flex: 1, padding: spacing.sm,
              borderRadius: radius.md, backgroundColor: c.primary, alignItems: 'center' }}>
              <Text style={{ fontSize: fontSize.sm, color: '#fff', fontWeight: fontWeight.semibold }}>Set</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// ── Inspection form (shared by pre-trip and EOD) ──────────────────────────────
function InspectionForm({ employeeId, inspType, onDone, c }: {
  employeeId: string; inspType: 'pre_trip' | 'eod'; onDone: () => void; c: ThemeColors;
}) {
  const [items,   setItems]   = useState<string[]>([]);
  const [results, setResults] = useState<Record<string, boolean | null>>({});
  const [notes,   setNotes]   = useState('');
  const [saving,  setSaving]  = useState(false);
  const [loaded,  setLoaded]  = useState(false);

  useEffect(() => {
    if (loaded) return;
    apiClient.get('/field-ops/inspection/items').then(r => {
      const canon: string[] = r.data.items ?? [];
      setItems(canon);
      setResults(Object.fromEntries(canon.map(k => [k, null])));
    }).catch(() => {});
    setLoaded(true);
  }, [loaded]);

  const toggle = (item: string, pass: boolean) =>
    setResults(p => ({ ...p, [item]: p[item] === pass ? null : pass }));
  const allDone = items.length > 0 && items.every(k => results[k] !== null);

  const submit = async () => {
    if (!allDone) { Alert.alert('Incomplete', 'Mark every item Pass or Fail.'); return; }
    setSaving(true);
    try {
      await apiClient.post('/field-ops/inspection', {
        driver_id: employeeId, date: localToday(),
        inspection_type: inspType,
        items: results as Record<string, boolean>,
        notes: notes.trim() || null,
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not submit inspection. Try again.')); }
    finally { setSaving(false); }
  };

  if (items.length === 0) return <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.md }} />;

  return (
    <>
      {items.map(item => {
        const val = results[item];
        return (
          <View key={item} style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
            paddingVertical: spacing.xs + 1, borderBottomWidth: 1, borderBottomColor: c.border }}>
            <Text style={{ fontSize: fontSize.sm, color: c.foreground, fontWeight: fontWeight.medium, flex: 1 }}>
              {ITEM_LABELS[item] ?? item}
            </Text>
            <View style={{ flexDirection: 'row', gap: spacing.xs }}>
              {([true, false] as const).map(pass => (
                <TouchableOpacity key={String(pass)} onPress={() => toggle(item, pass)}
                  style={{ paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.sm, borderWidth: 1,
                    backgroundColor: val === pass ? (pass ? c.success : c.danger) : 'transparent',
                    borderColor: val === pass ? (pass ? c.success : c.danger) : c.border }}>
                  <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold,
                    color: val === pass ? '#fff' : c.mutedForeground }}>{pass ? 'Pass' : 'Fail'}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        );
      })}
      <TextInput
        style={{ marginTop: spacing.sm, borderWidth: 1, borderColor: c.border, borderRadius: radius.md,
          padding: spacing.sm, fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background,
          minHeight: 60, textAlignVertical: 'top' }}
        value={notes} onChangeText={setNotes}
        placeholder="Notes (optional)…" placeholderTextColor={c.mutedForeground} multiline />
      <View style={{ marginTop: spacing.sm }}>
        <Btn label={`Submit ${inspType === 'pre_trip' ? 'Pre-Trip' : 'EOD'} Inspection`}
          onPress={submit} disabled={!allDone} loading={saving} c={c} />
      </View>
    </>
  );
}

function InspDoneView({ data, c }: { data: InspData; c: ThemeColors }) {
  const bg = data.has_failures ? c.danger + '12' : c.success + '12';
  const border = data.has_failures ? c.danger + '40' : c.success + '40';
  const col = data.has_failures ? c.danger : c.success;
  return (
    <View style={{ backgroundColor: bg, borderRadius: radius.md, borderWidth: 1, borderColor: border, padding: spacing.md }}>
      <Text style={{ color: col, fontWeight: fontWeight.semibold, fontSize: fontSize.sm, marginBottom: spacing.xs }}>
        {data.has_failures ? 'Failures noted — flagged to management.' : 'All items passed.'}
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs }}>
        {Object.entries(data.items).map(([k, pass]) => (
          <View key={k} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, width: '47%' }}>
            <Text style={{ color: pass ? c.success : c.danger, fontSize: fontSize.xs }}>{pass ? '✓' : '✗'}</Text>
            <Text style={{ fontSize: fontSize.xs, color: c.foreground }}>{ITEM_LABELS[k] ?? k}</Text>
          </View>
        ))}
      </View>
      {data.notes ? <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, fontStyle: 'italic', marginTop: spacing.xs }}>Notes: {data.notes}</Text> : null}
    </View>
  );
}

// ── Walker rating drafts, persisted in AsyncStorage ───────────────────────────
const DRAFT_KEY = (empId: string) => `asheflow_walker_drafts_${empId}_${localToday()}`;

async function loadDrafts(empId: string): Promise<Record<string, WalkerDraft>> {
  try {
    const raw = await AsyncStorage.getItem(DRAFT_KEY(empId));
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
}
async function saveDrafts(empId: string, drafts: Record<string, WalkerDraft>) {
  try { await AsyncStorage.setItem(DRAFT_KEY(empId), JSON.stringify(drafts)); } catch {}
}

// ── Check-in timing context ───────────────────────────────────────────────────
const CI_TIMES = ['~11:15 AM', '~2:00 PM', '~4:00 PM', '~5:30 PM'];

// ── Root screen ───────────────────────────────────────────────────────────────
export default function FieldOpsScreen() {
  const c = useColors();
  const { user, hasRole } = useAuth();
  const switchTab = useTabSwitch();
  const isDriver = hasRole('driver');
  const isWalker = hasRole('walker');

  const [employeeId, setEmployeeId] = useState('');
  const [loadingId,  setLoadingId]  = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [shift,      setShift]      = useState<ShiftState>(EMPTY_SHIFT);

  // Walker rating drafts — loaded from AsyncStorage
  const [walkerDrafts, setWalkerDrafts] = useState<Record<string, WalkerDraft>>({});
  const draftsRef = useRef(walkerDrafts);
  draftsRef.current = walkerDrafts;
  const loadAbortRef = useRef<AbortController | null>(null);

  const loadShift = useCallback(async (empId: string) => {
    loadAbortRef.current?.abort();
    const ctrl = new AbortController();
    loadAbortRef.current = ctrl;
    const sig = { signal: ctrl.signal };

    const today = localToday();
    const [ciRes, dockRes, inspRes, fuelRes, crewRes, arrRes, depRes, apRes,
           ci1Res, ci2Res, ci3Res, rtsRes, handoffRes, notifRes, confRes,
           rosterRes, dispRes] = await Promise.allSettled([
      apiClient.get(`/field-ops/check-in/${empId}`, sig),
      apiClient.get(`/field-ops/dock-assignment/${empId}`, sig),
      apiClient.get(`/field-ops/inspection/${empId}`, sig),
      apiClient.get(`/field-ops/fuel-log/${empId}`, sig),
      apiClient.get(`/field-ops/crew/${empId}`, sig),
      apiClient.get(`/field-ops/station-arrival/${empId}`, { params: { target_date: today }, ...sig }),
      apiClient.get(`/field-ops/departure/${empId}`, sig),
      apiClient.get('/anchor-points/driver/today', sig),
      apiClient.get(`/shift-ops/check-in/${empId}`, { params: { target_date: today }, ...sig }),
      apiClient.get(`/shift-ops/check-in/${empId}`, { params: { target_date: today }, ...sig }),
      apiClient.get(`/shift-ops/check-in/${empId}`, { params: { target_date: today }, ...sig }),
      apiClient.get(`/shift-ops/rts-report/${empId}`, sig),
      apiClient.get(`/shift-ops/station-handoff/${empId}`, sig),
      // Dispatch assignment notification for today (to get message text)
      apiClient.get(`/notifications/${empId}?limit=10`, sig),
      // Confirmation status for today
      apiClient.get(`/dispatch/${today}/my-confirmation`, sig),
      // ADR-181 dock flow — server scopes drivers to their own truck's roster
      apiClient.get(`/sort/${today}/rosters`, sig),
      // TruckAssignment id (for the RTS summary + handoff confirms)
      apiClient.get(`/dispatch/${today}`, sig),
    ]);
    if (ctrl.signal.aborted) return;

    const ci      = ciRes.status === 'fulfilled' ? ciRes.value.data.find((r: any) => r.date === today) : null;
    const dock    = dockRes.status === 'fulfilled' ? dockRes.value.data : null;
    const inspAll = inspRes.status === 'fulfilled' ? inspRes.value.data : [];
    const preTrip = inspAll.find((r: any) => r.date === today && r.inspection_type === 'pre_trip') ?? null;
    const eodInsp = inspAll.find((r: any) => r.date === today && r.inspection_type === 'eod') ?? null;
    const fuel    = fuelRes.status === 'fulfilled' ? fuelRes.value.data.find((r: any) => r.date === today) ?? null : null;
    const crew: CrewMember[] = crewRes.status === 'fulfilled' ? (crewRes.value.data.crew ?? []) : [];

    const arrivals: any[] = arrRes.status === 'fulfilled' ? arrRes.value.data : [];
    const loadArr  = arrivals.find((r: any) => r.arrival_type === 'loading') ?? null;
    const retArr   = arrivals.find((r: any) => r.arrival_type === 'return') ?? null;
    const dep      = depRes.status === 'fulfilled' ? depRes.value.data.find((r: any) => r.date === today) ?? null : null;

    // Anchor points — find most recent non-relocated for this truck today
    const aps: any[] = apRes.status === 'fulfilled' ? (apRes.value.data ?? []) : [];
    const activeAP = aps.find((a: any) => a.status !== 'relocated') ?? null;

    // Check-ins — one API call returns all, filter by number
    const checkIns: any[] = ci1Res.status === 'fulfilled' ? ci1Res.value.data : [];
    const ci1 = checkIns.find((r: any) => r.check_in_number === 1) ?? null;
    const ci2 = checkIns.find((r: any) => r.check_in_number === 2) ?? null;
    const ci3 = checkIns.find((r: any) => r.check_in_number === 3) ?? null;

    const rts     = rtsRes.status === 'fulfilled' ? rtsRes.value.data : null;
    const handoff = handoffRes.status === 'fulfilled' ? handoffRes.value.data : null;

    // Pull the assignment message from the notification list first — it anchors today's dispatch
    const notifs: any[] = notifRes.status === 'fulfilled' ? (notifRes.value.data ?? []) : [];
    const dispatchNotif = notifs.find((n: any) => n.type === 'dispatch_assignment' && n.dispatch_date === today);
    const dispatchMessage: string | null = dispatchNotif?.message ?? null;

    // Dispatch confirmation — only valid when the confirmed date matches today
    const confData = confRes.status === 'fulfilled' ? confRes.value.data : null;
    const confIsToday = confData?.date === today;
    const confirmationStatus: ShiftState['confirmationStatus'] = confIsToday ? (confData?.status ?? null) : null;
    // Show the card if today's dispatch notification exists OR if there's a same-day confirmation record
    const dispatchDate: string | null = (dispatchNotif || confIsToday) ? today : null;

    // Truck ID from crew endpoint
    const truckId: string | null = crewRes.status === 'fulfilled' ? (crewRes.value.data.truck_id ?? null) : null;

    // Dock roster — driver-scoped server-side, so ours is the only entry.
    const rosterData = rosterRes.status === 'fulfilled' ? rosterRes.value.data : null;
    const roster: TruckRoster | null = rosterData?.rosters?.[0] ?? null;
    const rosterAvailable: boolean = !!rosterData?.roster_available && !!roster;

    // TruckAssignment id for today's truck (RTS summary + handoff confirms).
    let taId: string | null = null;
    if (truckId && dispRes.status === 'fulfilled') {
      const tas: { truck_id: string; assignment_id?: string }[] = dispRes.value.data?.truck_assignments ?? [];
      taId = tas.find(t => t.truck_id === truckId)?.assignment_id ?? null;
    }

    // Manifest — needs truck_id
    let manifest: Manifest | null = null;
    if (truckId) {
      const mRes = await apiClient.get(`/field-ops/manifest/${truckId}`).catch(() => null);
      manifest = mRes?.data ?? null;
    }

    // Whole-truck RTS rollup (ADR-193 D4) — only meaningful once on the road.
    let rtsSummary: RTSSummary | null = null;
    if (taId) {
      const sRes = await apiClient.get(`/rts/summary/${taId}`).catch(() => null);
      rtsSummary = sRes?.data ?? null;
    }

    // Submitted walker ratings
    let walkerRatingsSubmitted: Record<string, boolean> = {};
    if (dep) {
      const rRes = await apiClient.get(`/field-ops/rating/driver/${empId}`, { params: { target_date: today } }).catch(() => null);
      if (rRes) {
        for (const r of rRes.data) walkerRatingsSubmitted[r.walker_id] = true;
      }
    }

    setShift({
      confirmationStatus, dispatchDate, dispatchMessage,
      checkedIn: !!ci, checkedInAt: ci?.checked_in_at ?? null,
      dockZone: dock?.dock_zone ?? null,
      preTripDone: !!preTrip,
      preTripData: preTrip ? { has_failures: preTrip.has_failures, items: preTrip.items, notes: preTrip.notes } : null,
      fuelLog: fuel,
      stationLoadArrived: !!loadArr, stationLoadAt: loadArr?.arrived_at ?? null,
      wasStaged: loadArr?.was_staged ?? null, missingItems: loadArr?.missing_items ?? [],
      truckId,
      taId,
      manifest,
      roster, rosterAvailable,
      departed: !!dep, departedAt: dep?.departed_at ?? null,
      activeAP: activeAP ? { id: activeAP.id, location: activeAP.location, eta: activeAP.eta, status: activeAP.status, sequence: activeAP.sequence } : null,
      checkIn1: ci1, checkIn2: ci2, checkIn3: ci3,
      rtsReport: rts,
      rtsSummary,
      crew,
      walkerRatingsSubmitted,
      stationReturnArrived: !!retArr, stationReturnAt: retArr?.arrived_at ?? null,
      stationHandoff: !!handoff,
      eodDone: !!eodInsp,
      eodData: eodInsp ? { has_failures: eodInsp.has_failures, items: eodInsp.items, notes: eodInsp.notes } : null,
      returned: !!(dep?.returned_at), returnedAt: dep?.returned_at ?? null,
    });
  }, []);

  useEffect(() => {
    apiClient.get('/employees/me').then(async r => {
      const id = r.data.id;
      setEmployeeId(id);
      await Promise.all([loadShift(id), loadDrafts(id).then(setWalkerDrafts)]);
    }).catch(() => {}).finally(() => setLoadingId(false));
    return () => { loadAbortRef.current?.abort(); };
  }, [user, loadShift]);

  const reload = useCallback(() => { if (employeeId) loadShift(employeeId); }, [employeeId, loadShift]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await reload();
    setRefreshing(false);
  }, [reload]);

  const updateDraft = useCallback((walkerId: string, patch: Partial<WalkerDraft>) => {
    setWalkerDrafts(prev => {
      const existing = prev[walkerId] ?? { stars: 0, comment: '' };
      const next = { ...prev, [walkerId]: { ...existing, ...patch } };
      saveDrafts(employeeId, next);
      return next;
    });
  }, [employeeId]);

  const s = styles(c);

  // Wizard hooks — declared unconditionally, BEFORE any early return, per the
  // Rules of Hooks. cursor starts at 0; the effect below syncs it to the live step.
  const [cursor, setCursor] = useState(0);
  const reviewingRef = useRef(false);
  const fade = useRef(new Animated.Value(1)).current;

  // ── Derived gating flags ─────────────────────────────────────────────────
  const {
    confirmationStatus,
    checkedIn, dockZone, preTripDone, fuelLog, stationLoadArrived, wasStaged,
    missingItems, manifest, roster, rosterAvailable, departed, activeAP,
    checkIn1, checkIn2, checkIn3,
    rtsReport, rtsSummary, crew, walkerRatingsSubmitted, stationReturnArrived,
    stationHandoff, eodDone, returned, truckId, taId,
  } = shift;

  const walkers      = crew.filter(m => m.role === 'walker');
  // NCNS walkers from check-in 1 — we don't have individual mapping so use submitted rating as proxy
  const presentWalkers = checkIn1
    ? walkers.filter(w => walkerRatingsSubmitted[w.id] !== undefined
        ? true // already rated means present
        : true) // before any ratings, show all; absent ones will be filtered after CI1 submitted
    : [];
  // After CI1: only walkers not explicitly no-shown
  // We determine absence from the ratings endpoint (present: false) — stored in walkerRatingsSubmitted
  // For simplicity: show all walkers who don't have a no-show rating submitted
  const ratableWalkers = checkIn1 ? walkers : [];

  const rtsApproved  = rtsReport?.status === 'rts_approved' || rtsReport?.status === 'approved';
  const rtsPending   = rtsReport?.status === 'pending';

  // Step progress for driver shift (20 total gated steps 0–19)
  const TOTAL_STEPS = 20;
  const completedSteps = isDriver ? [
    confirmationStatus === 'confirmed',
    !!checkedIn,
    !!dockZone,
    !!preTripDone,
    !!fuelLog?.odometer_start,
    !!stationLoadArrived,
    // Step 6: tote check-off + confirm-load when a roster exists (ADR-181),
    // legacy manifest acknowledge otherwise.
    rosterAvailable ? !!roster?.load_confirmed : !!manifest,
    !!departed,
    !!(activeAP && activeAP.status !== 'preliminary'),
    !!(activeAP && activeAP.status === 'arrived'),
    !!checkIn1,
    walkers.length === 0 || Object.keys(walkerRatingsSubmitted).length > 0,
    !!checkIn2,
    !!checkIn3,
    !!rtsReport,
    !!stationReturnArrived,
    !!stationHandoff,
    !!(fuelLog?.odometer_end != null),
    !!eodDone,
    !!returned,
  ].filter(Boolean).length : 0;

  // ── Wizard step model (one step per page, fade + dots) ──────────────────────
  // Each entry: reachable (is this step visible per the gates), done, section
  // label, and the node to render. Only reachable steps become pages; the same
  // gate booleans that drove the old checklist decide reachability, so the flow
  // logic is unchanged — only the presentation (paged vs scrolled).
  type WizStep = { key: string; section: string; reachable: boolean; done: boolean; node: React.ReactNode };
  const allSteps: WizStep[] = isDriver ? [
    { key: 'confirm', section: 'Offsite', reachable: true, done: confirmationStatus === 'confirmed',
      node: <StepDispatchConfirmation employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },
    { key: 'checkin', section: 'Offsite', reachable: confirmationStatus === 'confirmed', done: !!checkedIn,
      node: <StepCheckIn employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },
    { key: 'dock', section: 'Offsite', reachable: !!checkedIn, done: !!dockZone,
      node: <StepDockAssignment dockZone={dockZone} c={c} /> },
    { key: 'pretrip', section: 'Offsite', reachable: !!checkedIn, done: !!preTripDone,
      node: <StepInspection employeeId={employeeId} shift={shift} inspType="pre_trip" stepNum="3"
              title="Pre-Trip Inspection" subtitle="Inspect the truck before leaving the offsite." onDone={reload} c={c} /> },
    { key: 'odo_start', section: 'Offsite', reachable: !!preTripDone, done: !!fuelLog?.odometer_start,
      node: <StepStartOdometer employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },

    { key: 'station_arrive', section: 'Station — Loading', reachable: !!fuelLog, done: !!stationLoadArrived,
      node: <StepStationArrival employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },
    { key: 'load', section: 'Station — Loading', reachable: !!fuelLog && !!stationLoadArrived,
      done: rosterAvailable ? !!roster?.load_confirmed : !!manifest,
      node: rosterAvailable ? <StepLoadTruck roster={roster!} onDone={reload} c={c} />
                            : <StepManifest truckId={truckId} shift={shift} employeeId={employeeId} onDone={reload} c={c} /> },
    { key: 'depart', section: 'Station — Loading', reachable: !!fuelLog && !!stationLoadArrived, done: !!departed,
      node: <StepDeparture employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },

    { key: 'ap', section: 'Route', reachable: !!departed, done: !!activeAP,
      node: <StepAnchorPoint employeeId={employeeId} truckId={truckId} shift={shift} onDone={reload} c={c} /> },
    { key: 'ap_arrive', section: 'Route', reachable: !!departed && !!(activeAP && activeAP.status === 'preliminary'),
      done: !!(activeAP && activeAP.status === 'arrived'),
      node: activeAP ? <StepAPArrive ap={activeAP} onDone={reload} c={c} /> : null },
    { key: 'ci1', section: 'Route', reachable: !!departed && !!(activeAP && activeAP.status === 'arrived'), done: !!checkIn1,
      node: <StepCheckIn1 employeeId={employeeId} shift={shift} crew={crew} onDone={reload} c={c} /> },
    { key: 'ratings', section: 'Route', reachable: !!departed && !!checkIn1 && ratableWalkers.length > 0,
      done: walkers.length === 0 || Object.keys(walkerRatingsSubmitted).length > 0,
      node: <StepWalkerRatings walkers={ratableWalkers} drafts={walkerDrafts}
              submitted={walkerRatingsSubmitted} onUpdateDraft={updateDraft} c={c} /> },
    { key: 'ci2', section: 'Route', reachable: !!departed && !!checkIn1, done: !!checkIn2,
      node: <StepCheckInN employeeId={employeeId} shift={shift} num={2} time={CI_TIMES[1]}
              record={checkIn2} prevRecord={checkIn1} crew={crew} onDone={reload} c={c} /> },
    { key: 'ci3', section: 'Route', reachable: !!departed && !!checkIn2, done: !!checkIn3,
      node: <StepCheckInN employeeId={employeeId} shift={shift} num={3} time={CI_TIMES[2]}
              record={checkIn3} prevRecord={checkIn2} crew={crew} onDone={reload} c={c} /> },
    { key: 'handoffs', section: 'Route',
      reachable: !!departed && !!checkIn1 && !!rtsSummary && !!rtsSummary.routes.some(r => r.handoff_exists),
      // Informational (ADR-193 D4) — doesn't gate the RTS step. done=true when all
      // returned routes are driver-confirmed, so it never traps the live cursor.
      done: !rtsSummary || rtsSummary.routes.filter(r => r.handoff_exists).every(r => !!r.driver_confirmed_at),
      node: rtsSummary ? <StepWalkerHandoffs summary={rtsSummary} onDone={reload} c={c} /> : null },
    { key: 'rts', section: 'Route', reachable: !!departed && !!checkIn3, done: !!rtsReport,
      node: <StepRTSReport employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },

    { key: 'return_arrive', section: 'Station — Return', reachable: !!rtsApproved, done: !!stationReturnArrived,
      node: <StepStationReturn employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },
    { key: 'handoff', section: 'Station — Return', reachable: !!rtsApproved && !!stationReturnArrived, done: !!stationHandoff,
      node: <StepStationHandoff employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },

    { key: 'odo_end', section: 'Offsite — End of Day', reachable: !!stationHandoff, done: !!(fuelLog?.odometer_end != null),
      node: <StepEndOdometer employeeId={employeeId} shift={shift} walkers={ratableWalkers} drafts={walkerDrafts}
              submittedRatings={walkerRatingsSubmitted} onDone={reload} c={c} /> },
    { key: 'eod_insp', section: 'Offsite — End of Day', reachable: !!stationHandoff && fuelLog?.odometer_end != null, done: !!eodDone,
      node: <StepInspection employeeId={employeeId} shift={shift} inspType="eod" stepNum="18"
              title="End-of-Day Inspection" subtitle="Inspect the truck before parking. Note any new issues." onDone={reload} c={c} /> },
    { key: 'signout', section: 'Offsite — End of Day', reachable: !!stationHandoff && !!eodDone, done: !!returned,
      node: <StepSignOut employeeId={employeeId} shift={shift} onDone={reload} c={c} /> },
  ].filter(st => st.reachable) : [];

  // Live step = the furthest-incomplete reachable step (server-derived, as before).
  // cursor = which page the driver is viewing; clamped so they can review COMPLETED
  // steps (back) but never skip ahead of the live step.
  const liveIndex = (() => {
    const i = allSteps.findIndex(st => !st.done);
    return i === -1 ? Math.max(0, allSteps.length - 1) : i;
  })();

  // Follow the live step forward unless the driver is reviewing a past step.
  // (cursor / reviewingRef / fade are declared with the other hooks at the top of
  // the component — BEFORE the early returns — to satisfy the Rules of Hooks.)
  useEffect(() => {
    const clampedLive = Math.max(0, Math.min(liveIndex, allSteps.length - 1));
    setCursor(prev => {
      if (reviewingRef.current && prev < clampedLive) return Math.min(prev, allSteps.length - 1);
      return clampedLive;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveIndex, allSteps.length]);

  // Cross-dissolve on page change. Going to/at the live step clears review mode.
  const goToStep = (next: number) => {
    if (next === cursor || next < 0 || next > liveIndex) return;
    reviewingRef.current = next < liveIndex;
    Animated.timing(fade, { toValue: 0, duration: 120, useNativeDriver: true }).start(() => {
      setCursor(next);
      Animated.timing(fade, { toValue: 1, duration: 160, useNativeDriver: true }).start();
    });
  };

  // Early-return guards AFTER all hooks/derivations (Rules of Hooks: hooks must
  // run unconditionally every render).
  if (loadingId) {
    return (
      <SafeAreaView style={s.safe} edges={['top']}>
        <View style={s.center}><ActivityIndicator size="large" color={c.primary} /></View>
      </SafeAreaView>
    );
  }
  if (!employeeId) {
    return (
      <SafeAreaView style={s.safe} edges={['top']}>
        <View style={s.center}><Text style={{ color: c.mutedForeground }}>Could not load profile.</Text></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView style={s.scroll} contentContainerStyle={s.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />}>

        {/* ── Header ── */}
        <View style={s.screenHeader}>
          <TouchableOpacity onPress={() => switchTab('Home')} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }} style={s.backBtn}>
            <Text style={[s.backChevron, { color: c.primary }]}>‹</Text>
          </TouchableOpacity>
          <View style={s.screenHeaderCenter}>
            <Text style={s.pageTitle}>Field Ops</Text>
            <Text style={s.subtitle}>{localToday()}</Text>
          </View>
          {isDriver ? (
            <View style={[s.stepBadge, { backgroundColor: completedSteps === TOTAL_STEPS ? '#10B98118' : c.primary + '18', borderColor: completedSteps === TOTAL_STEPS ? '#10B981' : c.primary }]}>
              <Text style={[s.stepBadgeText, { color: completedSteps === TOTAL_STEPS ? '#10B981' : c.primary }]}>
                {completedSteps}/{TOTAL_STEPS}
              </Text>
            </View>
          ) : (
            <View style={s.backBtn} />
          )}
        </View>

        {isDriver && allSteps.length > 0 && (
          <>
            {/* Progress dots — green = completed, red = pending. Tappable to
                review a completed step (can't jump ahead of the live step). */}
            <View style={s.dotRow}>
              {allSteps.map((st, i) => {
                const filled = st.done;
                const isCurrent = i === cursor;
                const reviewable = i <= liveIndex;
                return (
                  <TouchableOpacity
                    key={st.key}
                    disabled={!reviewable}
                    onPress={() => goToStep(i)}
                    hitSlop={{ top: 8, bottom: 8, left: 3, right: 3 }}
                  >
                    <View style={[
                      s.dot,
                      { backgroundColor: filled ? '#10B981' : '#E8443A' },
                      isCurrent && s.dotCurrent,
                      !filled && !isCurrent && { opacity: 0.45 },
                    ]} />
                  </TouchableOpacity>
                );
              })}
            </View>

            {/* Section + back arrow + step count */}
            <View style={s.wizHeader}>
              {cursor > 0 ? (
                <TouchableOpacity onPress={() => goToStep(cursor - 1)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} style={s.wizBack}>
                  <Text style={[s.wizBackArrow, { color: c.primary }]}>←</Text>
                </TouchableOpacity>
              ) : <View style={s.wizBack} />}
              <View style={{ flex: 1, alignItems: 'center' }}>
                <Text style={[s.wizSection, { color: c.mutedForeground }]}>{allSteps[cursor]?.section?.toUpperCase()}</Text>
                <Text style={[s.wizCount, { color: c.foreground }]}>Step {cursor + 1} of {allSteps.length}</Text>
              </View>
              {cursor < liveIndex ? (
                <TouchableOpacity onPress={() => goToStep(liveIndex)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} style={s.wizBack}>
                  <Text style={[s.wizBackArrow, { color: c.primary }]}>→</Text>
                </TouchableOpacity>
              ) : <View style={s.wizBack} />}
            </View>

            {/* The current step, cross-dissolved on change */}
            <Animated.View style={{ opacity: fade }}>
              {allSteps[cursor]?.node}
            </Animated.View>
          </>
        )}

        {isWalker && (
          <WalkerPerformanceView employeeId={employeeId} c={c} />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step components
// ─────────────────────────────────────────────────────────────────────────────

function StepDispatchConfirmation({ employeeId, shift, onDone, c }: {
  employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors;
}) {
  const [acting, setActing] = useState<'confirming' | 'declining' | null>(null);
  const submitting = useRef(false);

  const respond = async (status: 'confirmed' | 'declined') => {
    if (!shift.dispatchDate || submitting.current) return;
    submitting.current = true;
    setActing(status === 'confirmed' ? 'confirming' : 'declining');
    try {
      await apiClient.post(`/dispatch/${shift.dispatchDate}/confirmations`, {
        employee_id: employeeId,
        status,
      });
      onDone();
    } catch (e: any) {
      Alert.alert('Error', errorText(e, 'Could not record response. Try again.'));
    } finally {
      setActing(null);
      submitting.current = false;
    }
  };

  const { confirmationStatus } = shift;

  if (!shift.dispatchDate) return null;

  if (confirmationStatus === 'confirmed') {
    return <CompletedRow num="0" title="Assignment Confirmed" summary="Check-in unlocked" c={c} />;
  }

  if (confirmationStatus === 'declined') {
    return (
      <View style={{ backgroundColor: c.danger + '0D', borderRadius: radius.lg, borderWidth: 1,
        borderColor: c.danger + '30', padding: spacing.md, marginBottom: spacing.md }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.xs }}>
          <Text style={{ fontSize: 18 }}>🚫</Text>
          <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.danger }}>
            Assignment Declined
          </Text>
        </View>
        <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground, lineHeight: 20 }}>
          You declined this assignment. Contact dispatch if this was a mistake.
        </Text>
      </View>
    );
  }

  // Extract truck name from message (bold text between **)
  const truckMatch = shift.dispatchMessage?.match(/\*\*(.+?)\*\*/);
  const truckName  = truckMatch ? truckMatch[1] : null;
  const cleanMsg   = shift.dispatchMessage?.replace(/\*\*(.*?)\*\*/g, '$1') ?? null;

  const dateLabel = new Date(shift.dispatchDate + 'T12:00:00').toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  });

  return (
    <View style={{ backgroundColor: c.card, borderRadius: radius.xl, borderWidth: 1.5,
      borderColor: c.warning + '60', marginBottom: spacing.md, overflow: 'hidden' }}>

      {/* Amber accent stripe — signals action required */}
      <View style={{ height: 4, backgroundColor: c.warning }} />

      <View style={{ padding: spacing.md, gap: spacing.md }}>

        {/* Header */}
        <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm }}>
          <View style={{ width: 48, height: 48, borderRadius: radius.lg,
            backgroundColor: c.warning + '18', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <Text style={{ fontSize: 22 }}>📋</Text>
          </View>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: 3 }}>
              <View style={{ backgroundColor: c.warning + '20', paddingHorizontal: spacing.sm,
                paddingVertical: 2, borderRadius: radius.full, borderWidth: 1, borderColor: c.warning + '50' }}>
                <Text style={{ fontSize: 10, fontWeight: fontWeight.bold, color: c.warning,
                  textTransform: 'uppercase', letterSpacing: 0.7 }}>Action Required</Text>
              </View>
            </View>
            <Text style={{ fontSize: fontSize.lg, fontWeight: fontWeight.extrabold, color: c.foreground, letterSpacing: -0.3 }}>
              {truckName ?? 'Dispatch Assignment'}
            </Text>
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 }}>📅 {dateLabel}</Text>
          </View>
        </View>

        {/* Message body */}
        <View style={{ backgroundColor: c.surfaceMuted, borderRadius: radius.md,
          padding: spacing.sm + 2, borderWidth: 1, borderColor: c.border }}>
          <Text style={{ fontSize: fontSize.sm, color: c.foreground, lineHeight: 21 }}>
            {cleanMsg ?? 'Confirm your attendance to begin the check-in process.'}
          </Text>
        </View>

        {/* Action buttons */}
        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          <TouchableOpacity
            onPress={() => respond('declined')}
            disabled={!!acting}
            style={{ flex: 1, paddingVertical: spacing.sm + 4, borderRadius: radius.lg,
              borderWidth: 1.5, alignItems: 'center', justifyContent: 'center',
              borderColor: c.danger, backgroundColor: c.danger + '10',
              opacity: acting === 'confirming' ? 0.3 : 1 }}>
            {acting === 'declining'
              ? <ActivityIndicator size="small" color={c.danger} />
              : <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.bold, color: c.danger }}>Decline</Text>}
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => respond('confirmed')}
            disabled={!!acting}
            style={{ flex: 2, paddingVertical: spacing.sm + 4, borderRadius: radius.lg,
              alignItems: 'center', justifyContent: 'center',
              backgroundColor: c.success,
              opacity: acting === 'declining' ? 0.3 : 1 }}>
            {acting === 'confirming'
              ? <ActivityIndicator size="small" color="#fff" />
              : <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.bold, color: '#fff' }}>✓  Confirm Attendance</Text>}
          </TouchableOpacity>
        </View>

      </View>
    </View>
  );
}

function StepCheckIn({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const [acting, setActing] = useState(false);
  const act = async () => {
    setActing(true);
    try {
      await apiClient.post('/field-ops/check-in', { employee_id: employeeId, date: localToday() });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Check-in failed.')); }
    finally { setActing(false); }
  };
  if (shift.checkedIn) {
    return <CompletedRow num="1" title="Check In" summary={`${fmtTime(shift.checkedInAt)}`} c={c} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="1" title="Check In — Arrive at Offsite"
        subtitle="Clock in when you arrive to pick up your truck." c={c} />
      <Btn label="Check In" onPress={act} loading={acting} c={c} />
    </Card>
  );
}

function StepDockAssignment({ dockZone, c }: { dockZone: string | null; c: ThemeColors }) {
  // Only collapse once we're past the offsite section (i.e. departed). While still offsite,
  // keep it visible so the driver can see their gate.
  return (
    <Card c={c}>
      <SectionHeader num="2" title="Your Gate Assignment" c={c} />
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md,
        backgroundColor: dockZone ? c.primary + '12' : c.surfaceMuted,
        borderRadius: radius.md, padding: spacing.md,
        borderWidth: 1, borderColor: dockZone ? c.primary + '40' : c.border }}>
        <Text style={{ fontSize: 28 }}>🚪</Text>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.6 }}>
            {dockZone ? 'Assigned Gate' : 'Gate Assignment'}
          </Text>
          <Text style={{ fontSize: fontSize.xl, fontWeight: fontWeight.extrabold,
            color: dockZone ? c.primary : c.mutedForeground, marginTop: 2 }}>
            {dockZone ?? 'Not yet assigned'}
          </Text>
          {!dockZone && (
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 }}>
              Dispatch will assign your gate before shift start. Pull down to refresh.
            </Text>
          )}
        </View>
      </View>
    </Card>
  );
}

function StepInspection({ employeeId, shift, inspType, stepNum, title, subtitle, onDone, c }: {
  employeeId: string; shift: ShiftState; inspType: 'pre_trip' | 'eod';
  stepNum: string; title: string; subtitle: string; onDone: () => void; c: ThemeColors;
}) {
  const done = inspType === 'pre_trip' ? shift.preTripDone : shift.eodDone;
  const data = inspType === 'pre_trip' ? shift.preTripData : shift.eodData;
  if (done) {
    return <CompletedRow num={stepNum} title={title} c={c}
      summary={data?.has_failures ? 'Failures noted' : 'All passed'} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num={stepNum} title={title} subtitle={subtitle} c={c} />
      <InspectionForm employeeId={employeeId} inspType={inspType} onDone={onDone} c={c} />
    </Card>
  );
}

function StepStartOdometer({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const [unit, setUnit] = useState<Unit>('imperial');
  const [val,  setVal]  = useState('');
  const [saving, setSaving] = useState(false);
  const distU = unit === 'metric' ? 'km' : 'mi';
  const done = !!shift.fuelLog;
  const submit = async () => {
    const n = parseFloat(val);
    if (isNaN(n) || n < 0) { Alert.alert('Invalid', 'Enter a valid reading.'); return; }
    setSaving(true);
    try {
      await apiClient.post('/field-ops/fuel-log', { driver_id: employeeId, date: localToday(), odometer_start: toMi(n, unit) });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not log odometer reading. Try again.')); }
    finally { setSaving(false); }
  };
  if (done) {
    return <CompletedRow num="4" title="Start Odometer" c={c}
      summary={`${shift.fuelLog ? toDisp(shift.fuelLog.odometer_start, unit) : '—'} ${distU}`} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="4" title="Log Start Odometer"
        subtitle="Record the truck's odometer before leaving the offsite." c={c} />
      <View style={{ flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.sm }}>
        {(['imperial', 'metric'] as const).map(u => (
          <TouchableOpacity key={u} onPress={() => setUnit(u)}
            style={{ flex: 1, paddingVertical: spacing.xs, borderRadius: radius.sm, borderWidth: 1,
              alignItems: 'center', backgroundColor: unit === u ? c.primary : 'transparent',
              borderColor: unit === u ? c.primary : c.border }}>
            <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold,
              color: unit === u ? '#fff' : c.mutedForeground }}>{u === 'imperial' ? 'mi / gal' : 'km / L'}</Text>
          </TouchableOpacity>
        ))}
      </View>
      <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
        fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.sm }}
        value={val} onChangeText={setVal} placeholder={`Odometer reading (${distU})`}
        placeholderTextColor={c.mutedForeground} keyboardType="numeric" />
      <Btn label="Log Start Odometer" onPress={submit} disabled={!val} loading={saving} c={c} />
    </Card>
  );
}

function StepStationArrival({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const done = shift.stationLoadArrived;
  const [staged,   setStaged]   = useState<boolean | null>(null);
  const [missing,  setMissing]  = useState<Record<string, boolean>>({});
  const [saving,   setSaving]   = useState(false);

  const toggleMissing = (item: string) =>
    setMissing(p => ({ ...p, [item]: !p[item] }));

  const submit = async () => {
    if (staged === null) { Alert.alert('Required', 'Was the area staged when you arrived?'); return; }
    setSaving(true);
    try {
      await apiClient.post('/field-ops/station-arrival', {
        employee_id: employeeId,
        date: localToday(),
        arrival_type: 'loading',
        was_staged: staged,
        missing_items: staged ? [] : Object.keys(missing).filter(k => missing[k]),
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not record station arrival. Try again.')); }
    finally { setSaving(false); }
  };

  const missingArr = shift.missingItems ?? [];
  if (done) {
    const summary = shift.wasStaged === true
      ? `Staged · ${fmtTime(shift.stationLoadAt)}`
      : shift.wasStaged === false
        ? `Not staged · ${missingArr.map(k => STAGING_LABELS[k] ?? k).join(', ') || fmtTime(shift.stationLoadAt)}`
        : `Arrived ${fmtTime(shift.stationLoadAt)}`;
    return <CompletedRow num="5" title="Station Arrival — Loading" summary={summary} c={c} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="5" title="Arrive at Station — Loading"
        subtitle="Record your arrival and check if your area was staged." c={c} />
      <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground, marginBottom: spacing.sm }}>
        Was your area already staged when you arrived?
      </Text>
      <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md }}>
        {([true, false] as const).map(v => (
          <TouchableOpacity key={String(v)} onPress={() => setStaged(v)}
            style={{ flex: 1, paddingVertical: spacing.sm, borderRadius: radius.md, borderWidth: 1,
              alignItems: 'center',
              backgroundColor: staged === v ? (v ? c.success : c.danger) : 'transparent',
              borderColor: staged === v ? (v ? c.success : c.danger) : c.border }}>
            <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold,
              color: staged === v ? '#fff' : c.mutedForeground }}>{v ? 'Yes — Staged' : 'No — Not Ready'}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {staged === false && (
        <View style={{ marginBottom: spacing.md }}>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.sm }}>
            What was missing? (select all that apply)
          </Text>
          {STAGING_ITEMS.map(item => (
            <TouchableOpacity key={item} onPress={() => toggleMissing(item)}
              style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.xs,
                borderBottomWidth: 1, borderBottomColor: c.border, gap: spacing.sm }}>
              <View style={{ width: 20, height: 20, borderRadius: 4, borderWidth: 1.5,
                borderColor: missing[item] ? c.danger : c.border,
                backgroundColor: missing[item] ? c.danger : 'transparent',
                alignItems: 'center', justifyContent: 'center' }}>
                {missing[item] && <Text style={{ color: '#fff', fontSize: 12, fontWeight: fontWeight.bold }}>✓</Text>}
              </View>
              <Text style={{ fontSize: fontSize.sm, color: c.foreground }}>{STAGING_LABELS[item]}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
      <Btn label="Record Arrival" onPress={submit} disabled={staged === null} loading={saving} c={c} />
    </Card>
  );
}

function StepLoadTruck({ roster, onDone, c }: { roster: TruckRoster; onDone: () => void; c: ThemeColors }) {
  const [togglingBag, setTogglingBag] = useState<string | null>(null);
  const [confirming,  setConfirming]  = useState(false);
  const [filter,      setFilter]      = useState('');
  const [hideChecked, setHideChecked] = useState(false);
  const [collapsed,   setCollapsed]   = useState<Record<string, boolean>>({});

  const unchecked = roster.tote_count - roster.checked_count;
  const pct = roster.tote_count > 0 ? Math.round((roster.checked_count / roster.tote_count) * 100) : 0;

  // Group by dock tag (how totes are physically staged on the dock). A tote may
  // carry multiple tags; group by its first, fall back to "Unstaged". Filter by
  // bag or dock tag; optionally hide already-loaded totes.
  const groups = useMemo(() => {
    const q = filter.trim().toUpperCase();
    const matches = (t: RosterTote) =>
      (!hideChecked || !t.checked) &&
      (!q || t.bag_id.toUpperCase().includes(q) || (t.dock_tags ?? []).some(d => d.toUpperCase().includes(q)));
    const by: Record<string, RosterTote[]> = {};
    for (const t of roster.totes) {
      if (!matches(t)) continue;
      const key = (t.dock_tags ?? [])[0] || 'Unstaged';
      (by[key] ??= []).push(t);
    }
    return Object.keys(by).sort().map(label => {
      const totes = by[label];
      return { label, totes, loaded: totes.filter(t => t.checked).length };
    });
  }, [roster.totes, filter, hideChecked]);

  const toggle = async (tote: RosterTote) => {
    if (roster.load_confirmed || togglingBag) return;
    setTogglingBag(tote.bag_id);
    try {
      await apiClient.post(`/sort/${localToday()}/totes/${tote.bag_id}/check`, { checked: !tote.checked });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not update the tote.')); }
    finally { setTogglingBag(null); }
  };

  const confirmLoad = () => {
    const doConfirm = async () => {
      setConfirming(true);
      try {
        await apiClient.post(`/sort/${localToday()}/trucks/${roster.truck_id}/confirm-load`);
        onDone();
      } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not confirm the load.')); }
      finally { setConfirming(false); }
    };
    if (unchecked > 0) {
      Alert.alert(
        'Confirm with missing totes?',
        `${unchecked} roster tote${unchecked === 1 ? ' is' : 's are'} still unchecked. They'll be recorded as short and dispatch will be notified.`,
        [{ text: 'Cancel', style: 'cancel' }, { text: 'Confirm Anyway', style: 'destructive', onPress: doConfirm }],
      );
    } else {
      doConfirm();
    }
  };

  const reopen = () => {
    Alert.alert('Reopen loading?', 'This unlocks tote check-off and clears your confirmation.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Reopen', style: 'destructive', onPress: async () => {
        try {
          await apiClient.delete(`/sort/${localToday()}/trucks/${roster.truck_id}/confirm-load`);
          onDone();
        } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not reopen loading.')); }
      }},
    ]);
  };

  if (roster.load_confirmed) {
    return (
      <View>
        <CompletedRow num="6" title="Load Truck" c={c}
          summary={`${roster.checked_count}/${roster.tote_count} totes confirmed ${fmtTime(roster.confirmed_at)}${roster.short_count ? ` · ${roster.short_count} short` : ''}`} />
        <TouchableOpacity onPress={reopen} style={{ alignSelf: 'flex-end', marginTop: -6, marginBottom: spacing.sm, padding: spacing.xs }}>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, textDecorationLine: 'underline' }}>Reopen loading</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const noMatch = groups.length === 0;

  return (
    <Card c={c}>
      <SectionHeader num="6" title="Load Truck"
        subtitle="Check each tote off as it goes on the truck, then confirm your load. Dispatch sees this live." c={c} />

      {/* Progress header */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm }}>
        <View style={{ flex: 1, height: 6, borderRadius: 999, backgroundColor: c.border, overflow: 'hidden' }}>
          <View style={{ width: `${pct}%`, height: '100%', borderRadius: 999, backgroundColor: pct === 100 ? '#0FA870' : c.primary }} />
        </View>
        <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground }}>
          {roster.checked_count}/{roster.tote_count} loaded
        </Text>
      </View>

      {/* Filter + hide-checked */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm }}>
        <TextInput
          value={filter}
          onChangeText={setFilter}
          placeholder="Filter bag or dock…"
          placeholderTextColor={c.mutedForeground}
          autoCapitalize="characters"
          style={{ flex: 1, fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background,
            borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs + 2 }}
        />
        <TouchableOpacity
          onPress={() => setHideChecked(v => !v)}
          style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs }}
        >
          <Switch value={hideChecked} onValueChange={setHideChecked} />
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>Hide loaded</Text>
        </TouchableOpacity>
      </View>

      {noMatch ? (
        <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground, paddingVertical: spacing.md, textAlign: 'center' }}>
          {roster.tote_count === 0 ? 'No totes on this roster.' : 'No totes match your filter.'}
        </Text>
      ) : groups.map(g => {
        const isCollapsed = collapsed[g.label];
        const allLoaded = g.loaded === g.totes.length;
        return (
          <View key={g.label} style={{ marginBottom: spacing.xs }}>
            {/* Section header */}
            <TouchableOpacity
              onPress={() => setCollapsed(p => ({ ...p, [g.label]: !p[g.label] }))}
              style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
                paddingVertical: spacing.xs + 2, borderTopWidth: 1, borderTopColor: c.border }}
            >
              <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.bold, color: c.foreground, flex: 1 }}>
                {g.label}
              </Text>
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: allLoaded ? '#0FA870' : c.mutedForeground }}>
                {g.loaded}/{g.totes.length}{allLoaded ? ' ✓' : ''}
              </Text>
              <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>{isCollapsed ? '▸' : '▾'}</Text>
            </TouchableOpacity>
            {!isCollapsed && g.totes.map(t => (
              <ToteRow key={t.bag_id} tote={t} toggling={togglingBag === t.bag_id}
                disabled={togglingBag !== null} onPress={() => toggle(t)} c={c} />
            ))}
          </View>
        );
      })}

      <View style={{ marginTop: spacing.md }}>
        <Btn
          label={unchecked > 0 ? `Confirm Load (${unchecked} unchecked)` : 'Confirm Load'}
          onPress={confirmLoad} loading={confirming} c={c}
        />
      </View>
    </Card>
  );
}

function ToteRow({ tote: t, toggling, disabled, onPress, c }: {
  tote: RosterTote; toggling: boolean; disabled: boolean; onPress: () => void; c: ThemeColors;
}) {
  const pullCount = t.pull_tbas?.length ?? 0;
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled}
      style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
        paddingVertical: spacing.sm, paddingLeft: spacing.sm }}
    >
      <View style={{ width: 24, height: 24, borderRadius: 6, borderWidth: 2,
        borderColor: t.checked ? '#0FA870' : c.border,
        backgroundColor: t.checked ? '#0FA870' : 'transparent',
        alignItems: 'center', justifyContent: 'center' }}>
        {toggling
          ? <ActivityIndicator size="small" color={t.checked ? '#fff' : c.primary} />
          : t.checked ? <Text style={{ color: '#fff', fontSize: 14, fontWeight: '700' }}>✓</Text> : null}
      </View>
      <View style={{ flex: 1 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, flexWrap: 'wrap' }}>
          <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground }}>{t.bag_id}</Text>
          {t.ov_count > 0 && (
            <View style={{ backgroundColor: '#E0F2FE', borderRadius: radius.full, paddingHorizontal: spacing.xs + 2, paddingVertical: 1 }}>
              <Text style={{ fontSize: fontSize.xs, color: '#0369A1', fontWeight: fontWeight.semibold }}>{t.ov_count} OV</Text>
            </View>
          )}
          {pullCount > 0 && (
            <View style={{ backgroundColor: '#FEF3C7', borderRadius: radius.full, paddingHorizontal: spacing.xs + 2, paddingVertical: 1 }}>
              <Text style={{ fontSize: fontSize.xs, color: '#B45309', fontWeight: fontWeight.semibold }}>⚠ pull {pullCount} at AP</Text>
            </View>
          )}
        </View>
        <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>
          {t.package_count} pkgs
          {t.checked && t.checked_by_name ? ` · ${t.checked_by_name}` : ''}
        </Text>
      </View>
    </TouchableOpacity>
  );
}

function StepWalkerHandoffs({ summary, onDone, c }: { summary: RTSSummary; onDone: () => void; c: ThemeColors }) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [flaggingId,   setFlaggingId]   = useState<string | null>(null);
  const [flagNotes,    setFlagNotes]    = useState('');

  const returned = summary.routes.filter(r => r.handoff_exists);
  const pending  = returned.filter(r => !r.driver_confirmed_at);

  const confirm = async (r: RTSSummaryRoute, discrepancy?: string) => {
    setConfirmingId(r.route_id);
    try {
      await apiClient.post(`/rts/handoff/${r.route_id}/confirm`, discrepancy
        ? { discrepancy_flagged: true, discrepancy_notes: discrepancy }
        : { discrepancy_flagged: false });
      setFlaggingId(null); setFlagNotes('');
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not confirm the handoff.')); }
    finally { setConfirmingId(null); }
  };

  return (
    <Card c={c}>
      <SectionHeader num="✓" title="Walker Handoffs"
        subtitle={pending.length > 0
          ? `Count each walker's returned RTS packages against their declared number, then confirm.`
          : 'All returned routes confirmed.'} c={c} />
      {returned.map(r => (
        <View key={r.route_id} style={{ borderTopWidth: 1, borderTopColor: c.border, paddingVertical: spacing.sm }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground }}>
                Route {r.route_number}{r.walker_name ? ` · ${r.walker_name}` : ''}
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 1 }}>
                {r.rts_count} RTS{r.missing_count ? ` · ${r.missing_count} missing` : ''}
                {r.discrepancy_flagged ? ' · ⚠ discrepancy flagged' : ''}
              </Text>
            </View>
            {r.driver_confirmed_at ? (
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: '#0FA870' }}>
                ✓ {fmtTime(r.driver_confirmed_at)}
              </Text>
            ) : (
              <View style={{ flexDirection: 'row', gap: spacing.xs }}>
                <TouchableOpacity
                  onPress={() => { setFlaggingId(flaggingId === r.route_id ? null : r.route_id); setFlagNotes(''); }}
                  style={{ borderWidth: 1, borderColor: c.warning + '66', borderRadius: radius.md,
                    paddingHorizontal: spacing.sm, paddingVertical: spacing.xs + 2 }}>
                  <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.warning }}>Flag</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => confirm(r)}
                  disabled={confirmingId !== null}
                  style={{ backgroundColor: '#0FA870', borderRadius: radius.md,
                    paddingHorizontal: spacing.sm + 2, paddingVertical: spacing.xs + 2 }}>
                  {confirmingId === r.route_id
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: '#fff' }}>Confirm</Text>}
                </TouchableOpacity>
              </View>
            )}
          </View>
          {flaggingId === r.route_id && !r.driver_confirmed_at && (
            <View style={{ marginTop: spacing.sm }}>
              <TextInput
                style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
                  fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background }}
                value={flagNotes} onChangeText={setFlagNotes}
                placeholder="What doesn't match? (e.g. declared 4, received 3)"
                placeholderTextColor={c.mutedForeground} multiline />
              <View style={{ marginTop: spacing.xs }}>
                <Btn label="Confirm with Discrepancy" variant="ghost"
                  onPress={() => flagNotes.trim() ? confirm(r, flagNotes.trim()) : Alert.alert('Required', 'Describe the discrepancy first.')}
                  loading={confirmingId === r.route_id} c={c} />
              </View>
            </View>
          )}
        </View>
      ))}
    </Card>
  );
}

function StepManifest({ truckId, shift, employeeId, onDone, c }: {
  truckId: string | null; shift: ShiftState; employeeId: string; onDone: () => void; c: ThemeColors;
}) {
  const m = shift.manifest;
  const [acking, setAcking] = useState(false);

  const acknowledge = async () => {
    if (!truckId) return;
    setAcking(true);
    try {
      await apiClient.patch(`/field-ops/manifest/${truckId}/acknowledge`);
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not confirm manifest. Try again.')); }
    finally { setAcking(false); }
  };

  if (m?.acknowledged_at) {
    return <CompletedRow num="6" title="Package Manifest" c={c}
      summary={`${m.tote_count} totes · ${m.ov_count} OV · confirmed ${fmtTime(m.acknowledged_at)}`} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="6" title="Package Manifest"
        subtitle="Review your load — confirm everything is accounted for." c={c} />
      {!m ? (
        <View style={{ backgroundColor: c.warning + '12', borderRadius: radius.md, borderWidth: 1,
          borderColor: c.warning + '40', padding: spacing.md }}>
          <Text style={{ fontSize: fontSize.sm, color: c.warning, fontWeight: fontWeight.semibold }}>
            No manifest entered yet
          </Text>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 4 }}>
            Dispatch hasn't entered your load details. Ask your captain or pull down to refresh.
          </Text>
        </View>
      ) : (
        <>
          <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md }}>
            {[
              { label: 'Totes',       val: m.tote_count, icon: '📦' },
              { label: 'OV Packages', val: m.ov_count,   icon: '🚚' },
            ].map(({ label, val, icon }) => (
              <View key={label} style={{ flex: 1, backgroundColor: c.surfaceMuted, borderRadius: radius.md,
                padding: spacing.md, alignItems: 'center', borderWidth: 1, borderColor: c.border }}>
                <Text style={{ fontSize: 22 }}>{icon}</Text>
                <Text style={{ fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, color: c.foreground }}>{val}</Text>
                <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'uppercase',
                  letterSpacing: 0.5, marginTop: 2 }}>{label}</Text>
              </View>
            ))}
          </View>
          {m.notes ? (
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, fontStyle: 'italic',
              marginBottom: spacing.sm }}>Note: {m.notes}</Text>
          ) : null}
          <Btn label="Confirm — Load is Correct" onPress={acknowledge} loading={acking} c={c} />
        </>
      )}
    </Card>
  );
}

function StepDeparture({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const [acting, setActing] = useState(false);
  const act = async () => {
    setActing(true);
    try {
      await apiClient.post('/field-ops/departure', { employee_id: employeeId, date: localToday() });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not record departure. Try again.')); }
    finally { setActing(false); }
  };
  if (shift.departed) {
    return <CompletedRow num="7" title="Departure" summary={`Departed ${fmtTime(shift.departedAt)}`} c={c} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="7" title="Record Departure"
        subtitle="Tap when you leave the station. Your truck becomes active on dispatch." c={c} />
      <Btn label="Record Departure" onPress={act} loading={acting} c={c} />
    </Card>
  );
}

function StepAnchorPoint({ employeeId, truckId, shift, onDone, c }: {
  employeeId: string; truckId: string | null; shift: ShiftState; onDone: () => void; c: ThemeColors;
}) {
  const ap = shift.activeAP;
  const done = !!ap;
  const [location,    setLocation]    = useState('');
  const [etaDate,     setEtaDate]     = useState<Date | null>(null);
  const [showPicker,  setShowPicker]  = useState(false);
  const [saving,      setSaving]      = useState(false);
  const submitting = useRef(false);

  const etaLabel = etaDate
    ? etaDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  const submit = async () => {
    if (submitting.current) return;
    if (!location.trim()) { Alert.alert('Required', 'Enter a cross street or address for your anchor point.'); return; }
    if (!etaLabel) { Alert.alert('Required', 'Set your ETA — crew and dispatch need your arrival time.'); return; }
    if (!truckId) { Alert.alert('No truck assigned', 'Your dispatch assignment hasn\'t loaded yet. Pull down to refresh — if this persists, contact dispatch.'); return; }
    submitting.current = true;
    setSaving(true);
    try {
      await apiClient.post('/anchor-points/', {
        truck_id: truckId, date: localToday(),
        location: location.trim(), eta: etaLabel,
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not post anchor point. Try again.')); }
    finally { setSaving(false); submitting.current = false; }
  };

  if (done) {
    return (
      <CompletedRow num="8" title="Anchor Point" c={c}
        summary={ap ? `${ap.location}${ap.eta ? ` — ETA ${ap.eta}` : ''}` : ''} />
    );
  }

  return (
    <Card c={c}>
      <SectionHeader num="8" title="Post Anchor Point + ETA"
        subtitle="Enter a cross street or address — it's geocoded to place your AP. ETA is required."
        c={c} />
      <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
        fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.sm }}
        value={location} onChangeText={setLocation}
        placeholder="Cross street or address (e.g. W 28 St & 9 Ave)" placeholderTextColor={c.mutedForeground} />
      <TouchableOpacity onPress={() => { setEtaDate(etaDate ?? new Date()); setShowPicker(true); }}
        style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
          borderWidth: 1, borderColor: etaDate ? c.primary : c.border, borderRadius: radius.md,
          padding: spacing.sm, backgroundColor: c.background, marginBottom: spacing.sm }}>
        <Text style={{ fontSize: fontSize.sm, color: etaDate ? c.foreground : c.mutedForeground }}>
          {etaLabel ?? 'ETA — required'}
        </Text>
        <Text style={{ fontSize: fontSize.xs, color: c.primary }}>
          {etaDate ? 'Change' : 'Set time'}
        </Text>
      </TouchableOpacity>
      {!truckId && (
        <Text style={{ fontSize: fontSize.xs, color: c.warning, marginBottom: spacing.sm }}>
          Truck assignment not loaded — pull down to refresh before posting.
        </Text>
      )}
      <Btn label="Post Anchor Point" onPress={submit} disabled={!location.trim() || !etaLabel} loading={saving} c={c} />
      {showPicker && (
        <TimePickerModal
          visible={showPicker}
          initial={etaDate ?? new Date()}
          onConfirm={(h, m) => {
            const d = new Date(); d.setHours(h, m, 0, 0);
            setEtaDate(d); setShowPicker(false);
          }}
          onCancel={() => setShowPicker(false)}
          c={c}
        />
      )}
    </Card>
  );
}

function StepAPArrive({ ap, onDone, c }: { ap: AP; onDone: () => void; c: ThemeColors }) {
  const [location, setLocation] = useState(ap.location);
  const [notes,    setNotes]    = useState('');
  const [acting,   setActing]   = useState(false);

  const confirm = async () => {
    setActing(true);
    try {
      await apiClient.patch(`/anchor-points/${ap.id}/arrive`, {
        location: location.trim() !== ap.location ? location.trim() : undefined,
        notes: notes.trim() || undefined,
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not confirm AP arrival. Try again.')); }
    finally { setActing(false); }
  };

  return (
    <Card c={c}>
      <SectionHeader num="9" title="Confirm AP Arrival"
        subtitle="Tap when you arrive. Correct the location if needed." c={c} />
      <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
        fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.sm }}
        value={location} onChangeText={setLocation} placeholderTextColor={c.mutedForeground} />
      <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
        fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.sm }}
        value={notes} onChangeText={setNotes} placeholder="Notes (optional)" placeholderTextColor={c.mutedForeground} />
      <Btn label="Confirm Arrival at AP" onPress={confirm} loading={acting} c={c} />
    </Card>
  );
}

function StepCheckIn1({ employeeId, shift, crew, onDone, c }: {
  employeeId: string; shift: ShiftState; crew: CrewMember[]; onDone: () => void; c: ThemeColors;
}) {
  const done = !!shift.checkIn1;
  const nonDriverCrew = crew.filter(m => m.role !== 'driver');
  type Entry = { present: boolean; uniform: boolean; cartCover: boolean };
  const defaultEntries = (): Record<string, Entry> =>
    Object.fromEntries(nonDriverCrew.map(m => [m.id, { present: true, uniform: true, cartCover: true }]));
  const [entries, setEntries] = useState<Record<string, Entry>>(defaultEntries);
  const [saving, setSaving] = useState(false);

  // Re-initialize if crew list arrives after first render
  useEffect(() => {
    if (nonDriverCrew.length > 0)
      setEntries(prev => {
        const next = { ...prev };
        for (const m of nonDriverCrew) {
          if (!next[m.id]) next[m.id] = { present: true, uniform: true, cartCover: true };
        }
        return next;
      });
  }, [nonDriverCrew.length]);

  const setField = (id: string, field: keyof Entry, val: boolean) =>
    setEntries(p => { const cur = p[id] ?? { present: true, uniform: true, cartCover: true }; return { ...p, [id]: { ...cur, [field]: val } }; });

  const allSet = nonDriverCrew.every(m => entries[m.id] !== undefined);

  const submit = async () => {
    if (!allSet) { Alert.alert('Incomplete', 'Mark attendance for all crew members.'); return; }
    setSaving(true);
    const ncns = nonDriverCrew.filter(m => !entries[m.id]?.present).length;
    const working = nonDriverCrew.filter(m => entries[m.id]?.present).length;
    try {
      // Submit crew compliance for all present members
      const compEntries = nonDriverCrew
        .filter(m => entries[m.id]?.present)
        .map(m => ({
          employee_id: m.id,
          uniform_pass:    entries[m.id]?.uniform   ?? true,
          cart_cover_pass: entries[m.id]?.cartCover ?? true,
        }));
      if (compEntries.length > 0) {
        await apiClient.post('/shift-ops/crew-compliance', {
          driver_id: employeeId, date: localToday(), entries: compEntries,
        });
      }
      // Submit check-in 1
      await apiClient.post('/shift-ops/check-in', {
        driver_id: employeeId, date: localToday(), check_in_number: 1,
        routes_remaining: nonDriverCrew.length, // total routes initially = crew size
        help_requested: false,
        working_crew_count: working,
        ncns_count: ncns,
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not submit check-in. Try again.')); }
    finally { setSaving(false); }
  };

  if (done) {
    return <CompletedRow num="10" title="Check-in 1" c={c}
      summary={shift.checkIn1 ? `${shift.checkIn1.working_crew_count} working · ${shift.checkIn1.ncns_count} NCNS` : ''} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="10" title={`Check-in 1 ${CI_TIMES[0]}`}
        subtitle="Routes handed out by captain. Mark attendance and uniform compliance for each crew member." c={c} />
      {nonDriverCrew.map(m => {
        const e = entries[m.id] ?? { present: true, uniform: true, cartCover: true };
        return (
          <View key={m.id} style={{ backgroundColor: c.background, borderRadius: radius.md, borderWidth: 1,
            borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm }}>
            <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground, marginBottom: spacing.sm }}>
              {m.name}
            </Text>
            <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: e.present ? spacing.sm : 0 }}>
              {([true, false] as const).map(v => (
                <TouchableOpacity key={String(v)} onPress={() => setField(m.id, 'present', v)}
                  style={{ flex: 1, paddingVertical: spacing.xs + 1, borderRadius: radius.sm, borderWidth: 1,
                    alignItems: 'center',
                    backgroundColor: e.present === v ? (v ? c.success : c.danger) : 'transparent',
                    borderColor: e.present === v ? (v ? c.success : c.danger) : c.border }}>
                  <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold,
                    color: e.present === v ? '#fff' : c.mutedForeground }}>{v ? 'Present' : 'NCNS'}</Text>
                </TouchableOpacity>
              ))}
            </View>
            {e.present && (
              <View style={{ gap: spacing.xs }}>
                {[
                  { field: 'uniform' as const,    label: 'Uniform pass' },
                  { field: 'cartCover' as const,  label: 'Cart cover pass' },
                ].map(({ field, label }) => (
                  <View key={field} style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>{label}</Text>
                    <Switch
                      value={e[field]}
                      onValueChange={v => setField(m.id, field, v)}
                      trackColor={{ false: c.danger + '80', true: c.success + '80' }}
                      thumbColor={e[field] ? c.success : c.danger}
                    />
                  </View>
                ))}
              </View>
            )}
          </View>
        );
      })}
      <Btn label="Submit Check-in 1 & Compliance" onPress={submit} disabled={!allSet} loading={saving} c={c} />
    </Card>
  );
}

function StepWalkerRatings({ walkers, drafts, submitted, onUpdateDraft, c }: {
  walkers: CrewMember[];
  drafts: Record<string, WalkerDraft>;
  submitted: Record<string, boolean>;
  onUpdateDraft: (id: string, patch: Partial<WalkerDraft>) => void;
  c: ThemeColors;
}) {
  const pending = walkers.filter(w => !submitted[w.id]);
  const done    = walkers.filter(w => submitted[w.id]);
  if (walkers.length === 0) return null;

  return (
    <Card c={c}>
      <SectionHeader num="11" title="Walker Ratings"
        subtitle={`Rate each walker during the route. Drafts auto-save. Submitted with end odometer.\nTarget: ${CI_TIMES[3]}`}
        done={pending.length === 0} doneLabel={`${done.length}/${walkers.length} rated`} c={c} />
      {done.map(w => (
        <View key={w.id} style={{ backgroundColor: c.success + '10', borderRadius: radius.md, borderWidth: 1,
          borderColor: c.success + '30', padding: spacing.sm, marginBottom: spacing.xs,
          flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
          <Text style={{ color: c.success, fontSize: fontSize.xs }}>✓</Text>
          <Text style={{ fontSize: fontSize.sm, color: c.foreground, fontWeight: fontWeight.medium }}>{w.name}</Text>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginLeft: 'auto' }}>Submitted</Text>
        </View>
      ))}
      {pending.map(w => {
        const d = drafts[w.id] ?? { stars: 0, comment: '' };
        return (
          <View key={w.id} style={{ backgroundColor: c.background, borderRadius: radius.md, borderWidth: 1,
            borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm }}>
            <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground, marginBottom: spacing.sm }}>{w.name}</Text>
            <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.sm }}>
              {[1,2,3,4,5].map(star => (
                <TouchableOpacity key={star} onPress={() => onUpdateDraft(w.id, { stars: star })}>
                  <Text style={{ fontSize: 28, color: star <= d.stars ? c.gold : c.border }}>★</Text>
                </TouchableOpacity>
              ))}
            </View>
            <TextInput
              style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
                fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.card,
                minHeight: 52, textAlignVertical: 'top' }}
              value={d.comment}
              onChangeText={t => onUpdateDraft(w.id, { comment: t })}
              placeholder="Comment (optional, private)…" placeholderTextColor={c.mutedForeground} multiline />
            {d.stars > 0 && (
              <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: spacing.xs, textAlign: 'right' }}>
                Draft saved — submits with end odometer
              </Text>
            )}
          </View>
        );
      })}
    </Card>
  );
}

function StepCheckInN({ employeeId, shift, num, time, record, prevRecord, crew, onDone, c }: {
  employeeId: string; shift: ShiftState; num: 2 | 3;
  time: string; record: CheckInRecord | null; prevRecord: CheckInRecord | null;
  crew: CrewMember[]; onDone: () => void; c: ThemeColors;
}) {
  const maxWorking = prevRecord?.working_crew_count ?? shift.checkIn1?.working_crew_count ?? 0;
  const nonDriverCrew = crew.filter(m => m.role !== 'driver');
  const [routes,       setRoutes]       = useState('');
  const [working,      setWorking]      = useState(maxWorking);
  const [help,         setHelp]         = useState(false);
  const [saving,       setSaving]       = useState(false);
  const [showModal,    setShowModal]    = useState(false);
  const [leftEarly,    setLeftEarly]    = useState<Set<string>>(new Set());
  const [pendingSubmit, setPending]     = useState<{ r: number } | null>(null);

  useEffect(() => { setWorking(maxWorking); }, [maxWorking]);

  const leftCount = maxWorking - working;

  const toggleLeaver = (id: string) => {
    setLeftEarly(prev => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); return next; }
      if (next.size < leftCount) { next.add(id); return next; }
      return prev; // already at limit
    });
  };

  const handleSubmitPress = () => {
    const r = parseInt(routes, 10);
    if (isNaN(r) || r < 0) { Alert.alert('Invalid', 'Enter routes remaining.'); return; }
    if (leftCount > 0 && nonDriverCrew.length > 0) {
      setLeftEarly(new Set());
      setPending({ r });
      setShowModal(true);
    } else {
      doSubmit(r, []);
    }
  };

  const doSubmit = async (r: number, leavers: string[]) => {
    setSaving(true);
    setShowModal(false);
    try {
      await apiClient.post('/shift-ops/check-in', {
        driver_id: employeeId, date: localToday(), check_in_number: num,
        routes_remaining: r, help_requested: help,
        working_crew_count: working,
        ncns_count: shift.checkIn1?.ncns_count ?? 0,
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not submit check-in. Try again.')); }
    finally { setSaving(false); setPending(null); }
  };

  const confirmModal = () => {
    if (leftEarly.size !== leftCount) {
      Alert.alert('Select all', `Select exactly ${leftCount} crew member${leftCount !== 1 ? 's' : ''} who left early.`);
      return;
    }
    doSubmit(pendingSubmit!.r, Array.from(leftEarly));
  };

  if (record) {
    return <CompletedRow num={String(num + 9)} title={`Check-in ${num}`} c={c}
      summary={`${record.routes_remaining} routes · ${record.working_crew_count} working · ${record.help_requested ? 'Help requested' : 'OK'}`} />;
  }

  return (
    <Card c={c}>
      <SectionHeader
        num={String(num + 9)}
        title={`Check-in ${num} — ${time}`}
        subtitle={num === 2 ? 'Report routes remaining and flag if help is needed.' : 'Update routes and confirm final dispatch.'}
        c={c}
      />

      {/* Routes remaining */}
      <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
        fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.md }}
        value={routes} onChangeText={setRoutes} placeholder="Routes remaining" keyboardType="numeric"
        placeholderTextColor={c.mutedForeground} />

      {/* Working crew stepper */}
      <View style={{ marginBottom: spacing.md }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xs }}>
          <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground }}>Working crew</Text>
          <Text style={{ fontSize: fontSize.xs, color: leftCount > 0 ? c.warning : c.mutedForeground }}>
            {leftCount > 0 ? `${leftCount} left route early` : 'All working'}
          </Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: c.surfaceMuted,
          borderRadius: radius.md, borderWidth: 1, borderColor: c.border, overflow: 'hidden' }}>
          <TouchableOpacity onPress={() => setWorking(w => Math.max(0, w - 1))} disabled={working <= 0}
            style={{ paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
              borderRightWidth: 1, borderRightColor: c.border, opacity: working <= 0 ? 0.35 : 1 }}>
            <Text style={{ fontSize: 22, color: c.foreground, fontWeight: fontWeight.bold, lineHeight: 26 }}>−</Text>
          </TouchableOpacity>
          <View style={{ flex: 1, alignItems: 'center' }}>
            <Text style={{ fontSize: fontSize.xl, fontWeight: fontWeight.extrabold, color: c.foreground }}>{working}</Text>
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>of {maxWorking}</Text>
          </View>
          <TouchableOpacity onPress={() => setWorking(w => Math.min(maxWorking, w + 1))} disabled={working >= maxWorking}
            style={{ paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
              borderLeftWidth: 1, borderLeftColor: c.border, opacity: working >= maxWorking ? 0.35 : 1 }}>
            <Text style={{ fontSize: 22, color: c.foreground, fontWeight: fontWeight.bold, lineHeight: 26 }}>+</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Help request */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
        backgroundColor: c.surfaceMuted, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm }}>
        <View>
          <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground }}>Request help?</Text>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>Surfaces to dispatch dashboard</Text>
        </View>
        <Switch value={help} onValueChange={setHelp}
          trackColor={{ false: c.border, true: c.warning + '80' }} thumbColor={help ? c.warning : c.mutedForeground} />
      </View>

      <Btn label={`Submit Check-in ${num}`} onPress={handleSubmitPress} disabled={!routes} loading={saving} c={c} />

      {/* Early leaver modal */}
      <Modal transparent visible={showModal} animationType="slide" onRequestClose={() => setShowModal(false)}>
        <View style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000055' }}>
          <View style={{ backgroundColor: c.card, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl,
            borderWidth: 1, borderBottomWidth: 0, borderColor: c.border, paddingBottom: 32 }}>
            {/* Handle */}
            <View style={{ alignItems: 'center', paddingTop: spacing.sm, paddingBottom: spacing.xs }}>
              <View style={{ width: 40, height: 4, borderRadius: 2, backgroundColor: c.border }} />
            </View>
            <View style={{ paddingHorizontal: spacing.md, paddingBottom: spacing.md }}>
              <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground }}>
                Who left the route early?
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 }}>
                Select {leftCount} crew member{leftCount !== 1 ? 's' : ''} · {leftEarly.size} of {leftCount} selected
              </Text>
            </View>
            {nonDriverCrew.map((m, i) => {
              const selected = leftEarly.has(m.id);
              const atLimit  = leftEarly.size >= leftCount && !selected;
              return (
                <TouchableOpacity key={m.id} onPress={() => toggleLeaver(m.id)}
                  disabled={atLimit}
                  style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: spacing.md,
                    paddingVertical: spacing.md, opacity: atLimit ? 0.4 : 1,
                    borderTopWidth: i === 0 ? 1 : 0, borderBottomWidth: 1, borderColor: c.border,
                    backgroundColor: selected ? c.warning + '12' : 'transparent' }}>
                  <View style={{ width: 22, height: 22, borderRadius: 11, borderWidth: 2,
                    borderColor: selected ? c.warning : c.border,
                    backgroundColor: selected ? c.warning : 'transparent',
                    alignItems: 'center', justifyContent: 'center', marginRight: spacing.md }}>
                    {selected && <Text style={{ color: '#fff', fontSize: 12, fontWeight: fontWeight.bold }}>✓</Text>}
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground }}>{m.name}</Text>
                    <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, textTransform: 'capitalize' }}>{m.role}</Text>
                  </View>
                </TouchableOpacity>
              );
            })}
            <View style={{ flexDirection: 'row', gap: spacing.sm, paddingHorizontal: spacing.md, paddingTop: spacing.md }}>
              <TouchableOpacity onPress={() => setShowModal(false)} style={{ flex: 1, padding: spacing.md,
                borderRadius: radius.md, borderWidth: 1, borderColor: c.border, alignItems: 'center' }}>
                <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={confirmModal}
                disabled={leftEarly.size !== leftCount}
                style={{ flex: 2, padding: spacing.md, borderRadius: radius.md,
                  backgroundColor: leftEarly.size === leftCount ? c.primary : c.border, alignItems: 'center' }}>
                <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold,
                  color: leftEarly.size === leftCount ? '#fff' : c.mutedForeground }}>
                  Confirm & Submit
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </Card>
  );
}

function StepRTSReport({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const rts = shift.rtsReport;
  const done = !!rts;
  const [crewCount,  setCrewCount]  = useState('');
  const [entries,    setEntries]    = useState<{ reason: string; count: string }[]>([{ reason: '', count: '' }]);
  const [saving,     setSaving]     = useState(false);
  const [prefilled,  setPrefilled]  = useState(false);

  // ADR-193 D4: prefill from what walkers actually recorded — the driver
  // adjusts instead of recalling from memory. Runs once; never overwrites edits.
  const reasonTotals = shift.rtsSummary?.reason_totals;
  useEffect(() => {
    if (prefilled || done || !reasonTotals) return;
    const rows = Object.entries(reasonTotals)
      .filter(([, n]) => n > 0)
      .map(([type, n]) => ({ reason: RTS_TYPE_LABELS[type] ?? type, count: String(n) }));
    if (rows.length > 0) { setEntries(rows); setPrefilled(true); }
  }, [prefilled, done, reasonTotals]);

  const unconfirmed = shift.rtsSummary?.unconfirmed_handoffs ?? 0;

  const addEntry    = () => setEntries(p => [...p, { reason: '', count: '' }]);
  const removeEntry = (i: number) => setEntries(p => p.filter((_, j) => j !== i));
  const setReason   = (i: number, v: string) => setEntries(p => p.map((e, j) => j === i ? { ...e, reason: v } : e));
  const setCount    = (i: number, v: string) => setEntries(p => p.map((e, j) => j === i ? { ...e, count: v }  : e));

  const submit = async () => {
    const cc = parseInt(crewCount, 10);
    if (isNaN(cc) || cc < 0) { Alert.alert('Invalid', 'Enter crew count.'); return; }
    const pkgs = entries
      .filter(e => e.reason.trim() && parseInt(e.count, 10) >= 0)
      .map(e => ({ reason: e.reason.trim(), count: parseInt(e.count, 10) }));
    if (pkgs.length === 0) { Alert.alert('Required', 'Add at least one RTS entry (can be 0 count).'); return; }
    setSaving(true);
    try {
      await apiClient.post('/shift-ops/rts-report', {
        driver_id: employeeId, date: localToday(),
        crew_confirmed: cc, rts_packages: pkgs,
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not submit departure request. Try again.')); }
    finally { setSaving(false); }
  };

  const statusLabel = rts?.status === 'rts_approved' || rts?.status === 'approved' ? 'Approved by dispatch'
    : rts?.status === 'rejected' ? 'Rejected — contact dispatch'
    : 'Pending dispatch review';

  if (done && rts) {
    return (
      <Card c={c}>
        <SectionHeader num="14" title="Departure Request" done doneLabel={statusLabel} c={c} />
        <View style={{ backgroundColor: rts.status === 'rts_approved' || rts.status === 'approved' ? c.success + '12' : rts.status === 'rejected' ? c.danger + '12' : c.warning + '12',
          borderRadius: radius.md, padding: spacing.md, borderWidth: 1,
          borderColor: rts.status === 'rts_approved' || rts.status === 'approved' ? c.success + '40' : rts.status === 'rejected' ? c.danger + '40' : c.warning + '40' }}>
          <Text style={{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold,
            color: rts.status === 'rts_approved' || rts.status === 'approved' ? c.success : rts.status === 'rejected' ? c.danger : c.warning }}>
            {statusLabel}
          </Text>
          {rts.dispatch_notes ? <Text style={{ fontSize: fontSize.xs, color: c.foreground, marginTop: 4 }}>{rts.dispatch_notes}</Text> : null}
        </View>
      </Card>
    );
  }
  return (
    <Card c={c}>
      <SectionHeader num="14" title="Departure Request — RTS Report"
        subtitle="All walkers returned and all packages attempted. Submit RTS groupings for dispatch review." c={c} />
      {unconfirmed > 0 && (
        <View style={{ backgroundColor: c.warning + '12', borderWidth: 1, borderColor: c.warning + '40',
          borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.md }}>
          <Text style={{ fontSize: fontSize.xs, color: c.warning, fontWeight: fontWeight.semibold }}>
            {unconfirmed} walker handoff{unconfirmed === 1 ? '' : 's'} not confirmed yet — confirm them above so these counts are trustworthy.
          </Text>
        </View>
      )}
      {prefilled && (
        <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.sm }}>
          Prefilled from your walkers' recorded RTS packages — adjust if the physical count differs.
        </Text>
      )}
      <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
        fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.md }}
        value={crewCount} onChangeText={setCrewCount}
        placeholder="Crew members confirmed on truck" keyboardType="numeric"
        placeholderTextColor={c.mutedForeground} />
      <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground,
        textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: spacing.sm }}>
        RTS Packages by Reason
      </Text>
      {entries.map((e, i) => (
        <View key={i} style={{ flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xs, alignItems: 'center' }}>
          <View style={{ flex: 1 }}>
            <TouchableOpacity onPress={() => {
              Alert.alert('Select Reason', '', RTS_REASONS.map(r => ({
                text: r, onPress: () => setReason(i, r),
              })));
            }} style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.sm,
              padding: spacing.sm, backgroundColor: c.background }}>
              <Text style={{ fontSize: fontSize.sm, color: e.reason ? c.foreground : c.mutedForeground }}>
                {e.reason || 'Select reason…'}
              </Text>
            </TouchableOpacity>
          </View>
          <TextInput style={{ width: 56, borderWidth: 1, borderColor: c.border, borderRadius: radius.sm,
            padding: spacing.sm, fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background,
            textAlign: 'center' }}
            value={e.count} onChangeText={v => setCount(i, v)} placeholder="0" keyboardType="numeric"
            placeholderTextColor={c.mutedForeground} />
          {entries.length > 1 && (
            <TouchableOpacity onPress={() => removeEntry(i)}>
              <Text style={{ fontSize: 18, color: c.danger, paddingHorizontal: 4 }}>×</Text>
            </TouchableOpacity>
          )}
        </View>
      ))}
      <Btn label="+ Add Reason" onPress={addEntry} variant="ghost" c={c} />
      <View style={{ marginTop: spacing.sm }}>
        <Btn label="Submit Departure Request" onPress={submit} disabled={!crewCount || entries.every(e => !e.reason)} loading={saving} c={c} />
      </View>
    </Card>
  );
}

function StepStationReturn({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const done = shift.stationReturnArrived;
  const [acting, setActing] = useState(false);
  const act = async () => {
    setActing(true);
    try {
      await apiClient.post('/field-ops/station-arrival', {
        employee_id: employeeId, date: localToday(), arrival_type: 'return',
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not record station return. Try again.')); }
    finally { setActing(false); }
  };
  if (done) {
    return <CompletedRow num="15" title="Station Return" summary={`Arrived ${fmtTime(shift.stationReturnAt)}`} c={c} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="15" title="Arrive at Station — Return"
        subtitle="Record your return to the station with RTS packages and totes." c={c} />
      <Btn label="Record Station Return" onPress={act} loading={acting} c={c} />
    </Card>
  );
}

function StepStationHandoff({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const done = shift.stationHandoff;
  // Prefill from what the system already knows: roster tote count and the
  // approved RTS report total. Driver corrects to the physical count.
  const [totes,  setTotes]  = useState(shift.roster ? String(shift.roster.tote_count) : '');
  const [rtsN,   setRtsN]   = useState(shift.rtsReport ? String(shift.rtsReport.total_rts) : '');
  const [notes,  setNotes]  = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const t = parseInt(totes, 10), r = parseInt(rtsN, 10);
    if (isNaN(t) || t < 0 || isNaN(r) || r < 0) { Alert.alert('Invalid', 'Enter tote and RTS counts.'); return; }
    setSaving(true);
    try {
      await apiClient.post('/shift-ops/station-handoff', {
        driver_id: employeeId, date: localToday(),
        totes_returned: t, rts_count: r, notes: notes.trim() || null,
      });
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not submit station handoff. Try again.')); }
    finally { setSaving(false); }
  };

  if (done) {
    return <CompletedRow num="16" title="Station Handoff" summary="Handoff complete" c={c} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="16" title="Station Handoff"
        subtitle="Hand off totes, RTS packages, and phones. Put phones to charge, do a light truck clean." c={c} />
      <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.sm }}>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: 4 }}>Totes returned</Text>
          <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
            fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background }}
            value={totes} onChangeText={setTotes} placeholder="0" keyboardType="numeric"
            placeholderTextColor={c.mutedForeground} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: 4 }}>RTS packages</Text>
          <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
            fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background }}
            value={rtsN} onChangeText={setRtsN} placeholder="0" keyboardType="numeric"
            placeholderTextColor={c.mutedForeground} />
        </View>
      </View>
      <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
        fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background,
        minHeight: 52, textAlignVertical: 'top', marginBottom: spacing.sm }}
        value={notes} onChangeText={setNotes} placeholder="Notes (optional)…"
        placeholderTextColor={c.mutedForeground} multiline />
      <Btn label="Submit Handoff" onPress={submit} disabled={!totes || !rtsN} loading={saving} c={c} />
    </Card>
  );
}

function StepEndOdometer({ employeeId, shift, walkers, drafts, submittedRatings, onDone, c }: {
  employeeId: string; shift: ShiftState; walkers: CrewMember[];
  drafts: Record<string, WalkerDraft>; submittedRatings: Record<string, boolean>;
  onDone: () => void; c: ThemeColors;
}) {
  const done = shift.fuelLog?.odometer_end != null;
  const [unit,   setUnit]   = useState<Unit>('imperial');
  const [endOdo, setEndOdo] = useState('');
  const [fuel,   setFuel]   = useState('');
  const [notes,  setNotes]  = useState('');
  const [saving, setSaving] = useState(false);
  const log = shift.fuelLog;
  const distU = unit === 'metric' ? 'km' : 'mi';
  const fuelU = unit === 'metric' ? 'L'  : 'gal';

  const pendingRatings = walkers.filter(w => !submittedRatings[w.id] && (drafts[w.id]?.stars ?? 0) > 0);

  const submit = async () => {
    if (!log) return;
    const endMi = toMi(parseFloat(endOdo), unit);
    if (isNaN(endMi) || endMi < log.odometer_start) {
      Alert.alert('Invalid', `End odometer must be ≥ start (${toDisp(log.odometer_start, unit)} ${distU}).`); return;
    }
    setSaving(true);
    try {
      // Flush pending walker rating drafts first
      for (const w of pendingRatings) {
        const d = drafts[w.id];
        await apiClient.post('/field-ops/rating', {
          driver_id: employeeId, walker_id: w.id, date: localToday(),
          present: true, stars: d.stars, comment: d.comment || null,
        }).catch(() => {});
      }
      // Log end odometer
      await apiClient.patch(`/field-ops/fuel-log/${employeeId}`, {
        odometer_end: endMi,
        fuel_added: fuel ? fToGal(+fuel, unit) : null,
        notes: notes.trim() || null,
      });
      // Clear drafts from storage
      await AsyncStorage.removeItem(`asheflow_walker_drafts_${employeeId}_${localToday()}`);
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not log end odometer. Try again.')); }
    finally { setSaving(false); }
  };

  const displayStart = log ? toDisp(log.odometer_start, unit) : null;
  const displayEnd   = log?.odometer_end != null ? toDisp(log.odometer_end, unit) : null;
  const displayDist  = displayStart != null && displayEnd != null ? +(displayEnd - displayStart).toFixed(1) : null;
  const displayFuel  = log?.fuel_added != null ? fDisp(log.fuel_added, unit) : null;

  if (done) {
    return <CompletedRow num="17" title="End Odometer" c={c}
      summary={`${displayEnd} ${distU}${displayDist != null ? ` · ${displayDist} ${distU} driven` : ''}`} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="17" title="Log End Odometer"
        subtitle={`Record truck odometer on return.${pendingRatings.length > 0 ? ` Also submits ${pendingRatings.length} walker rating draft${pendingRatings.length !== 1 ? 's' : ''}.` : ''}`}
        c={c} />
      {log && (
        <>
          <View style={{ flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.sm }}>
            {(['imperial', 'metric'] as const).map(u => (
              <TouchableOpacity key={u} onPress={() => setUnit(u)}
                style={{ flex: 1, paddingVertical: spacing.xs, borderRadius: radius.sm, borderWidth: 1,
                  alignItems: 'center', backgroundColor: unit === u ? c.primary : 'transparent',
                  borderColor: unit === u ? c.primary : c.border }}>
                <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold,
                  color: unit === u ? '#fff' : c.mutedForeground }}>{u === 'imperial' ? 'mi / gal' : 'km / L'}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <View style={{ backgroundColor: c.surfaceMuted, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm }}>
            <Text style={{ fontSize: fontSize.xs, color: c.foreground }}>
              Start: <Text style={{ fontWeight: fontWeight.semibold }}>{displayStart} {distU}</Text>
            </Text>
          </View>
          {pendingRatings.length > 0 && (
            <View style={{ backgroundColor: c.info + '12', borderRadius: radius.md, borderWidth: 1,
              borderColor: c.info + '40', padding: spacing.sm, marginBottom: spacing.sm }}>
              <Text style={{ fontSize: fontSize.xs, color: c.info, fontWeight: fontWeight.semibold }}>
                {pendingRatings.length} walker rating{pendingRatings.length !== 1 ? 's' : ''} will be submitted with this
              </Text>
            </View>
          )}
          <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
            fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.xs }}
            value={endOdo} onChangeText={setEndOdo} placeholder={`End odometer (${distU})`}
            placeholderTextColor={c.mutedForeground} keyboardType="numeric" />
          <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
            fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background, marginBottom: spacing.xs }}
            value={fuel} onChangeText={setFuel} placeholder={`Fuel added (${fuelU}) — optional`}
            placeholderTextColor={c.mutedForeground} keyboardType="numeric" />
          <TextInput style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm,
            fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background,
            minHeight: 52, textAlignVertical: 'top', marginBottom: spacing.sm }}
            value={notes} onChangeText={setNotes} placeholder="Notes (optional)…"
            placeholderTextColor={c.mutedForeground} multiline />
          <Btn label="Log End Odometer" onPress={submit} disabled={!endOdo} loading={saving} c={c} />
        </>
      )}
    </Card>
  );
}

function StepSignOut({ employeeId, shift, onDone, c }: { employeeId: string; shift: ShiftState; onDone: () => void; c: ThemeColors }) {
  const done = shift.returned;
  const [acting, setActing] = useState(false);
  const act = async () => {
    setActing(true);
    try {
      await apiClient.post(`/field-ops/return/${employeeId}`, {});
      onDone();
    } catch (e: any) { Alert.alert('Error', errorText(e, 'Could not sign out. Try again.')); }
    finally { setActing(false); }
  };
  if (done) {
    return <CompletedRow num="19" title="Sign Out" summary={`Shift complete · ${fmtTime(shift.returnedAt)}`} c={c} />;
  }
  return (
    <Card c={c}>
      <SectionHeader num="19" title="Sign Out"
        subtitle="Park the truck, complete any cleanup, then sign out to close your shift." c={c} />
      <Btn label="Sign Out — End Shift" onPress={act} loading={acting} c={c} />
    </Card>
  );
}

function WalkerPerformanceView({ employeeId, c }: { employeeId: string; c: ThemeColors }) {
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const GRADE_COLOR: Record<string, string> = { A: c.success, B: c.info, C: c.warning, D: c.warning, F: c.danger };
  useEffect(() => {
    apiClient.get(`/field-ops/walker-profile/${employeeId}`)
      .then(r => setProfile(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, [employeeId]);
  if (loading) return <ActivityIndicator color={c.primary} style={{ marginTop: spacing.xl }} />;
  if (!profile || profile.total_shifts === 0) return (
    <Card c={c}>
      <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center', paddingVertical: spacing.md }}>No shift data yet.</Text>
    </Card>
  );
  return (
    <Card c={c}>
      <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginBottom: spacing.md }}>My Performance</Text>
      <View style={{ flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.md }}>
        {[
          { lbl: 'Grade',    val: profile.grade ?? '—', color: GRADE_COLOR[profile.grade] ?? c.foreground },
          { lbl: 'Presence', val: `${profile.presence_rate ?? '—'}%`, color: (profile.presence_rate ?? 100) < 80 ? c.danger : c.success },
          { lbl: 'Shifts',   val: profile.total_shifts, color: c.foreground },
          { lbl: 'No-shows', val: profile.no_show_count ?? 0, color: (profile.no_show_count ?? 0) >= 3 ? c.danger : c.foreground },
        ].map(({ lbl, val, color }) => (
          <View key={lbl} style={{ flex: 1, backgroundColor: c.surfaceMuted, borderRadius: radius.md,
            padding: spacing.sm, alignItems: 'center' }}>
            <Text style={{ fontSize: fontSize.lg, fontWeight: fontWeight.extrabold, color }}>{val}</Text>
            <Text style={{ fontSize: 10, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.5, textAlign: 'center' }}>{lbl}</Text>
          </View>
        ))}
      </View>
      {profile.ratings?.slice(0, 5).map((r: any, i: number) => (
        <View key={i} style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
          paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: c.border }}>
          <View>
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>{r.date}</Text>
            <Text style={{ fontSize: fontSize.xs, color: r.present ? c.success : c.danger, fontWeight: fontWeight.medium }}>
              {r.present ? 'Present' : 'No-show'}
            </Text>
          </View>
          {r.stars != null && <Text style={{ color: c.gold, fontWeight: fontWeight.bold }}>{r.stars}★</Text>}
        </View>
      ))}
    </Card>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = (c: ThemeColors) => StyleSheet.create({
  safe:               { flex: 1, backgroundColor: c.background },
  scroll:             { flex: 1 },
  content:            { padding: spacing.lg, paddingBottom: 100 },
  center:             { flex: 1, justifyContent: 'center', alignItems: 'center' },
  screenHeader:       {
    flexDirection: 'row', alignItems: 'center',
    marginBottom: spacing.lg,
    paddingTop: spacing.xs,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.border,
    paddingBottom: spacing.sm,
    marginHorizontal: -spacing.lg, paddingHorizontal: spacing.md,
  },
  screenHeaderCenter: { flex: 1, alignItems: 'center' },
  backBtn:            { width: 44, alignItems: 'center' },
  backChevron:        { fontSize: 30, lineHeight: 32, fontWeight: '300' },
  pageTitle:          { fontSize: fontSize.xl, fontWeight: fontWeight.extrabold, color: c.foreground },
  subtitle:           { fontSize: fontSize.xs, color: c.mutedForeground },
  stepBadge:          { width: 44, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderRadius: radius.sm, paddingVertical: 3 },
  stepBadgeText:      { fontSize: 11, fontWeight: fontWeight.bold },
  // Wizard (paged step flow)
  dotRow:             { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 6, paddingVertical: spacing.sm },
  dot:                { width: 9, height: 9, borderRadius: 999 },
  dotCurrent:         { width: 22, borderRadius: 5 },
  wizHeader:          { flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.xs, marginBottom: spacing.xs },
  wizBack:            { width: 40, alignItems: 'center' },
  wizBackArrow:       { fontSize: 26, fontWeight: fontWeight.bold, lineHeight: 28 },
  wizSection:         { fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 0.8 },
  wizCount:           { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, marginTop: 1 },
});
