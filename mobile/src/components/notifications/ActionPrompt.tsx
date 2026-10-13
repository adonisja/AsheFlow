import React from 'react';
import { Text, StyleSheet, TouchableOpacity } from 'react-native';
import InterruptiveSheet from './InterruptiveSheet';
import { useAcknowledge } from './useAcknowledge';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { tick, MIN_TARGET } from '@components/ui/primitives';

/**
 * The prompt for every type without a face of its own (ADR-505 D4). Mobile twin
 * of the web ActionPrompt.
 *
 * The host's `switch` used to `return null` for every type but `graduation` and
 * `operating_mode_change`. `timecard_mismatch` is declared GATE and degraded by
 * the server to a PROMPT on every day but the last, so its whole prompt phase
 * showed nothing, and, being first in line, it hid the prompts behind it.
 * Reproduced on this emulator against staging, 2026-10-13.
 *
 * Two shapes:
 *  - the action has a screen here: [action] records `confirmed` (settles it),
 *    [Later] records `skipped` (re-asks next launch);
 *  - it has NO screen on this client: a single [Close] that records
 *    `unavailable`. "Later" there would re-ask forever about something the
 *    person cannot do on this device, and `skipped` would assert a declined
 *    choice that was never offered (ADR-494's rule).
 */
export default function ActionPrompt({
  notification,
  onDone,
  onNavigate,
}: {
  notification: { id: string; label: string; message: string; actions: { label: string; route: string }[] };
  onDone: () => void;
  /** Resolved tab key, or null when this surface has no mobile equivalent. */
  onNavigate: (() => void) | null;
}) {
  const c = useColors();
  const s = styles(c);
  const { acknowledge, busy, failed } = useAcknowledge();

  const action = notification.actions[0];
  const reachable = !!(action && onNavigate);

  const finish = async (
    choice: 'confirmed' | 'skipped' | 'unavailable',
    then?: () => void,
  ) => {
    const ok = await acknowledge(notification.id, choice, 'prompt');
    if (!ok) return;          // sheet stays open; `failed` renders below
    if (choice === 'confirmed') tick();
    then?.();
    onDone();
  };

  return (
    <InterruptiveSheet
      kind="prompt"
      onDismiss={() => void finish(reachable ? 'skipped' : 'unavailable')}
    >
      <Text style={s.title} accessibilityRole="header">{notification.label}</Text>
      <Text style={s.message}>{notification.message}</Text>

      {failed && (
        <Text style={s.error} accessibilityLiveRegion="assertive">
          We couldn't record that just now. Try again. This will keep appearing
          until it saves.
        </Text>
      )}

      {reachable ? (
        <>
          <TouchableOpacity
            style={[s.primary, busy && s.disabled]}
            disabled={busy}
            onPress={() => void finish('confirmed', onNavigate!)}
            accessibilityRole="button"
            accessibilityLabel={action!.label}
          >
            <Text style={s.primaryText}>{action!.label}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[s.secondary, busy && s.disabled]}
            disabled={busy}
            onPress={() => void finish('skipped')}
            accessibilityRole="button"
          >
            <Text style={s.secondaryText}>Later</Text>
          </TouchableOpacity>
        </>
      ) : (
        <TouchableOpacity
          style={[s.primary, busy && s.disabled]}
          disabled={busy}
          onPress={() => void finish('unavailable')}
          accessibilityRole="button"
        >
          <Text style={s.primaryText}>Close</Text>
        </TouchableOpacity>
      )}
    </InterruptiveSheet>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  title: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
    color: c.foreground,
    marginBottom: spacing.sm,
  },
  message: {
    fontSize: fontSize.base,
    lineHeight: fontSize.base * 1.5,
    color: c.foreground,
  },
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
    backgroundColor: c.primary,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  primaryText: {
    color: c.primaryForeground,
    fontSize: fontSize.base,
    fontWeight: fontWeight.semibold,
  },
  secondary: {
    marginTop: spacing.sm,
    minHeight: MIN_TARGET,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.surfaceMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryText: { color: c.foreground, fontSize: fontSize.base },
  disabled: { opacity: 0.6 },
});
