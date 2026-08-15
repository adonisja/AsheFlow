/**
 * My Account — tab shell.
 *
 * Was a single 452-line screen mixing credentials with two unrelated performance
 * surfaces. Split by WHO SAYS IT, which is the distinction that actually confuses
 * people:
 *
 *   Settings   the user's own credentials, password, appearance
 *   My Stats   AsheFlow's record of their work   (/field-ops/me/performance)
 *   Scorecard  Amazon's weekly assessment        (/scorecards/me/trend)
 *
 * My Stats and Scorecard are deliberately NOT merged. They read from entirely
 * separate sources — ours from DeliveryStop/RTS/ratings, Amazon's from their own
 * systems — and can legitimately disagree. That disagreement is what the appeals
 * process contests, so collapsing them into one "performance" page would erase
 * the distinction that makes an appeal possible.
 *
 * This shell also absorbs the former ProfileScreen, which duplicated the
 * email-change flow (the same two endpoints) but lacked password change, both
 * performance cards, and the standard PageHeader.
 */
import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';

import AccountSettingsScreen from './AccountSettingsScreen';
import MyScorecardScreen from './MyScorecardScreen';
import StatsDrill from '@components/stats/StatsDrill';

type Tab = 'settings' | 'stats' | 'scorecard';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'settings',  label: 'Settings',  icon: '⚙️' },
  { key: 'stats',     label: 'My Stats',  icon: '📊' },
  { key: 'scorecard', label: 'Scorecard', icon: '🏅' },
];

const HEADER_TITLE: Record<Tab, string> = {
  settings:  'My Account',
  stats:     'My Stats',
  scorecard: 'My Scorecard',
};

export default function MyAccountScreen() {
  const c = useColors();
  const s = styles(c);
  const [activeTab, setActiveTab] = useState<Tab>('settings');

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      {/* hideToggle on Settings only — that tab owns the theme control in its body */}
      <PageHeader title={HEADER_TITLE[activeTab]} hideToggle={activeTab === 'settings'} />

      <View style={s.tabBarWrap}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.tabBarScroll}>
          {TABS.map(tab => {
            const active = activeTab === tab.key;
            return (
              <TouchableOpacity
                key={tab.key}
                style={s.tab}
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
        {activeTab === 'settings'  && <AccountSettingsScreen />}
        {activeTab === 'scorecard' && <MyScorecardScreen />}
        {activeTab === 'stats' && (
          /* StatsDrill owns its own ScrollView (ADR-271): nesting it inside
             another breaks scrolling on both platforms, so the attribution
             rides above it rather than sharing a scroll container. */
          <View style={{ flex: 1 }}>
            {/* Attribution, so two differing numbers do not read as a bug */}
            <Text style={[s.attribution, { color: c.mutedForeground }]}>
              AsheFlow's record of your deliveries and peer ratings. Amazon's own
              weekly assessment is under Scorecard — the two are measured
              separately and can differ.
            </Text>
            <StatsDrill />
          </View>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:         { flex: 1, backgroundColor: c.background },
  tabBarWrap:   { backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  tabBarScroll: { paddingHorizontal: spacing.sm },
  tab:          { alignItems: 'center', flexDirection: 'row', gap: 5,
                  paddingHorizontal: spacing.md, paddingVertical: spacing.sm, position: 'relative' },
  tabIcon:      { fontSize: 14 },
  tabLabel:     { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium },
  tabIndicator: { position: 'absolute', bottom: 0, left: spacing.md, right: spacing.md,
                  height: 2, borderTopLeftRadius: 2, borderTopRightRadius: 2 },
  statsContent: { padding: spacing.lg, paddingBottom: spacing.xxl },
  /* Own horizontal padding: this text no longer sits inside `statsContent`,
     because StatsDrill brings its own scroll container. Without it the
     attribution runs to the screen edge. */
  attribution:  { fontSize: fontSize.xs, lineHeight: 17, marginBottom: spacing.md,
                  paddingHorizontal: spacing.md, paddingTop: spacing.md },
});
