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
 *
 * ADR-511: the door form is three steps, every answer is kept in AsyncStorage
 * until the door is saved, back (Android hardware, the header chevron) steps
 * back through the form rather than leaving the walk, and changes of layout
 * animate natively unless the OS asks for reduced motion.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import { createNativeStackNavigator, type NativeStackScreenProps } from '@react-navigation/native-stack';
import { useFocusEffect } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import ScreenShell from '@components/ui/ScreenShell';
import { Button, Chip, tick, MIN_TARGET } from '@components/ui/primitives';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { useAuth } from '@contexts/AuthContext';
import { useLayoutTransition } from '@hooks/useLayoutTransition';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── shapes (mirror backend/app/routers/survey_register.py) ──────────────────

type Neighbour = { address: string; bin: string | null };
type Address = { index: number; address: string; bin: string | null;
                 sides?: string[]; neighbours?: Neighbour[] };   // ADR-504 D8
type Block = { block_key: string; street: string; description: string; addresses: Address[] };
type Walk = { id: string; street: string; closed_at: string | null; addresses: Address[]; recorded: number[] };
type Point = { lat: number; lng: number };

// The server's building types (app/schemas/building_taxonomy.py), commercial
// first: 84% of surveyed doors so far were commercial. Shown in two labelled
// groups, as on web (ADR-511 D4).
const COMMERCIAL: { value: string; label: string }[] = [
  { value: 'freight', label: 'Freight' },
  { value: 'loading_dock', label: 'Loading dock / service entrance' },
  { value: 'loading_dock_mailroom', label: 'Loading dock: mailroom' },
  { value: 'storefront_reception', label: 'Store front: receptionist' },
  { value: 'storefront_front_door', label: 'Store front: front door' },
];
const RESIDENTIAL: { value: string; label: string }[] = [
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
// ADR-511 D1: grouped by when the answers are learned.
const STEPS = ['The building', 'Deliveries', 'Hours and note'] as const;

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

// ── walk (form version 2, ADR-504 D8) ──────────────────────────────────────

type Tri = 'yes' | 'no' | 'unknown';
type DayStatus = 'open' | 'closed' | 'unknown';
type Day = { status: DayStatus; open: string; close: string };
type DPoint = { point: string; side: string; floor: string; which: string };
type Form = {
  source: string; building_type: string; points: DPoint[]; receives_for: number[];
  security_desk: Tri; sign_in_required: Tri; delivery_mode: string | null; floors: string;
  weekday: Day; saturday: Day; sunday: Day; note: string;
};
const TRI = [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }, { value: 'unknown', label: "Didn't find out" }];
const DAY = [{ value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' }, { value: 'unknown', label: "Didn't find out" }];
// [D] freight was each-unit 9 of 9; dock/mailroom one drop point 7 of 7.
const MODE_FOR_TYPE: Record<string, string> = {
  freight: 'each_unit', elevator: 'each_unit', walkup: 'each_unit', doorman_reception: 'each_unit',
  public_housing: 'each_unit', loading_dock: 'one_drop_point', loading_dock_mailroom: 'one_drop_point',
  mailroom: 'one_drop_point', lockers: 'one_drop_point',
};
const unknownDay: Day = { status: 'unknown', open: '', close: '' };
const blankFor = (a: Address): Form => ({
  source: 'observed', building_type: '',
  points: [{ point: 'main_entrance', side: a.sides?.[0] ?? '', floor: '', which: '' }],
  receives_for: [], security_desk: 'unknown', sign_in_required: 'unknown', delivery_mode: null,
  floors: '', weekday: unknownDay, saturday: unknownDay, sunday: unknownDay, note: '',
});

function Pick({ options, value, onChange, clearable = true }: {
  options: { value: string; label: string }[]; value: string | null;
  onChange: (v: string | null) => void; clearable?: boolean;
}) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
      {options.map(o => (
        <Chip key={o.value} label={o.label} selected={value === o.value}
          onPress={() => onChange(value === o.value && clearable ? null : o.value)} />
      ))}
    </View>
  );
}

// ── drafts (ADR-511 D2) ─────────────────────────────────────────────────────
// Kept on this phone until the door is saved. A failed read or write keeps
// nothing and the form still works.
type Draft = { form: Form; step: number };
const DRAFT_PREFIX = 'survey-draft:';
const draftKey = (walkId: string, index: number) => `${DRAFT_PREFIX}${walkId}:${index}`;
const dropDraft = (walkId: string, index: number) =>
  AsyncStorage.removeItem(draftKey(walkId, index)).catch(() => {});
async function draftDoors(walkId: string): Promise<Set<number>> {
  try {
    const prefix = `${DRAFT_PREFIX}${walkId}:`;
    return new Set((await AsyncStorage.getAllKeys())
      .filter(k => k.startsWith(prefix)).map(k => Number(k.slice(prefix.length))));
  } catch { return new Set(); }
}

function SurveyWalkScreen({ route, navigation }: NativeStackScreenProps<StackParams, 'SurveyWalk'>) {
  const c = useColors();
  const s = styles(c);
  const animate = useLayoutTransition();
  const { walkId } = route.params;
  const [walk, setWalk] = useState<Walk | null>(null);
  const [door, setDoor] = useState<Address | null>(null);
  const [f, setF] = useState<Form | null>(null);
  const [step, setStep] = useState(0);
  const [drafts, setDrafts] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setWalk((await apiClient.get<Walk>(`/survey/walks/${walkId}`)).data); }
    catch (e) { Alert.alert("Couldn't load this walk", errorText(e, 'Try again.')); }
    setDrafts(await draftDoors(walkId));
  }, [walkId]);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  // D2: every change is kept. A door opened and left untouched is not a draft.
  useEffect(() => {
    if (!door || !f) return;
    const untouched = step === 0 && JSON.stringify(f) === JSON.stringify(blankFor(door));
    const key = draftKey(walkId, door.index);
    (untouched ? AsyncStorage.removeItem(key)
      : AsyncStorage.setItem(key, JSON.stringify({ form: f, step } satisfies Draft))).catch(() => {});
  }, [walkId, door, f, step]);

  const closeDoor = useCallback(() => {
    animate();
    setDoor(null);
    setF(null);
    void draftDoors(walkId).then(setDrafts);
  }, [animate, walkId]);
  const goTo = useCallback((n: number) => { animate(); setStep(n); }, [animate]);

  // D6: while a door is open, back steps back through the form, then to the
  // door list. It never leaves the walk. iOS swipe-back cannot be cancelled
  // halfway, so it is off while a door is open.
  useEffect(() => {
    navigation.setOptions({ gestureEnabled: door === null });
    if (!door) return;
    return navigation.addListener('beforeRemove', e => {
      e.preventDefault();
      if (step > 0) goTo(step - 1); else closeDoor();
    });
  }, [navigation, door, step, goTo, closeDoor]);

  const openDoor = async (a: Address) => {
    tick();
    let d: Draft | null = null;
    try {
      const raw = await AsyncStorage.getItem(draftKey(walkId, a.index));
      const parsed = raw ? JSON.parse(raw) as Draft : null;
      // A draft from an older form shape is not restored.
      d = parsed && Array.isArray(parsed.form?.points) ? parsed : null;
    } catch { d = null; }
    animate();
    setDoor(a);
    setF(d?.form ?? blankFor(a));
    setStep(d ? Math.min(Math.max(d.step, 0), STEPS.length - 1) : 0);
  };

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF(p => (p ? { ...p, [k]: v } : p));
  const setPoint = (i: number, v: Partial<DPoint>) =>
    setF(p => (p ? { ...p, points: p.points.map((x, j) => (j === i ? { ...x, ...v } : x)) } : p));

  const post = async (index: number, body: Record<string, unknown>) => {
    setBusy(true);
    try {
      await apiClient.post(`/survey/walks/${walkId}/observations`, body);
      tick();
      await dropDraft(walkId, index);
      closeDoor();
      await load();
    } catch (e) {
      Alert.alert("Couldn't save this door", errorText(e, 'Try again.'));
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (!door || !f) return;
    const day = (d: Day, label: string) => {
      if (d.status !== 'open') return { status: d.status };
      if (!HHMM.test(d.open) || !HHMM.test(d.close)) {
        throw new Error(`${label}: add both times like 08:30, or choose "Didn't find out".`);
      }
      return { status: 'open', open: d.open, close: d.close };
    };
    let hours;
    try {
      hours = { weekday: day(f.weekday, 'Weekdays'), saturday: day(f.saturday, 'Saturday'), sunday: day(f.sunday, 'Sunday') };
    } catch (e) {
      Alert.alert('Check the hours', (e as Error).message);
      return;
    }
    void post(door.index, {
      address_index: door.index, source: f.source, building_type: f.building_type,
      delivery_points: f.points.map(p => ({
        point: p.point, side: p.side.trim() || null, floor: p.floor ? Number(p.floor) : null,
        which_packages: f.points.length > 1 ? (p.which.trim() || null) : null,
      })),
      receives_for: f.receives_for, security_desk: f.security_desk, sign_in_required: f.sign_in_required,
      delivery_mode: f.delivery_mode, floors: f.floors ? Number(f.floors) : null,
      ...hours, note: f.note.trim() || null,
    });
  };

  const notADoor = (a: Address) => Alert.alert(
    'Not a delivery point?', `${a.address} will be recorded as not a delivery point (for example a gate or a second entrance).`,
    [{ text: 'Cancel', style: 'cancel' },
     { text: 'Record it', onPress: () => void post(a.index, { address_index: a.index, source: 'observed', not_a_delivery_point: true }) }],
  );

  const finish = () => Alert.alert('Finish this walk?', 'You can start a new walk to re-visit later.', [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Finish', onPress: async () => {
      try {
        await apiClient.post(`/survey/walks/${walkId}/close`);
        await Promise.all([...(await draftDoors(walkId))].map(i => dropDraft(walkId, i)));
        navigation.goBack();
      } catch (e) { Alert.alert("Couldn't finish", errorText(e, 'Try again.')); }
    } },
  ]);

  if (!walk) return <ScreenShell title="Walk" loading>{null}</ScreenShell>;
  const done = new Set(walk.recorded);

  if (door && f) {
    const sides = door.sides?.length ? door.sides : [door.address.split(' ').slice(1).join(' ')];
    const neighbours = door.neighbours ?? [];
    const last = step === STEPS.length - 1;
    const blocked = step === 0 && !f.building_type ? 'Choose a building type to go on.' : null;
    const typePick = (options: { value: string; label: string }[]) => (
      <Pick options={options} value={f.building_type || null}
        onChange={v => setF(p => (p ? { ...p, building_type: v ?? '',
          delivery_mode: p.delivery_mode ?? (v ? MODE_FOR_TYPE[v] ?? null : null) } : p))} />
    );
    const dayRow = (k: 'weekday' | 'saturday' | 'sunday', label: string) => (
      <View style={s.sub}>
        <View style={s.subHead}>
          <Text style={s.body}>{label}</Text>
          {k !== 'weekday' && (
            <TouchableOpacity onPress={() => { tick(); set(k, { ...f.weekday }); }} accessibilityRole="button"
              style={s.textAction}>
              <Text style={s.link}>Same as weekdays</Text>
            </TouchableOpacity>
          )}
        </View>
        <Pick options={DAY} value={f[k].status} clearable={false}
          onChange={v => { animate(); set(k, { ...f[k], status: (v ?? 'unknown') as DayStatus }); }} />
        {f[k].status === 'open' && (
          <View style={{ flexDirection: 'row', gap: spacing.sm }}>
            <TextInput value={f[k].open} onChangeText={v => set(k, { ...f[k], open: v })} maxLength={5}
              placeholder="08:00" keyboardType="numbers-and-punctuation" placeholderTextColor={c.placeholder}
              style={[s.input, { flex: 1 }]} accessibilityLabel={`${label} opens`} />
            <TextInput value={f[k].close} onChangeText={v => set(k, { ...f[k], close: v })} maxLength={5}
              placeholder="17:00" keyboardType="numbers-and-punctuation" placeholderTextColor={c.placeholder}
              style={[s.input, { flex: 1 }]} accessibilityLabel={`${label} closes`} />
          </View>
        )}
      </View>
    );
    return (
      <ScreenShell title={door.address} subtitle={`Step ${step + 1} of ${STEPS.length} · ${STEPS[step]}`}
        onBack={() => (step > 0 ? goTo(step - 1) : closeDoor())} keyboardInsets>
        <View style={s.progress} accessible={false}>
          {STEPS.map((_, i) => <View key={i} style={[s.progressSeg, i <= step && s.progressOn]} />)}
        </View>
        <Text style={[s.muted, { marginBottom: spacing.md }]}>Your answers are kept on this phone until you save.</Text>

        {step === 0 && (<>
          <View style={s.card}>
            <Text style={s.h2}>Where did this come from?</Text>
            <Pick options={SOURCES} value={f.source} clearable={false} onChange={v => set('source', v ?? 'observed')} />
            <Text style={s.muted}>The role that answered, never the person's name.</Text>
          </View>
          <View style={s.card}>
            <Text style={s.h2}>Building type</Text>
            <Text style={s.groupLabel}>Commercial</Text>
            {typePick(COMMERCIAL)}
            <Text style={s.groupLabel}>Residential</Text>
            {typePick(RESIDENTIAL)}
          </View>
          <View style={s.card}>
            <Text style={s.h2}>Each unit, or one drop point?</Text>
            <Pick options={[{ value: 'each_unit', label: 'Each unit' }, { value: 'one_drop_point', label: 'One drop point' }]}
              value={f.delivery_mode} onChange={v => set('delivery_mode', v)} />
            <TextInput value={f.floors} onChangeText={v => set('floors', v.replace(/\D/g, '').slice(0, 3))}
              keyboardType="number-pad" placeholder="Floors" placeholderTextColor={c.placeholder} style={s.input}
              accessibilityLabel="Number of floors" />
          </View>
        </>)}

        {step === 1 && (<>
          <View style={s.card}>
            <Text style={s.h2}>Deliveries go to</Text>
            {f.points.map((p, i) => (
              <View key={i} style={s.sub}>
                <View style={s.subHead}>
                  <Text style={s.muted}>Point {i + 1}</Text>
                  {f.points.length > 1 && (
                    <TouchableOpacity style={s.textAction} accessibilityRole="button" accessibilityLabel={`Remove point ${i + 1}`}
                      onPress={() => { animate(); set('points', f.points.filter((_, j) => j !== i)); }}>
                      <Text style={s.link}>Remove</Text>
                    </TouchableOpacity>
                  )}
                </View>
                <Pick options={POINTS} value={p.point} clearable={false} onChange={v => setPoint(i, { point: v ?? p.point })} />
                <Text style={s.muted}>Which side</Text>
                <Pick options={sides.map(sd => ({ value: sd, label: sd }))} value={sides.includes(p.side) ? p.side : null}
                  onChange={v => setPoint(i, { side: v ?? '' })} />
                <TextInput value={sides.includes(p.side) ? '' : p.side} onChangeText={v => setPoint(i, { side: v })}
                  maxLength={120} placeholder="Or describe it, e.g. rear via the alley"
                  placeholderTextColor={c.placeholder} style={s.input} accessibilityLabel="Describe the side" />
                <View style={{ flexDirection: 'row', gap: spacing.sm }}>
                  <TextInput value={p.floor} onChangeText={v => setPoint(i, { floor: v.replace(/[^\d-]/g, '').slice(0, 4) })}
                    keyboardType="numbers-and-punctuation" placeholder="Floor" placeholderTextColor={c.placeholder}
                    style={[s.input, { width: 80 }]} accessibilityLabel="Floor" />
                  {f.points.length > 1 && (
                    <TextInput value={p.which} onChangeText={v => setPoint(i, { which: v })} maxLength={120}
                      placeholder="Which packages?" placeholderTextColor={c.placeholder}
                      style={[s.input, { flex: 1 }]} accessibilityLabel="Which packages go here" />
                  )}
                </View>
              </View>
            ))}
            {f.points.length < 3 && (
              <Button variant="ghost" onPress={() => {
                animate();
                set('points', [...f.points, { point: 'main_entrance', side: sides[0], floor: '', which: '' }]);
              }}>
                Add another delivery point
              </Button>
            )}
          </View>
          {neighbours.length > 0 && (
            <View style={s.card}>
              <Text style={s.h2}>Also receives for</Text>
              <Text style={s.muted}>Other doors on this city block whose packages go here.</Text>
              {neighbours.map((n, i) => (
                <View key={n.address} style={s.switchRow}>
                  <Text style={[s.body, { flex: 1 }]}>{n.address}</Text>
                  <Switch value={f.receives_for.includes(i)} accessibilityLabel={`Also receives for ${n.address}`}
                    onValueChange={on => { tick(); set('receives_for', on ? [...f.receives_for, i] : f.receives_for.filter(x => x !== i)); }} />
                </View>
              ))}
            </View>
          )}
          <View style={s.card}>
            <Text style={s.h2}>Security desk</Text>
            <Pick options={TRI} value={f.security_desk} clearable={false} onChange={v => set('security_desk', (v ?? 'unknown') as Tri)} />
            <Text style={s.h2}>Sign-in required</Text>
            <Pick options={TRI} value={f.sign_in_required} clearable={false} onChange={v => set('sign_in_required', (v ?? 'unknown') as Tri)} />
          </View>
        </>)}

        {step === 2 && (<>
          <View style={s.card}>
            <Text style={s.h2}>Receiving hours</Text>
            {dayRow('weekday', 'Weekdays')}
            {dayRow('saturday', 'Saturday')}
            {dayRow('sunday', 'Sunday')}
          </View>
          <View style={s.card}>
            <Text style={s.h2}>Note</Text>
            <TextInput value={f.note} onChangeText={v => set('note', v)} maxLength={500} multiline
              style={[s.input, { minHeight: 80 }]} accessibilityLabel="Note" />
            <Text style={s.muted}>Building facts only. No door or gate codes, no names, no security details.</Text>
          </View>
        </>)}

        {blocked && <Text style={[s.muted, { textAlign: 'center', marginBottom: spacing.sm }]}>{blocked}</Text>}
        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          {step > 0 && (
            <View style={{ flex: 1 }}>
              <Button variant="secondary" onPress={() => goTo(step - 1)} disabled={busy} fullWidth>Back</Button>
            </View>
          )}
          <View style={{ flex: 2 }}>
            {last
              ? <Button onPress={save} loading={busy} fullWidth>Save this door</Button>
              : <Button onPress={() => goTo(step + 1)} disabled={blocked !== null} fullWidth>
                  {`Next: ${STEPS[step + 1]}`}
                </Button>}
          </View>
        </View>
      </ScreenShell>
    );
  }

  return (
    <ScreenShell title={walk.street} subtitle={`${done.size} of ${walk.addresses.length} doors recorded`}
      onRefresh={() => void load()}>
      {walk.addresses.map(a => (
        <View key={a.index} style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
          <TouchableOpacity style={[s.row, { flex: 1 }, done.has(a.index) && { opacity: 0.5 }]}
            disabled={!!walk.closed_at || done.has(a.index)} accessibilityRole="button"
            accessibilityHint={drafts.has(a.index) ? 'Has a draft' : undefined}
            onPress={() => void openDoor(a)}>
            <Text style={[s.body, { flex: 1 }]}>{a.address}</Text>
            {done.has(a.index) ? <Text style={s.muted}>Recorded</Text>
              : drafts.has(a.index) && <Text style={s.draft}>Draft</Text>}
          </TouchableOpacity>
          {!walk.closed_at && !done.has(a.index) && (
            <TouchableOpacity onPress={() => notADoor(a)} accessibilityRole="button"
              accessibilityLabel={`${a.address} is not a delivery point`} style={s.notDoor}>
              <Text style={s.link}>Not a door</Text>
            </TouchableOpacity>
          )}
        </View>
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
  sub: { gap: spacing.sm, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: c.border },
  subHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  // ADR-511 D3: a text action still gets a full-size target.
  textAction: { minHeight: MIN_TARGET, justifyContent: 'center', paddingHorizontal: spacing.sm },
  groupLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground,
                textTransform: 'uppercase', letterSpacing: 0.5 },
  draft: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.warning },
  progress: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.sm },
  progressSeg: { flex: 1, height: 6, borderRadius: radius.full, backgroundColor: c.surfaceMuted },
  progressOn: { backgroundColor: c.primary },
  link: { fontSize: fontSize.xs, color: c.primary, fontWeight: fontWeight.semibold },
  notDoor: { minHeight: MIN_TARGET, justifyContent: 'center', paddingHorizontal: spacing.sm, marginBottom: spacing.sm },
  input: { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.md,
           paddingVertical: spacing.sm, fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.background },
});
