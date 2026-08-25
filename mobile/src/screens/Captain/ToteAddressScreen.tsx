/**
 * Captain enters delivery addresses for the totes on the truck (ADR-291).
 *
 * In workforce mode there is no Amazon manifest, so this screen IS the sort's
 * input: a captain walks the truck, reads an address off a package in each
 * tote, and types it. Everything downstream — routes, walker assignment, the
 * day's returns — hangs off what is entered here.
 *
 * DESIGNED FOR A HAND IN A VAN, NOT A DESK.
 *
 * The bag id is sticky between submissions. A captain enters several addresses
 * for one tote before moving on, and clearing that field each time would mean
 * retyping "5270" three times while holding a package. The address field clears
 * and refocuses instead, so the natural rhythm is type-address, submit,
 * type-address — one field, one thumb.
 *
 * A tote whose addresses disagree on a block is surfaced immediately rather than
 * at sort time (ADR-291 D4). Either Amazon bagged loosely or someone mistyped,
 * and both are cheap to fix while standing at the tote and expensive to discover
 * as a bad route two hours later.
 *
 * Unaddressed totes from the BTR sheet (ADR-290) are listed as a countdown, so
 * "am I done?" is answerable without counting bags by memory.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, StyleSheet,
  Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Badge, Button, tick } from '@components/ui/primitives';
import { errorText } from '@api/errorText';

// ── Types (mirror the /workforce endpoints) ───────────────────────────────────

type ToteAddress = {
  id: string;
  bag_id: string;
  raw_address: string | null;
  normalised_address: string | null;
  block_key: string | null;
  entry_sequence: number;
  entered_by_name: string | null;
  geocoded: boolean;
};

type Disagreement = {
  bag_id: string;
  block_keys: string[];
  winning_block_key: string;
};

/** Mirrors ToteAddressListOut exactly — it carries no entry_date or truck_id,
 *  because the caller already supplied both in the request. */
type DayAddresses = {
  addresses: ToteAddress[];
  disagreements: Disagreement[];
  unaddressed_bags: string[];
};

type MyTruck = {
  truck_id: string | null;
  truck_name: string | null;
  no_truck_assigned: boolean;
};

type Props = {
  /** Optional override. Omitted when this renders as a tab, where the server
   *  resolves the caller's own truck — a captain is standing next to it. */
  truckId?: string;
  /** ISO date. Defaults to the device's today; the server is authoritative. */
  entryDate?: string;
  onDone?: () => void;
};

// ── Screen ────────────────────────────────────────────────────────────────────

export default function ToteAddressScreen({ truckId: truckIdProp, entryDate, onDone }: Props) {
  const c = useColors();
  const s = styles(c);

  const day = entryDate ?? new Date().toISOString().slice(0, 10);

  const [truck, setTruck] = useState<MyTruck | null>(null);
  const [data, setData] = useState<DayAddresses | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sticky across submissions — see the header comment.
  const [bagId, setBagId] = useState('');
  const [address, setAddress] = useState('');
  const [saving, setSaving] = useState(false);
  const addressRef = useRef<TextInput>(null);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      // Resolve the truck first unless the caller named one. Dispatch may be on
      // none, which is a real answer and renders as an empty state rather than
      // an error.
      let id = truckIdProp ?? null;
      if (!id) {
        const mine = await apiClient.get<MyTruck>(`/workforce/my-truck/${day}`);
        setTruck(mine.data);
        id = mine.data.truck_id;
        if (!id) { setData(null); setError(null); return; }
      }
      const res = await apiClient.get<DayAddresses>(
        `/workforce/tote-addresses/${day}`, { params: { truck_id: id } },
      );
      setData(res.data);
      setError(null);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not load this truck’s addresses.'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [day, truckIdProp]);

  useEffect(() => { load(); }, [load]);

  const canSubmit = bagId.trim().length > 0 && address.trim().length >= 3 && !saving;

  const submit = async () => {
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      await apiClient.post('/workforce/tote-addresses', {
        truck_id: truckIdProp ?? truck?.truck_id,
        entry_date: day,
        bag_id: bagId.trim(),
        raw_address: address.trim(),
      });
      tick();                       // a captain wearing gloves feels this
      setAddress('');               // bag id deliberately survives
      addressRef.current?.focus();  // straight into the next address
      await load();
    } catch (e: unknown) {
      setError(errorText(e, 'Could not save that address.'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await apiClient.delete(`/workforce/tote-addresses/${id}`);
      tick();
      await load();
    } catch (e: unknown) {
      setError(errorText(e, 'Could not remove that entry.'));
    }
  };

  if (loading) {
    return (
      <ScreenShell title="Tote addresses" loading>
        <View />
      </ScreenShell>
    );
  }

  if (!truckIdProp && truck?.no_truck_assigned) {
    return (
      <ScreenShell title="Tote addresses" onBack={onDone}>
        <View style={s.content}>
          <View style={s.card}>
            <Text style={s.sectionTitle}>No truck assigned today</Text>
            <Text style={s.empty}>
              This page is for entering addresses for the totes on the truck you
              are crewed on. Once dispatch assigns you, it will appear here.
            </Text>
          </View>
        </View>
      </ScreenShell>
    );
  }

  const byBag = groupByBag(data?.addresses ?? []);
  const disagreeing = new Set((data?.disagreements ?? []).map(d => d.bag_id));

  return (
    <ScreenShell
      title="Tote addresses"
      subtitle={[truck?.truck_name, summaryLine(data)].filter(Boolean).join(" · ")}
      refreshing={refreshing}
      onRefresh={() => load(true)}
      onBack={onDone}
    >
      <KeyboardAvoidingView
        // iOS pushes content above the keyboard; Android resizes the window
        // itself, so 'padding' there double-counts and leaves a gap.
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={s.flex}
      >
        <ScrollView
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
        >
          {error ? (
            <View style={s.errorBox}>
              <Text style={s.errorText}>{error}</Text>
            </View>
          ) : null}

          {/* ── Entry form ──────────────────────────────────────────────── */}
          <View style={s.card}>
            <Text style={s.label}>Bag</Text>
            <TextInput
              value={bagId}
              onChangeText={setBagId}
              placeholder="5270"
              placeholderTextColor={c.mutedForeground}
              // A bag id is digits off a printed label. numeric spares the
              // captain a keyboard switch on every new tote.
              keyboardType="number-pad"
              returnKeyType="next"
              onSubmitEditing={() => addressRef.current?.focus()}
              style={s.input}
              accessibilityLabel="Bag number"
            />

            <Text style={[s.label, s.labelSpaced]}>Address</Text>
            <TextInput
              ref={addressRef}
              value={address}
              onChangeText={setAddress}
              placeholder="411 W 36 St"
              placeholderTextColor={c.mutedForeground}
              autoCapitalize="words"
              autoCorrect={false}          // street names are not dictionary words
              returnKeyType="done"
              onSubmitEditing={submit}
              style={s.input}
              accessibilityLabel="Delivery address"
            />

            <Button
              onPress={submit}
              disabled={!canSubmit}
              loading={saving}
              fullWidth
              style={s.submit}
              accessibilityLabel="Add this address"
              accessibilityHint="Saves the address and keeps the bag number for the next one"
            >
              Add address
            </Button>

            {bagId.trim().length > 0 ? (
              <Text style={s.hint}>
                Bag {bagId.trim()} stays selected — keep adding its addresses.
              </Text>
            ) : null}
          </View>

          {/* ── Split totes (D4) ────────────────────────────────────────── */}
          {(data?.disagreements ?? []).map(d => (
            <View key={d.bag_id} style={s.warnBox}>
              <Text style={s.warnTitle}>Bag {d.bag_id} spans {d.block_keys.length} blocks</Text>
              <Text style={s.warnBody}>
                {d.block_keys.join('  ·  ')}
              </Text>
              <Text style={s.warnBody}>
                It will sort to {d.winning_block_key}. If one of those is a typo,
                fix it now — it is much cheaper than a wrong route.
              </Text>
            </View>
          ))}

          {/* ── Still to do (ADR-290) ───────────────────────────────────── */}
          {(data?.unaddressed_bags?.length ?? 0) > 0 ? (
            <View style={s.card}>
              <Text style={s.sectionTitle}>
                Not addressed yet ({data!.unaddressed_bags.length})
              </Text>
              <View style={s.chips}>
                {data!.unaddressed_bags.map(b => (
                  <TouchableOpacity
                    key={b}
                    onPress={() => { setBagId(b); addressRef.current?.focus(); }}
                    style={s.chip}
                    accessibilityLabel={`Enter an address for bag ${b}`}
                  >
                    <Text style={s.chipText}>{b}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          ) : null}

          {/* ── What has been entered ───────────────────────────────────── */}
          {Object.keys(byBag).length === 0 ? (
            <View style={s.card}>
              <Text style={s.empty}>
                No addresses yet. Read one off a package in the first tote and
                enter it above.
              </Text>
            </View>
          ) : (
            Object.entries(byBag).map(([bag, rows]) => (
              <View key={bag} style={s.card}>
                <View style={s.bagHeader}>
                  <Text style={s.sectionTitle}>Bag {bag}</Text>
                  <Badge tone={disagreeing.has(bag) ? 'warning' : 'muted'}>
                    {rows.length} {rows.length === 1 ? 'address' : 'addresses'}
                  </Badge>
                </View>
                {rows.map(r => (
                  <View key={r.id} style={s.row}>
                    <View style={s.flex}>
                      <Text style={s.rowText}>
                        {r.normalised_address ?? r.raw_address ?? '(address removed)'}
                      </Text>
                      <Text style={s.rowSub}>
                        {r.block_key
                          ? r.block_key
                          : 'Could not read a block from this address'}
                      </Text>
                    </View>
                    <TouchableOpacity
                      onPress={() => remove(r.id)}
                      style={s.remove}
                      accessibilityLabel={`Remove ${r.raw_address ?? 'this address'}`}
                    >
                      <Text style={s.removeText}>Remove</Text>
                    </TouchableOpacity>
                  </View>
                ))}
              </View>
            ))
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </ScreenShell>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

function groupByBag(rows: ToteAddress[]): Record<string, ToteAddress[]> {
  const out: Record<string, ToteAddress[]> = {};
  for (const r of rows) (out[r.bag_id] ??= []).push(r);
  for (const list of Object.values(out)) {
    list.sort((a, b) => a.entry_sequence - b.entry_sequence);
  }
  return out;
}

function summaryLine(data: DayAddresses | null): string {
  if (!data) return '';
  const totes = new Set(data.addresses.map(a => a.bag_id)).size;
  const left = data.unaddressed_bags.length;
  const base = `${totes} ${totes === 1 ? 'tote' : 'totes'} addressed`;
  return left > 0 ? `${base} · ${left} to go` : base;
}

// ── styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xl },

  card: {
    backgroundColor: c.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: c.border,
  },

  label: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
    color: c.mutedForeground,
    marginBottom: spacing.xs,
  },
  labelSpaced: { marginTop: spacing.md },

  input: {
    backgroundColor: c.surfaceMuted,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    // A gloved thumb needs a bigger target than a mouse does.
    paddingVertical: spacing.md,
    fontSize: fontSize.lg,
    color: c.foreground,
    borderWidth: 1,
    borderColor: c.border,
  },

  submit: { marginTop: spacing.md },
  hint: {
    marginTop: spacing.sm,
    fontSize: fontSize.sm,
    color: c.mutedForeground,
    textAlign: 'center',
  },

  sectionTitle: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
  },
  bagHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },

  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: c.border,
  },
  rowText: { fontSize: fontSize.md, color: c.foreground },
  rowSub: { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: 2 },

  remove: { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  removeText: { fontSize: fontSize.sm, color: c.danger, fontWeight: fontWeight.medium },

  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm },
  chip: {
    backgroundColor: c.surfaceMuted,
    borderRadius: radius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderWidth: 1,
    borderColor: c.border,
  },
  chipText: { fontSize: fontSize.md, color: c.foreground, fontWeight: fontWeight.medium },

  warnBox: {
    backgroundColor: c.warningLight,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: c.warning,
    gap: spacing.xs,
  },
  warnTitle: { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  warnBody: { fontSize: fontSize.sm, color: c.mutedForeground, lineHeight: 18 },

  errorBox: {
    backgroundColor: c.dangerLight,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: c.danger,
  },
  errorText: { fontSize: fontSize.sm, color: c.danger },

  empty: { fontSize: fontSize.md, color: c.mutedForeground, textAlign: 'center', lineHeight: 20 },
});
