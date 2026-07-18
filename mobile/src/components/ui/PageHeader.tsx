import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import ThemeToggle from '@components/ui/ThemeToggle';

/**
 * Standard page header for tab-root screens that don't use ScreenShell (ADR-207).
 * Matches ScreenShell's header — bordered row, title + optional subtitle, and the
 * light/dark ThemeToggle on the right — so every top-level screen looks consistent.
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
      <View style={{ flex: 1 }}>
        <Text style={s.title}>{title}</Text>
        {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
      </View>
      {right ?? (hideToggle ? null : <ThemeToggle />)}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    backgroundColor: c.background,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  title:    { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  subtitle: { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
});
