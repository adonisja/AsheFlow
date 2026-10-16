import React from 'react';
import {
  View, ScrollView, StyleSheet, RefreshControl, ActivityIndicator, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useColors } from '@contexts/ThemeContext';
import { spacing, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';

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
  /** The screen's own action on the right of the header (e.g. refresh).
   *  No default: the theme toggle lives in Account (ADR-517 D3). */
  headerRight?: React.ReactNode;
  /** `danger` tints the subtitle (e.g. "No truck assignment today."). */
  subtitleTone?: 'muted' | 'danger';
  /** Pinned element between the header and the scroll (e.g. a segmented tab bar). */
  belowHeader?: React.ReactNode;
  /**
   * iOS: inset the scroll by the keyboard, so the field being typed in and the
   * ones below it can be scrolled into view (ADR-511 D6). Android needs nothing:
   * the manifest's `adjustResize` already shrinks the window. Opt-in because
   * the other screens using this shell have not been reviewed with it on.
   */
  keyboardInsets?: boolean;
};

export default function ScreenShell({
  title, subtitle, loading, refreshing, onRefresh, children,
  edges = ['top'], noHeader = false, onBack, headerRight, subtitleTone,
  belowHeader, keyboardInsets = false,
}: Props) {
  const c = useColors();
  const s = styles(c);

  if (loading) {
    return (
      <SafeAreaView style={s.safe} edges={edges}>
        {/* The header stays while loading, so the title does not flash in. */}
        {!noHeader && title ? (
          <PageHeader title={title} subtitle={subtitle} subtitleTone={subtitleTone}
            right={headerRight} onBack={onBack} />
        ) : null}
        <View style={s.center}><ActivityIndicator size="large" color={c.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={edges}>
      {/* ADR-517: the one shared header, not a copy of it. */}
      {!noHeader && title ? (
        <PageHeader title={title} subtitle={subtitle} subtitleTone={subtitleTone}
          right={headerRight} onBack={onBack} />
      ) : null}
      {belowHeader}
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        // Without this, the first tap while a keyboard is open is consumed by
        // dismissing it — so a "Save" button under the keyboard needs two taps
        // and reads as unresponsive. Every screen in this shell has the bug the
        // moment it grows an input.
        keyboardShouldPersistTaps="handled"
        // Let the keyboard close when the user scrolls away from a field, which
        // is the iOS convention for a long form.
        keyboardDismissMode="on-drag"
        automaticallyAdjustKeyboardInsets={keyboardInsets && Platform.OS === 'ios'}
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
  scroll:         { flex: 1 },
  content:        { padding: spacing.md, paddingBottom: 80 },
  center:         { flex: 1, justifyContent: 'center', alignItems: 'center' },
});
