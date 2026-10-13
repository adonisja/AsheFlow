/**
 * The survey register on mobile (ADR-504): start a walk, then record its doors.
 *
 * Shown INSTEAD of the tab shell to accounts with no Employee row (surveyors and
 * the platform owner): every tab there calls employee endpoints they cannot use.
 *
 * Blocks are found from a typed address. GPS needs a native location module this
 * app does not have yet; adding one is a native dependency (pod install, rebuild),
 * so it is a separate step. The typed path is the plain fallback that always works.
 *
 * Field order and choices match the web form (pages/survey/SurveyWalk.tsx), which
 * follows the 2026-10-13 usage analysis of the old collection form.
 */
import React, { useCallback, useState } from 'react';
import {
  Alert, ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import { createNativeStackNavigator, type NativeStackScreenProps } from '@react-navigation/native-stack';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import { Button, Chip, tick, MIN_TARGET } from '@components/ui/primitives';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { useAuth } from '@contexts/AuthContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── shapes (mirror backend/app/routers/survey_register.py) ──────────────────

type Address = { index: number; address: string; bin: string | null };
type Block = { block_key: string; street: string; description: string; addresses: Address[] };
type Walk = { id: string; street: string; closed_at: string | null; addresses: Address[]; recorded: number[] };
type Point = { lat: number; lng: number };

// The server's building types (app/schemas/building_taxonomy.py), commercial
// first: 84% of surveyed doors so far were commercial.
const TYPES: { value: string; label: string }[] = [
  { value: 'freight', label: 'Freight' },
  { value: 'loading_dock', label: 'Loading dock / service entrance' },
  { value: 'loading_dock_mailroom', label: 'Loading dock: mailroom' },
  { value: 'storefront_reception', label: 'Store front: receptionist' },
  { value: 'storefront_front_door', label: 'Store front: front door' },
  { value: 'walkup', label: 'Walk-up' },
  { value: 'elevator', label: 'Elevator' },
  { value: 'doorman_reception', label: 'Doorman / Reception' },
  { value: 'mailroom', label: 'Mailroom' },
  { value: 'lockers', label: 'Lockers' },
  { value: 'public_housing', label: 'Public housing' },
];
const SOURCES = [
  { value: 'observed', label: 'I saw it' }, { value: 'front_desk', label: 'Front desk' },
  { value: 'mailroom', label: 'Mailroom' }, { value: 'security', label: 'Security' },
];
const POINTS = [
  { value: 'main_entrance', label: 'Main entrance' }, { value: 'service_entrance', label: 'Service entrance' },
  { value: 'loading_dock', label: 'Loading dock' }, { value: 'mailroom', label: 'Mailroom' },
  { value: 'front_desk', label: 'Front desk' },
];
const CONFIRMATIONS = [
  { key: 'attest_off_shift', label: "I'm off-shift. I'm not on any route or block for any carrier." },
  { key: 'attest_unbranded', label: 'No branded van, uniform, work phone or delivery app.' },
  { key: 'attest_as_self', label: "I'm asking as myself, not as a delivery driver." },
] as const;
type ConfirmKey = typeof CONFIRMATIONS[number]['key'];

type StackParams = { SurveyStart: undefined; SurveyWalk: { walkId: string } };
const Stack = createNativeStackNavigator<StackParams>();

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

// ── start ───────────────────────────────────────────────────────────────────

function SurveyStartScreen({ navigation }: NativeStackScreenProps<StackParams, 'SurveyStart'>) {
  const c = useColors();
  const s = styles(c);
  const { signOut } = useAuth();
  const [confirmed, setConfirmed] = useState<Record<ConfirmKey, boolean>>({
    attest_off_shift: false, attest_unbranded: false, attest_as_self: false,
  });
  const all = Object.values(confirmed).every(Boolean);
  const [typed, setTyped] = useState('');
  const [point, setPoint] = useState<Point | null>(null);
  const [blocks, setBlocks] = useState<Block[] | null>(null);
  const [open, setOpen] = useState<Walk[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  useFocusEffect(useCallback(() => {
    apiClient.get<Walk[]>('/survey/walks', { params: { limit: 10 } })
      .then(r => setOpen(r.data.filter(w => !w.closed_at))).catch(() => {});
  }, []));

  const find = async () => {
    setBusy('find');
    try {
      const p = (await apiClient.get<Point>('/survey/locate', { params: { address: typed.trim() } })).data;
      setPoint(p);
      setBlocks((await apiClient.get<Block[]>('/survey/blocks', { params: { ...p, radius_m: 150 } })).data);
    } catch (e) {
      Alert.alert("Couldn't find blocks", errorText(e, 'Check the address and try again.'));
    } finally {
      setBusy(null);
    }
  };

  const start = async (b: Block) => {
    if (!point) return;
    setBusy(b.block_key);
    try {
      const { data } = await apiClient.post<Walk>('/survey/walks', {
        ...point, radius_m: 150, block_key: b.block_key, ...confirmed,
      });
      tick();
      navigation.navigate('SurveyWalk', { walkId: data.id });
    } catch (e) {
      Alert.alert("Couldn't start the walk", errorText(e, 'Try again.'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <ScreenShell title="Survey register" subtitle="Walk a block">
      {open.length > 0 && (
        <View style={s.card}>
          <Text style={s.h2}>Walks in progress</Text>
          {open.map(w => (
            <TouchableOpacity key={w.id} style={s.row} onPress={() => navigation.navigate('SurveyWalk', { walkId: w.id })}
              accessibilityRole="button">
              <Text style={s.body}>{w.street}</Text>
              <Text style={s.muted}>{w.recorded.length} of {w.addresses.length}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}

      <View style={s.card}>
        <Text style={s.h2}>1. Before you start</Text>
        {CONFIRMATIONS.map(k => (
          <View key={k.key} style={s.switchRow}>
            <Text style={[s.body, { flex: 1 }]}>{k.label}</Text>
            <Switch value={confirmed[k.key]} accessibilityLabel={k.label}
              onValueChange={v => { tick(); setConfirmed(p => ({ ...p, [k.key]: v })); }} />
          </View>
        ))}
      </View>

      <View style={[s.card, !all && { opacity: 0.5 }]}>
        <Text style={s.h2}>2. Find the block you're on</Text>
        <TextInput value={typed} onChangeText={setTyped} editable={all} maxLength={200}
          placeholder="An address on the block, e.g. 433 W 32 St" placeholderTextColor={c.placeholder}
          style={s.input} autoCapitalize="words" returnKeyType="search" onSubmitEditing={() => void find()} />
        <Button onPress={() => void find()} disabled={!all || typed.trim().length < 3} loading={busy === 'find'} fullWidth>
          Find blocks
        </Button>
      </View>

      {blocks && (
        <View style={s.card}>
          <Text style={s.h2}>3. Pick a block</Text>
          {blocks.length === 0 && <Text style={s.muted}>The city lists no addresses near there.</Text>}
          {blocks.map(b => (
            <TouchableOpacity key={b.block_key} style={s.row} disabled={busy !== null}
              onPress={() => void start(b)} accessibilityRole="button">
              <Text style={[s.body, { flex: 1 }]}>{b.description}</Text>
              <Text style={s.muted}>{busy === b.block_key ? 'Starting…' : `${b.addresses.length} doors`}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}

      <Button variant="ghost" onPress={() => void signOut()}>Sign out</Button>
    </ScreenShell>
  );
}

// ── walk ────────────────────────────────────────────────────────────────────

type Form = {
  source: string; building_type: string; delivery_point: string | null; entrance_side: string;
  security_desk: boolean | null; sign_in_required: boolean | null; delivery_mode: string | null;
  floors: string; opens_at: string; closes_at: string; note: string;
};
const blank: Form = {
  source: 'observed', building_type: '', delivery_point: null, entrance_side: '',
  security_desk: null, sign_in_required: null, delivery_mode: null,
  floors: '', opens_at: '', closes_at: '', note: '',
};

function Pick({ options, value, onChange }: {
  options: { value: string; label: string }[]; value: string | null; onChange: (v: string | null) => void;
}) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
      {options.map(o => (
        <Chip key={o.value} label={o.label} selected={value === o.value}
          onPress={() => onChange(value === o.value ? null : o.value)} />
      ))}
    </View>
  );
}

function SurveyWalkScreen({ route, navigation }: NativeStackScreenProps<StackParams, 'SurveyWalk'>) {
  const c = useColors();
  const s = styles(c);
  const { walkId } = route.params;
  const [walk, setWalk] = useState<Walk | null>(null);
  const [door, setDoor] = useState<Address | null>(null);
  const [f, setF] = useState<Form>(blank);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setWalk((await apiClient.get<Walk>(`/survey/walks/${walkId}`)).data); }
    catch (e) { Alert.alert("Couldn't load this walk", errorText(e, 'Try again.')); }
  }, [walkId]);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF(p => ({ ...p, [k]: v }));

  const save = async () => {
    if (!door) return;
    for (const [k, v] of [['opens_at', f.opens_at], ['closes_at', f.closes_at]] as const) {
      if (v && !HHMM.test(v)) { Alert.alert('Check the hours', `${k === 'opens_at' ? 'Opens' : 'Closes'} must be like 08:30.`); return; }
    }
    setBusy(true);
    try {
      await apiClient.post(`/survey/walks/${walkId}/observations`, {
        address_index: door.index, source: f.source, building_type: f.building_type,
        delivery_point: f.delivery_point, entrance_side: f.entrance_side.trim() || null,
        security_desk: f.security_desk, sign_in_required: f.sign_in_required,
        delivery_mode: f.delivery_mode, floors: f.floors ? Number(f.floors) : null,
        opens_at: f.opens_at || null, closes_at: f.closes_at || null, note: f.note.trim() || null,
      });
      tick();
      setDoor(null);
      setF(blank);
      await load();
    } catch (e) {
      Alert.alert("Couldn't save this door", errorText(e, 'Try again.'));
    } finally {
      setBusy(false);
    }
  };

  const finish = () => Alert.alert('Finish this walk?', 'You can start a new walk to re-visit later.', [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Finish', onPress: async () => {
      try { await apiClient.post(`/survey/walks/${walkId}/close`); navigation.goBack(); }
      catch (e) { Alert.alert("Couldn't finish", errorText(e, 'Try again.')); }
    } },
  ]);

  if (!walk) return <ScreenShell title="Walk" loading>{null}</ScreenShell>;
  const done = new Set(walk.recorded);

  if (door) {
    return (
      <ScreenShell title={door.address} subtitle={walk.street}>
        <View style={s.card}>
          <Text style={s.h2}>Where did this come from?</Text>
          <Pick options={SOURCES} value={f.source} onChange={v => set('source', v ?? 'observed')} />
          <Text style={s.muted}>The role that answered, never the person's name.</Text>
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Deliveries go to</Text>
          <Pick options={POINTS} value={f.delivery_point} onChange={v => set('delivery_point', v)} />
          <TextInput value={f.entrance_side} onChangeText={v => set('entrance_side', v)} maxLength={120}
            placeholder="Which side? e.g. on 33rd St" placeholderTextColor={c.placeholder} style={s.input} />
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Building type</Text>
          <Pick options={TYPES} value={f.building_type || null} onChange={v => set('building_type', v ?? '')} />
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Security desk</Text>
          <Pick options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]}
            value={f.security_desk === null ? null : f.security_desk ? 'yes' : 'no'}
            onChange={v => set('security_desk', v === null ? null : v === 'yes')} />
          <Text style={s.h2}>Sign-in required</Text>
          <Pick options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]}
            value={f.sign_in_required === null ? null : f.sign_in_required ? 'yes' : 'no'}
            onChange={v => set('sign_in_required', v === null ? null : v === 'yes')} />
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Each unit, or one drop point?</Text>
          <Pick options={[{ value: 'each_unit', label: 'Each unit' }, { value: 'one_drop_point', label: 'One drop point' }]}
            value={f.delivery_mode} onChange={v => set('delivery_mode', v)} />
          <TextInput value={f.floors} onChangeText={v => set('floors', v.replace(/\D/g, '').slice(0, 3))}
            keyboardType="number-pad" placeholder="Floors" placeholderTextColor={c.placeholder} style={s.input} />
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Receiving hours</Text>
          <View style={{ flexDirection: 'row', gap: spacing.sm }}>
            <TextInput value={f.opens_at} onChangeText={v => set('opens_at', v)} maxLength={5}
              placeholder="08:00" keyboardType="numbers-and-punctuation" placeholderTextColor={c.placeholder}
              style={[s.input, { flex: 1 }]} accessibilityLabel="Opens at" />
            <TextInput value={f.closes_at} onChangeText={v => set('closes_at', v)} maxLength={5}
              placeholder="17:00" keyboardType="numbers-and-punctuation" placeholderTextColor={c.placeholder}
              style={[s.input, { flex: 1 }]} accessibilityLabel="Closes at" />
          </View>
        </View>
        <View style={s.card}>
          <Text style={s.h2}>Note</Text>
          <TextInput value={f.note} onChangeText={v => set('note', v)} maxLength={500} multiline
            style={[s.input, { minHeight: 80 }]} accessibilityLabel="Note" />
          <Text style={s.muted}>Building facts only. No door or gate codes, no names, no security details.</Text>
        </View>
        <Button onPress={() => void save()} disabled={!f.building_type} loading={busy} fullWidth>Save this door</Button>
        <Button variant="ghost" onPress={() => { setDoor(null); setF(blank); }}>Back to doors</Button>
      </ScreenShell>
    );
  }

  return (
    <ScreenShell title={walk.street} subtitle={`${done.size} of ${walk.addresses.length} doors recorded`}
      onRefresh={() => void load()}>
      {walk.addresses.map(a => (
        <TouchableOpacity key={a.index} style={[s.row, done.has(a.index) && { opacity: 0.5 }]}
          disabled={!!walk.closed_at || done.has(a.index)} accessibilityRole="button"
          onPress={() => { tick(); setDoor(a); }}>
          <Text style={[s.body, { flex: 1 }]}>{a.address}</Text>
          {done.has(a.index) && <Text style={s.muted}>Recorded</Text>}
        </TouchableOpacity>
      ))}
      {!walk.closed_at && <Button variant="secondary" onPress={finish} fullWidth>Finish walk</Button>}
    </ScreenShell>
  );
}

export default function SurveyNavigator() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="SurveyStart" component={SurveyStartScreen} />
      <Stack.Screen name="SurveyWalk" component={SurveyWalkScreen} />
    </Stack.Navigator>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card: { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border,
          padding: spacing.md, marginBottom: spacing.md, gap: spacing.sm },
  h2: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground },
  body: { fontSize: fontSize.sm, color: c.foreground },
  muted: { fontSize: fontSize.xs, color: c.mutedForeground },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, minHeight: MIN_TARGET,
         paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.md,
         borderWidth: 1, borderColor: c.border, marginBottom: spacing.sm, backgroundColor: c.card },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, minHeight: MIN_TARGET },
  input: { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.md,
           paddingVertical: spacing.sm, fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background },
});
