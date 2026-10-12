import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import InterruptiveSheet from './InterruptiveSheet';
import { useAcknowledge } from './useAcknowledge';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { tick, MIN_TARGET } from '@components/ui/primitives';

/**
 * "How this company runs has changed" (ADR-494 D5, type
 * `operating_mode_change`). Mobile twin of the web prompt.
 *
 * A separate component from GraduationPrompt, not a shared one with a prop.
 * Where graduation gets a success band and a seal, this is sober: a neutral
 * header row, an explicit "things may have moved" note, and copy that says half
 * the app changed. Nobody earned this and nobody chose it — it happened to them
 * — so the design owes them orientation rather than celebration.
 *
 * ADR-305 is why the link matters more than a wall: half the surface genuinely
 * differs between modes, and the reader needs the ROLE-SCOPED explanation,
 * which is what /my-role is.
 */
export default function OperatingModeChangePrompt({
  notification,
  onDone,
  onNavigate,
}: {
  notification: { id: string; message: string; actions: { label: string; route: string }[] };
  onDone: () => void;
  onNavigate: (() => void) | null;
}) {
  const c = useColors();
  const s = styles(c);
  const { acknowledge, busy, failed } = useAcknowledge();

  const action = notification.actions[0];

  const finish = async (choice: 'confirmed' | 'skipped', then?: () => void) => {
    const ok = await acknowledge(notification.id, choice, 'prompt');
    if (!ok) return;
    if (choice === 'confirmed') tick();
    then?.();
    onDone();
  };

  return (
    <InterruptiveSheet kind="prompt" onDismiss={() => void finish('skipped')}>
      <View style={s.headerRow}>
        <View style={s.iconBox}><Text style={s.icon}>⚙️</Text></View>
        <View style={s.headerText}>
          <Text style={s.title} accessibilityRole="header">
            How this company runs has changed
          </Text>
          <Text style={s.sub}>Some of what you see and do is different now.</Text>
        </View>
      </View>

      <Text style={s.message}>{notification.message}</Text>

      {/* Stated plainly rather than discovered. A walker who finds a button
          missing assumes the app is broken; a walker who was told the mode
          changed knows to look at their role page. */}
      <View style={s.note}>
        <Text style={s.noteText}>
          Pages and buttons you used before may have moved or gone. That is the
          mode change, not a fault.
        </Text>
      </View>

      {failed && (
        <Text style={s.error} accessibilityLiveRegion="assertive">
          We couldn't record that just now. Try again. This will keep appearing
          until it saves.
        </Text>
      )}

      {action && onNavigate && (
        <TouchableOpacity
          style={[s.primary, busy && s.disabled]}
          disabled={busy}
          onPress={() => void finish('confirmed', onNavigate)}
          accessibilityRole="button"
          accessibilityLabel={action.label}
        >
          <Text style={s.primaryText}>{action.label}</Text>
        </TouchableOpacity>
      )}

      <TouchableOpacity
        style={[s.secondary, busy && s.disabled]}
        disabled={busy}
        onPress={() => void finish('skipped')}
        accessibilityRole="button"
      >
        <Text style={s.secondaryText}>Not now</Text>
      </TouchableOpacity>
    </InterruptiveSheet>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    alignItems: 'flex-start',
    paddingBottom: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: c.surfaceMuted,
    marginBottom: spacing.md,
  },
  iconBox: {
    width: 40, height: 40, borderRadius: radius.md,
    // `info`, not `warning`. Two reasons, and the second is the real one:
    //   1. Semantics — a mode change is something that HAPPENED, not a hazard.
    //      A warning triangle implies the reader should do something about it,
    //      and there is nothing to do; the mode is already switched.
    //   2. The shared error strip ("we couldn't record that") is `warning` on
    //      BOTH sheets. An identity built from the same family is an identity
    //      the D5 distinctness check cannot see, and cannot see means a future
    //      refactor can collapse the two and nothing notices.
    backgroundColor: c.infoLight,
    alignItems: 'center', justifyContent: 'center',
  },
  icon: { fontSize: 20 },
  headerText: { flex: 1 },
  title: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
    color: c.foreground,
  },
  sub: { marginTop: 2, fontSize: fontSize.sm, color: c.mutedForeground },
  message: {
    fontSize: fontSize.base,
    lineHeight: fontSize.base * 1.5,
    color: c.foreground,
  },
  note: {
    marginTop: spacing.md,
    padding: spacing.sm,
    borderRadius: radius.md,
    // The warning accent, not a neutral grey. This note IS this sheet's
    // signature element — "pages you used may have moved" is the whole reason
    // it interrupts — and a grey box reads as a footnote. Also what makes the
    // D5 distinctness check meaningful: with only `warningLight` (shared with
    // the error strip both sheets have) this component had no accent of its
    // own, so the test could not tell it apart from the celebration.
    backgroundColor: c.infoLight,
    borderLeftWidth: 3,
    borderLeftColor: c.info,
  },
  noteText: { fontSize: fontSize.sm, color: c.foreground },
  error: {
    marginTop: spacing.md,
    padding: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: c.warningLight,
    color: c.foreground,
    fontSize: fontSize.sm,
  },
  primary: {
    marginTop: spacing.lg,
    minHeight: MIN_TARGET,
    borderRadius: radius.lg,
    backgroundColor: c.foreground,
    alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  primaryText: {
    color: c.background,
    fontSize: fontSize.base,
    fontWeight: fontWeight.semibold,
  },
  secondary: {
    marginTop: spacing.sm,
    minHeight: MIN_TARGET,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.surfaceMuted,
    alignItems: 'center', justifyContent: 'center',
  },
  secondaryText: { color: c.foreground, fontSize: fontSize.base },
  disabled: { opacity: 0.6 },
});
