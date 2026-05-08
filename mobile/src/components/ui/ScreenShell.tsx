import React from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  useColorScheme, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { lightColors, darkColors, spacing, fontSize, fontWeight } from '@theme/index';

type Edge = 'top' | 'bottom' | 'left' | 'right';

type Props = {
  title: string;
  subtitle?: string;
  loading?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  children: React.ReactNode;
  /** Pass [] when this shell is embedded inside a parent that already handles safe area */
  edges?: Edge[];
  /** Hide the title/subtitle header bar (e.g. when parent owns the header) */
  noHeader?: boolean;
};

export default function ScreenShell({
  title, subtitle, loading, refreshing, onRefresh, children,
  edges = ['top'], noHeader = false,
}: Props) {
  const scheme = useColorScheme();
  const c = scheme === 'dark' ? darkColors : lightColors;
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
          <Text style={s.title}>{title}</Text>
          {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
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
        {!noHeader ? null : subtitle ? (
          <Text style={[s.inlineSubtitle, { color: c.mutedForeground }]}>{subtitle}</Text>
        ) : null}
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: typeof lightColors) => StyleSheet.create({
  safe:           { flex: 1, backgroundColor: c.background },
  header:         {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    backgroundColor: c.background,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  title:          { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  subtitle:       { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  inlineSubtitle: { fontSize: fontSize.xs, marginBottom: spacing.sm },
  scroll:         { flex: 1 },
  content:        { padding: spacing.md, paddingBottom: 80 },
  center:         { flex: 1, justifyContent: 'center', alignItems: 'center' },
});
