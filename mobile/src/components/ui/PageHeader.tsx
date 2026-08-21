import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import ThemeToggle from '@components/ui/ThemeToggle';

/**
 * Standard page header for tab-root screens that don't use ScreenShell (ADR-207).
 * Matches ScreenShell's header EXACTLY — a symmetric three-column row (balancing
 * left spacer · centered title/subtitle · right slot) with the light/dark
 * ThemeToggle on the right — so every top-level screen looks identical.
 * Pass `right` to override the toggle, or `hideToggle` to drop it.
 */
export default function PageHeader({
  title, subtitle, right, hideToggle = false,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  hideToggle?: boolean;
}) {
  const c = useColors();
  const s = styles(c);
  return (
    <View style={s.header}>
      {/* Left spacer — balances the right slot so the title stays centered */}
      <View style={s.side} />

      {/* Centre — title + subtitle stacked */}
      <View style={s.center}>
        <Text style={s.title}>{title}</Text>
        {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
      </View>

      {/* Right — custom action, else the light/dark toggle */}
      <View style={s.side}>
        {right ?? (hideToggle ? null : <ThemeToggle />)}
      </View>
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    backgroundColor: c.background,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  side:     { width: 44, alignItems: 'center' },
  center:   { flex: 1, alignItems: 'center' },
  title:    { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  subtitle: { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
});
