import React, { useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';
import { useAuth } from '@contexts/AuthContext';

import MyRouteScreen          from '@screens/Trainee/MyRouteScreen';
import FoundPackageScreen     from './FoundPackageScreen';

type Tab = 'myroute' | 'found';

const TABS: { key: Tab; label: string; icon: string; feature?: string }[] = [
  // ADR-289. My Route and Found are FULL-MODE ONLY, and their absence here was
  // a real gap: every endpoint under them (/rts/stops, /rts/packages,
  // /rts/missing, /packages/intake) is registered under `_full_mode`, so in
  // workforce mode the server 404s all of them and "Start Route" does nothing.
  //
  // Worse, MyRouteScreen renders `package_count` — which counts captain-entered
  // ADDRESSES in workforce mode (ADR-298) — and a stop list that is structurally
  // always empty, because commit-sort writes stops=None. A walker saw "3
  // packages · 0 stops" for a route carrying 47 parcels across 3 totes.
  //
  // The workforce equivalent is the WorkforceRoute tab (ADR-297), gated on
  // `workforce_sort`, which is mutually exclusive with `route_sort`.
  { key: 'myroute',     label: 'My Route',    icon: '🗺️', feature: 'route_sort' },
  // A walker finds an unregistered package WHILE working the route, so this
  // sits beside My Route rather than in a separate tab (ADR-246).
  { key: 'found',       label: 'Found',       icon: '📦', feature: 'package_intake' },
  // Performance REMOVED (2026-08-25). Account already carries two dedicated
  // performance surfaces — "My Stats" (/assignment-history/me/stats, our
  // record) and "Scorecard" (/scorecards/me/trend, Amazon's) — and this tab was
  // a third view of the same shift data in a tab named for route work. One home for a
  // walker's own numbers, and it is the one that already explains why there are
  // two of them (see MyAccountScreen's header comment on why they are not
  // merged).
  //
  // With it gone, every remaining sub-tab is full-mode, so the WALKER TAB
  // ITSELF is gated on `route_sort` in navigation/index.tsx — an empty shell in
  // workforce mode is worse than no tab.
];

export default function WalkerDashboard() {
  const c = useColors();
  const { hasFeature } = useAuth();
  const s = styles(c);

  // hasFeature fails OPEN on unknown capabilities (see AuthContext): a walker on
  // a flaky van connection keeps their tabs, and the server enforces the gate.
  const tabs = TABS.filter(t => !t.feature || hasFeature(t.feature));
  const [activeTab, setActiveTab] = useState<Tab>(tabs[0]?.key ?? 'myroute');

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <PageHeader title="Walker" />

      <View style={s.tabBarWrap}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={s.tabBarScroll}
        >
          {tabs.map(tab => {
            const active = activeTab === tab.key;
            return (
              <TouchableOpacity
                key={tab.key}
                style={[s.tab, active && s.tabActive]}
                onPress={() => setActiveTab(tab.key)}
                activeOpacity={0.7}
              >
                <Text style={s.tabIcon}>{tab.icon}</Text>
                <Text style={[s.tabLabel, active && { color: c.primary, fontWeight: fontWeight.semibold }]}>
                  {tab.label}
                </Text>
                {active && <View style={[s.tabIndicator, { backgroundColor: c.primary }]} />}
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      </View>

      <View style={{ flex: 1 }}>
        {activeTab === 'myroute'     && <MyRouteScreen />}
        {activeTab === 'found'       && <FoundPackageScreen />}
      </View>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:         { flex: 1, backgroundColor: c.background },
  header:       { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.xs, backgroundColor: c.background, borderBottomWidth: 1, borderBottomColor: c.border },
  title:        { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  tabBarWrap:   { backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  tabBarScroll: { paddingHorizontal: spacing.sm },
  tab:          { alignItems: 'center', flexDirection: 'row', gap: 5, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, position: 'relative' },
  tabActive:    {},
  tabIcon:      { fontSize: 14 },
  tabLabel:     { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium },
  tabIndicator: { position: 'absolute', bottom: 0, left: spacing.md, right: spacing.md, height: 2, borderTopLeftRadius: 2, borderTopRightRadius: 2 },
});
