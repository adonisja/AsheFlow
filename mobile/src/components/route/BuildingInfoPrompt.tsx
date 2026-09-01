/**
 * "Know anything about this building?" at the moment the address is on screen
 * (ADR-293 D5).
 *
 * In full mode building intelligence accrues automatically: a walker completes
 * a stop and ADR-277 surfaces the building for assessment in context. Workforce
 * mode has no stops, so collection is entirely manual — and without a surface
 * it does not happen at all, which is what leaves the nightly decay job (now
 * stopped, ADR-293 D1) with nothing to decay in the first place.
 *
 * WHY IT IS PASSIVE
 * -----------------
 * The tote-address loop is deliberately fast: submit clears the field, refocuses
 * the input, and the captain types the next address wearing gloves. Anything
 * that interrupts that — a modal, a required choice — would trade a hundred
 * addresses for a handful of profiles.
 *
 * So this waits on the entered card. The captain who remembers something taps
 * it; the captain who is moving ignores it and nothing is slower. Capture rate
 * is lower than a blocking prompt and that is the intended trade.
 */
import React, { useState } from 'react';
import { Modal, ScrollView, Text, TouchableOpacity, View } from 'react-native';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Button, tick, MIN_TARGET } from '@components/ui/primitives';

/** The server's vocabulary, verbatim (routers/building_profiles BUILDING_TYPES).
 *  Grouped only for scanning — a captain reads "is this a home or a business?"
 *  faster than a flat list of nine. All nine are offered on purpose: hiding the
 *  rarer ones behind a "more" would under-report them, which biases exactly the
 *  sample ADR-293 D3's provenance column exists to let us reason about. */
const TYPE_GROUPS: { label: string; types: { key: string; label: string }[] }[] = [
  {
    label: 'Residential',
    types: [
      { key: 'walkup',       label: 'Walk-up' },
      { key: 'elevator',     label: 'Elevator' },
      { key: 'doorman',      label: 'Doorman' },
      { key: 'receptionist', label: 'Receptionist' },
      { key: 'mailroom',     label: 'Mailroom' },
    ],
  },
  {
    label: 'Business',
    types: [
      { key: 'biz_front',        label: 'Front desk' },
      { key: 'biz_security',     label: 'Security' },
      { key: 'biz_freight',      label: 'Freight lift' },
      { key: 'biz_loading_dock', label: 'Loading dock' },
    ],
  },
];

type Props = {
  /** The address as the server normalised it. Null when it did not parse — the
   *  prompt hides rather than filing a profile against something unresolvable. */
  normalisedAddress: string | null;
  blockKey: string | null;
  /** Already has a profile: show it as recorded rather than inviting a duplicate. */
  recorded?: string | null;
  onSaved?: (buildingType: string) => void;
};

export default function BuildingInfoPrompt({
  normalisedAddress, blockKey, recorded, onSaved,
}: Props) {
  const c = useColors();
  const s = styles(c);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // An address that did not geocode has no stable key, so a profile filed
  // against it could never be found again.
  if (!normalisedAddress) return null;

  if (recorded) {
    return <Text style={s.recorded}>Building: {labelFor(recorded)}</Text>;
  }

  const save = async (buildingType: string) => {
    setSaving(true);
    setError(null);
    try {
      // collection_source is DERIVED server-side (ADR-293 D3) — deliberately
      // not sent. The client cannot label its own provenance.
      await apiClient.post('/building-profiles/', {
        normalised_address: normalisedAddress,
        block_key: blockKey ?? undefined,
        building_type: buildingType,
      });
      tick();
      setOpen(false);
      onSaved?.(buildingType);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not save that.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <TouchableOpacity
        onPress={() => { tick(); setOpen(true); }}
        style={s.prompt}
        accessibilityRole="button"
        accessibilityLabel={`Add building information for ${normalisedAddress}`}
      >
        <Text style={s.promptText}>+ building info</Text>
      </TouchableOpacity>

      <Modal visible={open} transparent animationType="slide"
             onRequestClose={() => setOpen(false)}>
        <View style={s.backdrop}>
          <View style={s.sheet}>
            <Text style={s.title}>What kind of building?</Text>
            <Text style={s.subtitle} numberOfLines={2}>{normalisedAddress}</Text>

            <ScrollView style={s.scroll} keyboardShouldPersistTaps="handled">
              {TYPE_GROUPS.map(g => (
                <View key={g.label} style={s.group}>
                  <Text style={s.groupLabel}>{g.label}</Text>
                  <View style={s.chips}>
                    {g.types.map(t => (
                      <TouchableOpacity
                        key={t.key}
                        disabled={saving}
                        onPress={() => save(t.key)}
                        style={s.chip}
                        accessibilityRole="button"
                        accessibilityLabel={t.label}
                      >
                        <Text style={s.chipText}>{t.label}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                </View>
              ))}
            </ScrollView>

            {error ? <Text style={s.error}>{error}</Text> : null}
            <Button variant="ghost" onPress={() => setOpen(false)}>Not now</Button>
          </View>
        </View>
      </Modal>
    </>
  );
}

function labelFor(key: string): string {
  for (const g of TYPE_GROUPS) {
    const hit = g.types.find(t => t.key === key);
    if (hit) return hit.label;
  }
  return key;
}

const styles = (c: ThemeColors) => ({
  prompt: {
    paddingVertical: spacing.xs,
    minHeight: 32,
    justifyContent: 'center' as const,
  },
  promptText: {
    color: c.primary,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
  },
  recorded: {
    color: c.mutedForeground,
    fontSize: fontSize.xs,
    marginTop: spacing.xs,
  },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'flex-end' as const,
  },
  sheet: {
    backgroundColor: c.card,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.lg,
    maxHeight: '80%' as const,
  },
  title: {
    color: c.foreground,
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
  },
  subtitle: {
    color: c.mutedForeground,
    fontSize: fontSize.sm,
    marginTop: spacing.xs,
    marginBottom: spacing.md,
  },
  scroll: { flexGrow: 0 },
  group: { marginBottom: spacing.md },
  groupLabel: {
    color: c.mutedForeground,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    textTransform: 'uppercase' as const,
    marginBottom: spacing.xs,
  },
  chips: { flexDirection: 'row' as const, flexWrap: 'wrap' as const, gap: spacing.xs },
  chip: {
    minHeight: MIN_TARGET,
    justifyContent: 'center' as const,
    paddingHorizontal: spacing.md,
    borderRadius: radius.full,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surfaceMuted,
  },
  chipText: {
    color: c.foreground,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
  },
  error: {
    color: c.danger,
    fontSize: fontSize.sm,
    marginBottom: spacing.sm,
  },
});
