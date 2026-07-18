import React, { useState, useEffect } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '@contexts/AuthContext';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';

import TrainerTodayScreen       from './TrainerTodayScreen';
import TrainerHistoryScreen     from './TrainerHistoryScreen';
import TrainerPerformanceScreen from './TrainerPerformanceScreen';
import Phase4Screen             from './Phase4Screen';

type Tab = 'today' | 'history' | 'performance' | 'phase4';

export default function TrainerDashboard() {
  const c = useColors();
  const { user } = useAuth();

  const [activeTab, setActiveTab] = useState<Tab>('today');
  const [isPhase4,  setIsPhase4]  = useState(false);

  // Check if today's session is Phase 4 — same check the web navbar does
  useEffect(() => {
    if (!user?.id) return;
    apiClient.get('/training/trainer/today')
      .then(res => {
        const dayNum = res.data?.record?.current_day_number ?? null;
        setIsPhase4(dayNum === 4);
      })
      .catch(() => setIsPhase4(false));
  }, [user?.id]);

  const tabs: { key: Tab; label: string; icon: string }[] = [
    // My Route and Route Sort are TOP-LEVEL tabs now (field actions, not
    // training) — this dashboard is training-only.
    { key: 'today',       label: "Today",       icon: '📋' },
    { key: 'history',     label: 'History',     icon: '📂' },
    { key: 'performance', label: 'Performance', icon: '📊' },
    ...(isPhase4 ? [{ key: 'phase4' as Tab, label: 'Phase 4', icon: '🎯' }] : []),
  ];

  const s = styles(c);

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      {/* Header */}
      <View style={s.header}>
        <Text style={s.title}>Trainer Dashboard</Text>
      </View>

      {/* Tab bar */}
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

      {/* Screen content — rendered directly, not as a navigator */}
      <View style={{ flex: 1 }}>
        {activeTab === 'today'       && <TrainerTodayScreen />}
        {activeTab === 'history'     && <TrainerHistoryScreen />}
        {activeTab === 'performance' && <TrainerPerformanceScreen />}
        {activeTab === 'phase4'      && <Phase4Screen />}
      </View>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:          { flex: 1, backgroundColor: c.background },
  header:        {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
    backgroundColor: c.background,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  title:         { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  tabBarWrap:    {
    backgroundColor: c.surface,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  tabBarScroll:  { paddingHorizontal: spacing.sm },
  tab:           {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 5,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    position: 'relative',
  },
  tabActive:     {},
  tabIcon:       { fontSize: 14 },
  tabLabel:      { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium },
  tabIndicator:  {
    position: 'absolute',
    bottom: 0,
    left: spacing.md,
    right: spacing.md,
    height: 2,
    borderTopLeftRadius: 2,
    borderTopRightRadius: 2,
  },
});
