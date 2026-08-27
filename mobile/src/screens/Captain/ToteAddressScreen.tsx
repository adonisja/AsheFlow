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
 * A BAG IS CHOSEN, NOT TYPED. The BTR sheet (ADR-290) already tells us which
 * totes are on this truck, so the captain taps one from that list. Typing an id
 * from memory invites a transposition, and a mistyped bag is a tote that
 * silently never gets sorted — it does not error, it just never appears. Bags
 * leave the picker once they have an address, so the list doubles as a countdown
 * of what is left.
 *
 * ONE BAG AT A TIME: PICKER, OR ENTRY — NEVER BOTH (ADR-296 D2).
 * This REVERSES ADR-291's "the picker never closes". That rule was written
 * against a real worry — that swapping the picker out forces a commit before the
 * captain has seen the alternatives — but it bought protection from the wrong
 * failure. Keeping both on screen put a 25-row picker above the form and the
 * entered-bag cards below it, so after every submit the one thing the captain
 * wanted to see (the address that just saved) was the one region scrolled off.
 * And they are not weighing alternatives: they walked to a physical tote and
 * picked it up. The escape hatch survives as "Back to bags" in the entry header,
 * which costs the same one tap that re-picking did.
 *
 * WITHIN the form the bag STAYS selected. A captain enters several addresses for
 * one tote before moving on, so submit clears the field and refocuses rather than
 * returning: type-address, submit, type-address — one field, one thumb — until
 * they tap Done. Done goes back to the picker, where the tote they just finished
 * is now on screen as an entered card.
 *
 * A tote can hold more than one street, and a bag with an address is no longer
 * in the picker, so each entered bag carries its own "Add another" — the only
 * way back to a tote once it has left the list, and the ONLY affordance for it
 * (ADR-296 D3 removed the duplicate that stood at the top of the screen).
 *
 * With no BTR sheet imported the bag list is unknowable, so free entry is
 * offered as an explicit fallback rather than the default.
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
  StyleSheet, Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Badge, Button, tick } from '@components/ui/primitives';
import { errorText } from '@api/errorText';
import { localYMD } from '@hooks/localDate';
import BuildingInfoPrompt from '@components/route/BuildingInfoPrompt';

// ── Types (mirror the /workforce endpoints) ───────────────────────────────────

type ToteAddress = {
  id: string;
  bag_id: string;
  raw_address: string | null;
  normalised_address: string | null;
  block_key: string | null;
  /** The block key as a sentence. Server-derived — see ADR-296 D5. Null when the
   *  address no longer parses, in which case the raw key stands alone. */
  block_description: string | null;
  entry_sequence: number;
  entered_by_name: string | null;
  geocoded: boolean;
  /** Same colour the picker chip shows, so one tote looks the same in both. */
  bag_color: string | null;
  bag_color_name: string | null;
};

type Disagreement = {
  bag_id: string;
  block_keys: string[];
  winning_block_key: string;
};

type UnaddressedBag = {
  bag_id: string;
  /** Resolved hex from the sheet's colour word; null renders a neutral pill. */
  bag_color: string | null;
  /** The colour WORD ("orange"), for labelling and search. */
  bag_color_name: string | null;
  /** Reference only (ADR-290 D7). Deliberately NOT a grouping key — a captain
   *  cannot tell which Amazon route a physical tote belongs to by looking. */
  amazon_route_name: string | null;
};

/** Mirrors ToteAddressListOut exactly — it carries no entry_date or truck_id,
 *  because the caller already supplied both in the request. */
type DayAddresses = {
  addresses: ToteAddress[];
  disagreements: Disagreement[];
  unaddressed_bags: string[];
  unaddressed: UnaddressedBag[];
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

  // Local, not UTC. toISOString() rolls over at 8 PM Eastern, so an evening
  // sort would file addresses against tomorrow — see hooks/localDate.ts.
  const day = entryDate ?? localYMD();

  const [truck, setTruck] = useState<MyTruck | null>(null);
  const [data, setData] = useState<DayAddresses | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sticky across submissions — see the header comment.
  const [bagId, setBagId] = useState('');
  const [manualBag, setManualBag] = useState('');   // fallback when no BTR sheet
  const [filter, setFilter] = useState('');
  const [openGroup, setOpenGroup] = useState<string | null>(null);
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

  const canSubmit = bagId.length > 0 && address.trim().length >= 3 && !saving;

  // A BTR sheet tells us which bags exist. Without one the list is unknowable,
  // and free entry becomes the only way through (see the form below).
  const hasSheet = (data?.unaddressed_bags?.length ?? 0) > 0
    || (data?.addresses?.length ?? 0) > 0;

  // Filtered, then grouped by the Amazon route the sheet listed the bag under —
  // which is the order the totes are physically stacked in.
  const groupedBags = groupBags(data?.unaddressed ?? [], filter);

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

  const useManualBag = () => {
    const b = manualBag.trim();
    if (!b) return;
    tick();
    setBagId(b);
    setManualBag('');
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
  // The selected bag may live in EITHER list: unaddressed while it is being
  // filled in, entered once it has an address and left the picker. Checking one
  // only would drop the colour exactly when "Add another" reopens a finished tote.
  const selectedBag =
    (data?.unaddressed ?? []).find(b => b.bag_id === bagId) ?? null;
  const selectedEntered = bagId ? (byBag[bagId] ?? [])[0] ?? null : null;
  const selectedColor = selectedBag?.bag_color ?? selectedEntered?.bag_color ?? null;
  const selectedColorName =
    selectedBag?.bag_color_name ?? selectedEntered?.bag_color_name ?? null;

  // Entered cards, in bag-id order, narrowed to the open bag while one is open.
  // Both the list AND its empty state read from this, so a freshly opened bag
  // with no addresses cannot fall through to rendering nothing at all.
  const visibleBags = sortedBags(byBag).filter(
    ([bag]) => !bagId || bag === bagId,
  );
  // Bags that already have at least one address — they have left the picker, so
  // "Add another" is the only route back and the form must say which mode it is
  // in, or a captain cannot tell why the bag is not in the list above.
  const alreadyAddressed = new Set(Object.keys(byBag));
  const disagreeing = new Set((data?.disagreements ?? []).map(d => d.bag_id));

  return (
    <ScreenShell
      title="Tote addresses"
      subtitle={[truck?.truck_name, summaryLine(data)].filter(Boolean).join(" · ")}
      refreshing={refreshing}
      onRefresh={() => load(true)}
      onBack={onDone}
    >
      <View style={s.content}>
          {error ? (
            <View style={s.errorBox}>
              <Text style={s.errorText}>{error}</Text>
            </View>
          ) : null}

          {/* ── Bag picker ───────────────────────────────────────────────
              A flat chip list is unusable at real scale: a 25-tote truck renders
              25 identical four-digit pills and the captain hunts for one. Three
              things fix that, all from data the BTR sheet already carries:

                · a FILTER — typing "52" narrows 25 bags to one, which is faster
                  than scanning and is how someone with a bag in hand thinks;
                · GROUPING by Amazon route, because totes are stacked that way on
                  the truck, so the list matches the physical order of work;
                · the bag's COLOUR, which is what the captain is actually looking
                  at — the number confirms, the colour finds.

              Groups collapse to a single row each, so 25 totes across 4 routes is
              4 lines until one is opened. */}
          {!bagId && ((data?.unaddressed?.length ?? 0) > 0 || !hasSheet) ? (
            <View style={s.card}>
              <View style={s.bagHeader}>
                <Text style={s.sectionTitle}>Which bag?</Text>
                {(data?.unaddressed?.length ?? 0) > 0 ? (
                  <Badge tone="muted">{data!.unaddressed.length} left</Badge>
                ) : null}
              </View>

              {/* The filter earns its place past a handful of bags. Below that it
                  is a field taking a tap for nothing. */}
              {(data?.unaddressed?.length ?? 0) > 8 ? (
                <TextInput
                  value={filter}
                  onChangeText={setFilter}
                  placeholder="Filter by number or colour"
                  placeholderTextColor={c.mutedForeground}
                  // NOT number-pad. The placeholder invites a colour, and a
                  // numeric keyboard makes "orange" literally untypable — the
                  // control contradicted its own label.
                  autoCapitalize="none"
                  autoCorrect={false}
                  clearButtonMode="while-editing"
                  returnKeyType="search"
                  style={[s.input, s.filterInput]}
                  accessibilityLabel="Filter bags"
                />
              ) : null}

              {groupedBags.map(([routeName, bags], gi) => {
                // First group opens by default so the screen never lands fully
                // collapsed. A single group is NOT a reason to hide the header:
                // 25 bags under one colour is exactly when the captain needs to
                // see what they are looking at. The old `length > 1` guard had
                // this backwards and rendered a flat 25-chip grid, unlabelled.
                const open = openGroup === null ? gi === 0 : openGroup === routeName;
                return (
                  <View key={routeName} style={s.group}>
                    <TouchableOpacity
                      // Collapsing must not fall back to "first group open".
                      onPress={() => {
                        tick();
                        setOpenGroup(open ? '__none__' : routeName);
                      }}
                      style={s.groupHeader}
                      accessibilityLabel={`${routeName}, ${bags.length} bags`}
                      accessibilityState={{ expanded: open }}
                    >
                      <View style={s.groupLeft}>
                        {/* Safe to read bags[0]: the group KEY is the colour,
                            so every bag in this group shares one hex. */}
                        <View
                          style={[
                            s.groupSwatch,
                            { backgroundColor: bags[0]?.bag_color ?? c.surfaceMuted },
                            !bags[0]?.bag_color && s.swatchEmpty,
                          ]}
                        />
                        <Text style={s.groupTitle}>{titleCase(routeName)}</Text>
                      </View>
                      <View style={s.headerRight}>
                        <Badge tone="muted">{bags.length}</Badge>
                        <Text style={s.chevron}>{open ? '▾' : '▸'}</Text>
                      </View>
                    </TouchableOpacity>

                    {open ? (
                      <View style={s.chips}>
                        {bags.map(b => {
                          const on = b.bag_id === bagId;
                          return (
                            <TouchableOpacity
                              key={b.bag_id}
                              onPress={() => { tick(); setBagId(on ? '' : b.bag_id); setAddress(''); }}
                              style={[s.chip, on && s.chipOn]}
                              accessibilityLabel={
                                `Bag ${b.bag_id}${b.amazon_route_name ? `, route ${b.amazon_route_name}` : ''}`
                              }
                              accessibilityState={{ selected: on }}
                            >
                              {/* The colour is the find; the number confirms it. */}
                              <View
                                style={[
                                  s.swatch,
                                  { backgroundColor: b.bag_color ?? c.surfaceMuted },
                                  !b.bag_color && s.swatchEmpty,
                                ]}
                              />
                              <Text style={[s.chipText, on && s.chipTextOn]}>{b.bag_id}</Text>
                            </TouchableOpacity>
                          );
                        })}
                      </View>
                    ) : null}
                  </View>
                );
              })}

              {filter.trim() && groupedBags.length === 0 ? (
                <Text style={s.hintLeft}>No bag matches “{filter.trim()}”.</Text>
              ) : null}

              {/* No BTR sheet means the bag list is unknowable, so free entry is
                  the only way through — the fallback, never the default. */}
              {!hasSheet ? (
                <View style={s.fallback}>
                  <Text style={s.fallbackTitle}>No BTR sheet imported today</Text>
                  <Text style={s.fallbackHint}>
                    Without it we do not know which totes are on this truck, so
                    type the bag number from the label.
                  </Text>
                  <View style={s.inlineRow}>
                    <TextInput
                      value={manualBag}
                      onChangeText={setManualBag}
                      placeholder="5270"
                      placeholderTextColor={c.mutedForeground}
                      keyboardType="number-pad"
                      returnKeyType="done"
                      onSubmitEditing={useManualBag}
                      style={[s.input, s.flex]}
                      accessibilityLabel="Bag number"
                    />
                    <Button
                      onPress={useManualBag}
                      disabled={manualBag.trim().length === 0}
                      accessibilityLabel="Use this bag"
                    >
                      Use
                    </Button>
                  </View>
                </View>
              ) : null}
            </View>
          ) : null}

          {/* ── Address entry for the SELECTED bag ─────────────────────────── */}
          {bagId ? (
            <View style={[s.card, s.selectedCard]}>
              <View style={s.bagHeader}>
                <BagPill
                  bagId={bagId}
                  color={selectedColor}
                  colorName={selectedColorName}
                  styles={s}
                  c={c}
                />
                <TouchableOpacity
                  onPress={() => { tick(); setBagId(''); setAddress(''); }}
                  style={s.addAnother}
                  accessibilityLabel="Back to the bag list"
                >
                  <Text style={s.link}>
                    {alreadyAddressed.has(bagId) ? 'Done' : 'Back to bags'}
                  </Text>
                </TouchableOpacity>
              </View>

              <Text style={[s.label, s.labelSpaced]}>Address</Text>
              <TextInput
                ref={addressRef}
                value={address}
                onChangeText={setAddress}
                placeholder="411 W 36 St"
                placeholderTextColor={c.mutedForeground}
                autoCapitalize="words"
                autoCorrect={false}          // street names are not dictionary words
                autoFocus                    // the bag is chosen; the address is all that is left
                returnKeyType="done"
                onSubmitEditing={submit}
                style={s.input}
                accessibilityLabel={`Delivery address for bag ${bagId}`}
              />

              <Button
                onPress={submit}
                disabled={!canSubmit}
                loading={saving}
                fullWidth
                style={s.submit}
                accessibilityLabel="Add this address"
                accessibilityHint="Saves it and stays on this bag for the next one"
              >
                Add address
              </Button>

              <Text style={s.hint}>
                Staying on bag {bagId} — add its other addresses, or tap
                {alreadyAddressed.has(bagId) ? ' Done' : ' Back to bags'} when
                this tote is finished.
              </Text>
            </View>
          ) : null}

          {/* ── Split totes (D4) ────────────────────────────────────────── */}
          {/* Scoped to the open bag for the same reason the cards below are: while
              a captain is entering, the only tote that matters is the one in
              hand. A split warning for a DIFFERENT bag is not actionable until
              they walk to it. */}
          {(data?.disagreements ?? [])
            .filter(d => !bagId || d.bag_id === bagId)
            .map(d => (
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

          {/* ── What has been entered ───────────────────────────────────── */}
          {/* While a bag is open, ONLY that bag's entries are listed. The other
              totes are a distraction from the one physically in hand, and on a
              phone they push the just-saved address off screen — the same
              failure the picker caused (ADR-296 D2), one region further down. */}
          {visibleBags.length === 0 ? (
            <View style={s.card}>
              <Text style={s.empty}>
                {bagId
                  // A bag is open but has nothing yet: say so about THIS tote.
                  // The generic "no addresses yet" would read as though the whole
                  // day were empty while the captain is mid-entry on bag 2500.
                  ? `Nothing entered for bag ${bagId} yet. Read an address off a package in this tote and enter it above.`
                  : 'No addresses yet. Read one off a package in the first tote and enter it above.'}
              </Text>
            </View>
          ) : (
            visibleBags.map(([bag, rows]) => (
              <View key={bag} style={s.card}>
                <View style={s.bagHeader}>
                  <BagPill
                    bagId={bag}
                    color={rows[0]?.bag_color ?? null}
                    colorName={rows[0]?.bag_color_name ?? null}
                    styles={s}
                    c={c}
                  />
                  <View style={s.headerRight}>
                    <Badge tone={disagreeing.has(bag) ? 'warning' : 'muted'}>
                      {rows.length} {rows.length === 1 ? 'address' : 'addresses'}
                    </Badge>
                    {/* A tote can hold more than one street. Once a bag has an
                        address it leaves the picker above, so this is the only
                        way back to it. */}
                    <TouchableOpacity
                      // The form renders ABOVE this list, which is a short scroll
                      // on a phone. Deliberately not auto-scrolling: yanking the
                      // view while a thumb is mid-tap is worse than a small
                      // deliberate scroll, and autoFocus already raises the
                      // keyboard as the signal that something opened.
                      onPress={() => { tick(); setBagId(bag); setAddress(''); }}
                      style={s.addAnother}
                      accessibilityLabel={`Add another address to bag ${bag}`}
                    >
                      <Text style={s.link}>Add another</Text>
                    </TouchableOpacity>
                  </View>
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
                      {/* The key is the system's token; this is what it means.
                          Server-derived (ADR-296 D5) — the trailing number is a
                          hundred-block on one address format and a cross street
                          on another, and the key alone cannot tell you which. */}
                      {r.block_description ? (
                        <Text style={s.rowSub}>{r.block_description}</Text>
                      ) : null}
                      {/* ADR-293 D5 — "know anything about this building?" at
                          the moment the address is already on screen. Passive
                          on purpose: the entry loop above clears and refocuses
                          for the next address, and a blocking prompt would
                          trade a hundred addresses for a handful of profiles. */}
                      <BuildingInfoPrompt
                        normalisedAddress={r.normalised_address}
                        blockKey={r.block_key}
                      />
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
      </View>
    </ScreenShell>
  );
}

// ── BagPill ───────────────────────────────────────────────────────────────────

/** The bag id wearing its tote's colour (ADR-296 D3/D4).
 *
 * The same component titles the entry form and every entered card, so a tote
 * looks identical wherever it appears — which is the point: the captain is
 * matching it against a physical bag in front of them.
 *
 * The swatch is the PHYSICAL colour and does not move with the theme (ADR-296 D1).
 * A black tote is black in light mode and dark mode, because the captain is
 * matching it against a bag that does not change. Black is true #000000; the
 * hairline ring — also theme-fixed — is what keeps it visible on a dark surface,
 * which is the job the old slate (#94A3B8) was doing by lying about the colour.
 */
function BagPill({
  bagId, color, colorName, styles: s, c,
}: {
  bagId: string;
  color: string | null;
  colorName: string | null;
  styles: ReturnType<typeof styles>;
  c: ThemeColors;
}) {
  return (
    <View style={s.bagPill}>
      <View
        style={[
          s.pillSwatch,
          { backgroundColor: color ?? c.surfaceMuted },
          !color && s.swatchEmpty,
        ]}
      />
      <Text
        style={s.bagPillText}
        // Screen readers get the colour word; sighted users get the swatch.
        accessibilityLabel={
          colorName ? `${titleCase(colorName)} bag ${bagId}` : `Bag ${bagId}`
        }
      >
        {bagId}
      </Text>
    </View>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

/** Colour words a captain might type for a given canonical colour.
 *
 * The bags are physically NAVY but crews say "blue" — bag_colors.py already
 * accepts "blue" as an alias when PARSING the sheet, so search has to accept it
 * too. Otherwise the one word most people reach for silently returns nothing.
 */
const COLOR_ALIASES: Record<string, string> = { navy: 'blue' };

/** Canonical name plus any alias, lowercased, for substring matching. */
function colorSearchText(name: string | null): string {
  if (!name) return '';
  const n = name.toLowerCase();
  const alias = COLOR_ALIASES[n];
  return alias ? `${n} ${alias}` : n;
}

/** Filter by number OR colour, then group by COLOUR. Returns [colour, bags][].
 *
 * GROUPED BY COLOUR, NOT BY AMAZON ROUTE. An earlier version grouped by route,
 * which is useless in the hand: a captain looking at a physical tote has no way
 * to tell which Amazon route it belongs to. Colour is the one attribute they
 * can SEE, so it is the only grouping that maps to the thing in front of them.
 */
function groupBags(bags: UnaddressedBag[], filter: string): [string, UnaddressedBag[]][] {
  const q = filter.trim().toLowerCase();
  const matched = q
    // Number OR colour — either is a reasonable thing to have in mind while
    // holding a bag. Matching only the number is why colour search found nothing.
    ? bags.filter(
        b =>
          b.bag_id.toLowerCase().includes(q) ||
          colorSearchText(b.bag_color_name).includes(q),
      )
    : bags;

  const out = new Map<string, UnaddressedBag[]>();
  for (const b of matched) {
    // A bag whose sheet carried no colour still needs a home. "No colour" is
    // honest — the sheet did not say, rather than inventing one.
    const key = b.bag_color_name ?? 'No colour';
    const list = out.get(key) ?? [];
    list.push(b);
    out.set(key, list);
  }
  for (const list of out.values()) list.sort((a, b) => a.bag_id.localeCompare(b.bag_id));
  // Ungrouped last; otherwise alphabetical so order is stable between refreshes
  // rather than shifting as bags get addressed.
  return [...out.entries()].sort((a, b) =>
    a[0] === 'No colour' ? 1 : b[0] === 'No colour' ? -1 : a[0].localeCompare(b[0]),
  );
}


/** "orange" -> "Orange". The API returns lowercase colour words. */
function titleCase(v: string): string {
  return v.charAt(0).toUpperCase() + v.slice(1);
}

/** Entered bags in bag-id order, numerically where the ids are numbers.
 *
 * NOT `Object.entries`. JS hoists integer-like keys into ascending numeric order
 * and appends everything else in insertion order, so the list LOOKS sorted for a
 * numeric BTR sheet and silently is not: one hand-typed non-numeric bag (the
 * no-sheet fallback allows any string) lands at the end regardless of its value,
 * and the captain scanning for it finds it somewhere other than where the number
 * says it should be. Sorting explicitly means the order is a decision rather
 * than an artefact of key insertion.
 */
function sortedBags(
  byBag: Record<string, ToteAddress[]>,
): [string, ToteAddress[]][] {
  return Object.entries(byBag).sort(([a], [b]) =>
    a.localeCompare(b, undefined, { numeric: true }),
  );
}

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

  headerRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  addAnother: { paddingVertical: spacing.xs, paddingHorizontal: spacing.xs },
  link: { fontSize: fontSize.sm, color: c.brand, fontWeight: fontWeight.medium },
  hintLeft: { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: spacing.xs },

  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm },
  selectedCard: { borderColor: c.brand },
  filterInput: { marginTop: spacing.sm, fontSize: fontSize.md },
  group: { marginTop: spacing.sm },
  groupHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: spacing.sm,
  },
  fallback: {
    marginTop: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surfaceMuted,
    gap: spacing.xs,
  },
  fallbackTitle: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
  },
  fallbackHint: { fontSize: fontSize.sm, color: c.mutedForeground },
  groupLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  groupSwatch: { width: 16, height: 16, borderRadius: 8, borderWidth: 1, borderColor: c.swatchRing },
  groupTitle: { fontSize: fontSize.md, fontWeight: fontWeight.medium, color: c.foreground },
  chevron: { fontSize: fontSize.md, color: c.mutedForeground },
  // The colour is what the captain scans for, and every swatch wears a hairline
  // ring (ADR-296 D1).
  //
  // `c.swatchRing` is deliberately NOT `c.border`: it holds the SAME value in
  // light and dark mode, because the swatch depicts a tote the captain is
  // physically holding and nothing about it may shift with a display preference.
  // A themed ring would make a black bag look different between modes — the very
  // mismatch true black was chosen to end. It is also not `c.ring`, which is the
  // dedicated focus indicator and is reserved for nothing else (WCAG 2.4.11).
  swatch: {
    width: 12, height: 12, borderRadius: 6, marginRight: spacing.xs,
    borderWidth: 1, borderColor: c.swatchRing,
  },
  // A bag with no colour on the sheet gets a hollow ring rather than a filled
  // pill that would read as a real colour. Same ring as its siblings — otherwise
  // the one swatch that means "unknown" would be the one that moves with theme.
  swatchEmpty: { borderWidth: 1, borderColor: c.swatchRing },

  bagPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: c.surfaceMuted,
    borderRadius: radius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderWidth: 1,
    borderColor: c.border,
  },
  pillSwatch: { width: 12, height: 12, borderRadius: 6, borderWidth: 1, borderColor: c.swatchRing },
  bagPillText: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
  },
  inlineRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.xs },
  chipOn: { backgroundColor: c.brand, borderColor: c.brand },
  chipTextOn: { color: c.brandForeground },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: c.surfaceMuted,
    borderRadius: radius.full,
    paddingHorizontal: spacing.md,
    // 44pt minimum target — a gloved thumb, per MIN_TARGET in primitives.
    minHeight: 44,
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
