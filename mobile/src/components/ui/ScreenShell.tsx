import React from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  ActivityIndicator, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import ThemeToggle from '@components/ui/ThemeToggle';

type Edge = 'top' | 'bottom' | 'left' | 'right';

type Props = {
  /** Optional — not needed when noHeader is set (the header isn't rendered). */
  title?: string;
  subtitle?: string;
  loading?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  children: React.ReactNode;
  /** Pass [] when this shell is embedded inside a parent that already handles safe area */
  edges?: Edge[];
  /** Hide the title/subtitle header bar (e.g. when parent owns the header) */
  noHeader?: boolean;
  /** Show a back chevron on the left; tapping calls this */
  onBack?: () => void;
  /** Extra element rendered on the right side of the header (e.g. refresh button).
   * When omitted, a quick light/dark ThemeToggle is shown by default (ADR-207). */
  headerRight?: React.ReactNode;
  /** Suppress the default header ThemeToggle (e.g. Account, which has its own control) */
  hideThemeToggle?: boolean;
};

export default function ScreenShell({
  title, subtitle, loading, refreshing, onRefresh, children,
  edges = ['top'], noHeader = false, onBack, headerRight, hideThemeToggle = false,
}: Props) {
  const c = useColors();
  const s = styles(c);

  if (loading) {
    return (
      <SafeAreaView style={s.safe} edges={edges}>
        <View style={s.center}><ActivityIndicator size="large" color={c.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={edges}>
      {!noHeader && (
        <View style={s.header}>
          {/* Left — back button or spacer */}
          <View style={s.headerSide}>
            {onBack && (
              <TouchableOpacity onPress={onBack} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }} style={s.backBtn}>
                <Text style={[s.backChevron, { color: c.primary }]}>‹</Text>
              </TouchableOpacity>
            )}
          </View>

          {/* Centre — title + subtitle stacked */}
          <View style={s.headerCenter}>
            <Text style={s.title}>{title}</Text>
            {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
          </View>

          {/* Right — custom action, else a quick light/dark toggle by default */}
          <View style={s.headerSide}>
            {headerRight ?? (hideThemeToggle ? null : <ThemeToggle />)}
          </View>
        </View>
      )}
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        refreshControl={
          onRefresh
            ? <RefreshControl refreshing={refreshing ?? false} onRefresh={onRefresh} tintColor={c.primary} />
            : undefined
        }
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:           { flex: 1, backgroundColor: c.background },
  header:         {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    backgroundColor: c.background,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  headerSide:     { width: 44, alignItems: 'center' },
  headerCenter:   { flex: 1, alignItems: 'center' },
  backBtn:        { padding: spacing.xs },
  backChevron:    { fontSize: 30, lineHeight: 32, fontWeight: '300' },
  title:          { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  subtitle:       { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  scroll:         { flex: 1 },
  content:        { padding: spacing.md, paddingBottom: 80 },
  center:         { flex: 1, justifyContent: 'center', alignItems: 'center' },
});
