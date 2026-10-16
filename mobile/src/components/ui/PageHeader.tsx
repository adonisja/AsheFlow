import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, radius, type ThemeColors } from '@theme/index';

/**
 * The ONE screen header (ADR-517).
 *
 * Centred title, optional subtitle, an optional count beside the title, and a
 * right slot for the screen's own action. Before ADR-517 five treatments
 * existed side by side (this, a copy inside ScreenShell, three hand-built ones
 * and a bare heading), and the theme toggle appeared only where the right slot
 * happened to be free.
 *
 *   * No back chevron unless `onBack` is given: a top-level tab is a root, and
 *     its "back" went to Home, which the tab bar already does. Drill-in screens
 *     pass `onBack`.
 *   * No theme toggle: it lives in Account -> Settings -> Appearance.
 *   * Both sides are the same width, so a wide action ("All read") does not
 *     push the title off centre.
 */
export default function PageHeader({
  title, subtitle, subtitleTone = 'muted', badge, right, onBack,
}: {
  title: string;
  subtitle?: string;
  /** `danger` for a warning such as "No truck assignment today". */
  subtitleTone?: 'muted' | 'danger';
  /** A count shown beside the title (e.g. unread). Hidden when 0 or absent. */
  badge?: number;
  /** The screen's own action, or nothing. */
  right?: React.ReactNode;
  /** Only on drill-in screens. */
  onBack?: () => void;
}) {
  const c = useColors();
  const s = styles(c);
  return (
    <View style={s.header}>
      <View style={[s.side, s.left]}>
        {onBack && (
          <TouchableOpacity onPress={onBack} accessibilityRole="button" accessibilityLabel="Back"
            hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
            <Text style={[s.back, { color: c.primary }]}>‹</Text>
          </TouchableOpacity>
        )}
      </View>

      <View style={s.center}>
        <View style={s.titleRow}>
          <Text style={s.title} numberOfLines={1} accessibilityRole="header">{title}</Text>
          {!!badge && badge > 0 && (
            <View style={[s.badge, { backgroundColor: c.danger }]}>
              <Text style={[s.badgeText, { color: c.primaryForeground }]}>{badge > 99 ? '99+' : badge}</Text>
            </View>
          )}
        </View>
        {subtitle ? (
          <Text style={[s.subtitle, subtitleTone === 'danger' && { color: c.danger }]} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
      </View>

      <View style={[s.side, s.right]}>{right}</View>
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
  // Equal widths keep the title centred; 72 fits "All read" and a step count.
  side:      { width: 72 },
  left:      { alignItems: 'flex-start' },
  right:     { alignItems: 'flex-end' },
  center:    { flex: 1, alignItems: 'center' },
  titleRow:  { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  back:      { fontSize: 30, lineHeight: 32, fontWeight: '300' },
  title:     { flexShrink: 1, fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  badge:     { minWidth: 20, height: 20, borderRadius: radius.full, paddingHorizontal: 6, alignItems: 'center', justifyContent: 'center' },
  badgeText: { fontSize: fontSize.xs, fontWeight: fontWeight.bold },
  subtitle:  { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
});
