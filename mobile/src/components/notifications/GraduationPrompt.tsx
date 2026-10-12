import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import InterruptiveSheet from './InterruptiveSheet';
import { useAcknowledge } from './useAcknowledge';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { tick, MIN_TARGET } from '@components/ui/primitives';

/**
 * "You passed" (ADR-494 D5, type `graduation`). Mobile twin of the web
 * GraduationPrompt.
 *
 * Deliberately NOT the same component as OperatingModeChangePrompt, and not a
 * parameterised one. D5: *"`graduation` is congratulatory;
 * `operating_mode_change` is 'half your app changed'. One parameterised
 * component would make them look alike, and the second would read as a
 * promotion nobody earned."*
 *
 * So this is warm — a success band, a seal, one forward action — and the
 * mode-change sheet is sober. The shared parts are the accessibility shell and
 * the acknowledgement call, which are the parts that must not differ.
 *
 * `tick()` on confirm, because a walker in a van feels it without looking.
 */
export default function GraduationPrompt({
  notification,
  onDone,
  onNavigate,
}: {
  notification: { id: string; message: string; actions: { label: string; route: string }[] };
  onDone: () => void;
  /** Resolved tab key, or null when this surface has no mobile equivalent. */
  onNavigate: (() => void) | null;
}) {
  const c = useColors();
  const s = styles(c);
  const { acknowledge, busy, failed } = useAcknowledge();

  const action = notification.actions[0];

  const finish = async (choice: 'confirmed' | 'skipped', then?: () => void) => {
    const ok = await acknowledge(notification.id, choice, 'prompt');
    if (!ok) return;          // sheet stays open; `failed` renders below
    if (choice === 'confirmed') tick();
    then?.();
    onDone();
  };

  return (
    <InterruptiveSheet kind="prompt" onDismiss={() => void finish('skipped')}>
      <View style={s.band}>
        <Text style={s.seal}>🎓</Text>
        <Text style={s.title} accessibilityRole="header">
          Congratulations, you're a Walker
        </Text>
      </View>

      <Text style={s.message}>{notification.message}</Text>
      <Text style={s.sub}>
        Your access has already changed. Here's what's different for you now.
      </Text>

      {failed && (
        <Text style={s.error} accessibilityLiveRegion="assertive">
          We couldn't record that just now. Try again. This will keep appearing
          until it saves.
        </Text>
      )}

      {/* The action renders ONLY when a mobile destination exists. A button that
          navigates nowhere is the dismiss-only control ADR-494 D1 removes. */}
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
        <Text style={s.secondaryText}>Later</Text>
      </TouchableOpacity>
    </InterruptiveSheet>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  band: {
    backgroundColor: c.successLight,
    borderRadius: radius.xl,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  seal: { fontSize: 40, marginBottom: spacing.xs },
  title: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
    color: c.foreground,
    textAlign: 'center',
  },
  message: {
    fontSize: fontSize.base,
    lineHeight: fontSize.base * 1.5,
    color: c.foreground,
  },
  sub: {
    marginTop: spacing.sm,
    fontSize: fontSize.sm,
    color: c.mutedForeground,
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
    backgroundColor: c.success,
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
