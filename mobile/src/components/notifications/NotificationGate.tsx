import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import InterruptiveSheet from './InterruptiveSheet';
import { useAcknowledge } from './useAcknowledge';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { tick, MIN_TARGET } from '@components/ui/primitives';

/**
 * The one mobile surface with no exit but its own action (ADR-494). Twin of the
 * web NotificationGate.
 *
 * Two types reach here and only two: `credentials_sent` (no app without the
 * credentials, nothing to escalate toward) and `timecard_mismatch` inside the
 * final day before its pay period closes.
 *
 * ## This component decides nothing
 *
 * Whether a gate is a gate is the SERVER's answer (D6): `channels` either
 * carries `gate` or it does not. There is deliberately no expiry check and no
 * deadline arithmetic here — both already happened server-side, and a second
 * copy on this surface is exactly the web-vs-mobile drift D6 exists to prevent.
 *
 * ## Why the degraded branch exists
 *
 * A gate whose action has no mobile destination would be a wall with nothing on
 * it — worse than the modal ADR-494 D1 replaced. The server degrades a gate
 * with no ACTION to a prompt, but it cannot know that mobile has no screen for
 * a given route (that is this client's business, see navigation/actionRoutes).
 * So when `onNavigate` is null the sheet records **`unavailable`** and lets the
 * person through: a truthful statement that nobody was offered a choice, and
 * distinctly NOT `skipped`, which would assert a decision never presented.
 */
export default function NotificationGate({
  notification,
  onDone,
  onNavigate,
}: {
  notification: {
    id: string;
    label: string;
    message: string;
    actions: { label: string; route: string }[];
  };
  onDone: () => void;
  onNavigate: (() => void) | null;
}) {
  const c = useColors();
  const s = styles(c);
  const { acknowledge, busy, failed } = useAcknowledge();

  const action = notification.actions[0];
  const degraded = !action || !onNavigate;

  const finish = async (choice: 'confirmed' | 'unavailable', then?: () => void) => {
    const ok = await acknowledge(notification.id, choice, 'gate');
    // A gate must NOT close on a failed acknowledgement. The point is that the
    // record exists; letting them through without it leaves nothing to show
    // they answered.
    if (!ok) return;
    tick();
    then?.();
    onDone();
  };

  return (
    <InterruptiveSheet
      kind="gate"
      onDismiss={() => { /* unreachable: a gate ignores back and backdrop */ }}
    >
      <View style={s.headerRow}>
        <View style={s.iconBox}><Text style={s.icon}>🛡️</Text></View>
        <View style={s.headerText}>
          <Text style={s.title} accessibilityRole="header">{notification.label}</Text>
          <Text style={s.sub}>This needs an answer before you carry on.</Text>
        </View>
      </View>

      <Text style={s.message}>{notification.message}</Text>

      {failed && (
        <Text style={s.error} accessibilityLiveRegion="assertive">
          We couldn't record your answer. Try again. This stays until it saves.
        </Text>
      )}

      {degraded ? (
        <TouchableOpacity
          style={[s.neutral, busy && s.disabled]}
          disabled={busy}
          onPress={() => void finish('unavailable')}
          accessibilityRole="button"
        >
          <Text style={s.neutralText}>I've read this</Text>
        </TouchableOpacity>
      ) : (
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
    </InterruptiveSheet>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    alignItems: 'flex-start',
    backgroundColor: c.dangerLight,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  iconBox: {
    width: 40, height: 40, borderRadius: radius.md,
    backgroundColor: c.surface,
    alignItems: 'center', justifyContent: 'center',
  },
  icon: { fontSize: 20 },
  headerText: { flex: 1 },
  title: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
    color: c.foreground,
  },
  sub: { marginTop: 2, fontSize: fontSize.sm, color: c.danger },
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
    backgroundColor: c.danger,
    alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  primaryText: {
    color: c.primaryForeground,
    fontSize: fontSize.base,
    fontWeight: fontWeight.semibold,
  },
  neutral: {
    marginTop: spacing.lg,
    minHeight: MIN_TARGET,
    borderRadius: radius.lg,
    backgroundColor: c.foreground,
    alignItems: 'center', justifyContent: 'center',
  },
  neutralText: {
    color: c.background,
    fontSize: fontSize.base,
    fontWeight: fontWeight.semibold,
  },
  disabled: { opacity: 0.6 },
});
