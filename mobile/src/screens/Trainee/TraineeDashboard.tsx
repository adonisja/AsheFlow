import React, { useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';

import TraineeTodayScreen    from './TraineeTodayScreen';
import TraineeHistoryScreen  from './TraineeHistoryScreen';
import MyRouteScreen         from './MyRouteScreen';
import GraduationQuizScreen  from './GraduationQuizScreen';
import MyCredentialsScreen   from './MyCredentialsScreen';

type Tab = 'today' | 'history' | 'myroute' | 'quiz' | 'credentials';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'today',       label: 'Today',       icon: '📚' },
  { key: 'history',     label: 'History',     icon: '📂' },
  { key: 'myroute',     label: 'My Route',    icon: '🗺️' },
  { key: 'quiz',        label: 'Quiz',        icon: '🎓' },
  { key: 'credentials', label: 'Credentials', icon: '🔑' },
];

export default function TraineeDashboard() {
  const c = useColors();
  const [activeTab, setActiveTab] = useState<Tab>('today');
  const s = styles(c);

  // Header title transitions with the active tab (ADR-207); child screens render
  // headerless so there's no duplicate title.
  const HEADER_TITLE: Record<Tab, string> = {
    today:       "Today's Training",
    history:     'Training History',
    myroute:     'My Route',
    quiz:        'Graduation Quiz',
    credentials: 'My Credentials',
  };

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <PageHeader title={HEADER_TITLE[activeTab] ?? 'My Training'} />

      <View style={s.tabBarWrap}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={s.tabBarScroll}
        >
          {TABS.map(tab => {
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
        {activeTab === 'today'       && <TraineeTodayScreen />}
        {activeTab === 'history'     && <TraineeHistoryScreen />}
        {activeTab === 'myroute'     && <MyRouteScreen />}
        {activeTab === 'quiz'        && <GraduationQuizScreen />}
        {activeTab === 'credentials' && <MyCredentialsScreen />}
      </View>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:         { flex: 1, backgroundColor: c.background },
  header:       {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
    backgroundColor: c.background,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  title:        { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  tabBarWrap:   { backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  tabBarScroll: { paddingHorizontal: spacing.sm },
  tab:          { alignItems: 'center', flexDirection: 'row', gap: 5, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, position: 'relative' },
  tabActive:    {},
  tabIcon:      { fontSize: 14 },
  tabLabel:     { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium },
  tabIndicator: { position: 'absolute', bottom: 0, left: spacing.md, right: spacing.md, height: 2, borderTopLeftRadius: 2, borderTopRightRadius: 2 },
});
