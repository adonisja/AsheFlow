import React, { useState, useCallback, createContext, useContext } from 'react';
import {
  NavigationContainer,
} from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import {
  View, Text, TouchableOpacity, ScrollView, StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── Screens ───────────────────────────────────────────────────────────────────
import LoginScreen              from '@screens/Auth/LoginScreen';
import HomeScreen               from '@screens/Home/HomeScreen';
import TodayAssignmentScreen    from '@screens/Home/TodayAssignmentScreen';
import ProfileScreen            from '@screens/Profile/ProfileScreen';
import FieldOpsScreen           from '@screens/FieldOps/FieldOpsScreen';
import ScheduleScreen           from '@screens/Schedule/ScheduleScreen';
import NotificationsScreen      from '@screens/Notifications/NotificationsScreen';
import IncidentsScreen          from '@screens/Incidents/IncidentsScreen';
import TrainerDashboard         from '@screens/Trainer/TrainerDashboard';
import TraineeDashboard         from '@screens/Trainee/TraineeDashboard';
import AnchorPointsScreen       from '@screens/AnchorPoints/AnchorPointsScreen';
import PreferencesScreen        from '@screens/Preferences/PreferencesScreen';
import ScheduleChangesScreen    from '@screens/ScheduleChanges/ScheduleChangesScreen';
import WalkerDashboard          from '@screens/Walker/WalkerDashboard';
import LocationProfilesScreen   from '@screens/LocationProfiles/LocationProfilesScreen';
import DriverSurveyScreen       from '@screens/DriverSurvey/DriverSurveyScreen';
import MyAccountScreen          from '@screens/Profile/MyAccountScreen';
import RouteSortScreen          from '@screens/Trainer/RouteSortScreen';

// ── Role constants ────────────────────────────────────────────────────────────
// Moved to ./roles (cycle-free module) — screens must import from
// '@navigation/roles', never from this file (it imports every screen, so a
// screen importing back from here evaluates the constant as undefined).
// Re-exported for existing imports within this file's consumers.
export * from './roles';
import {
  FIELD_OPS_ROLES, ANCHOR_POINT_ROLES, PREFERENCES_ROLES, SCHEDULE_ROLES,
  SCHEDULE_CHANGE_ROLES, INCIDENT_ROLES, TRAINER_ROLES, TRAINEE_ROLES,
  WALKER_ROLES, LOCATION_PROFILE_ROLES, ROUTE_SORT_ROLES, DRIVER_SURVEY_ROLES,
  GEAR_ROLES,
} from './roles';
import GearRequestsScreen from '@screens/Gear/GearRequestsScreen';

// ── Tab-switch context (lets child screens navigate to a different tab) ───────
const TabSwitchContext = createContext<(key: string) => void>(() => {});
export const useTabSwitch = () => useContext(TabSwitchContext);

// ── Navigator param lists ─────────────────────────────────────────────────────
export type RootStackParamList = { Auth: undefined; Main: undefined };

export type HomeStackParamList = {
  HomeMain: undefined;
  TodayAssignment: undefined;
  Profile: undefined;
};

export type TrainerStackParamList = {
  TrainerDashboard: undefined;
};

export type TraineeStackParamList = {
  TraineeDashboard: undefined;
};

const RootStack    = createNativeStackNavigator<RootStackParamList>();
const HomeStack    = createNativeStackNavigator<HomeStackParamList>();
const TrainerStack = createNativeStackNavigator<TrainerStackParamList>();
const TraineeStack = createNativeStackNavigator<TraineeStackParamList>();

// ── Tab definition ────────────────────────────────────────────────────────────
type TabDef = {
  key: string;
  label: string;
  icon: string;
  roles: readonly string[];
  component: React.ComponentType<any>;
};

const ALL_TABS: TabDef[] = [
  { key: 'Home',            label: 'Home',            icon: '🏠', roles: [],                     component: HomeNavigator },
  { key: 'FieldOps',        label: 'Field Ops',        icon: '🔧', roles: FIELD_OPS_ROLES,         component: FieldOpsScreen },
  { key: 'AnchorPoints',    label: 'Anchor Points',    icon: '📍', roles: ANCHOR_POINT_ROLES,      component: AnchorPointsScreen },
  { key: 'Training',        label: 'Training',         icon: '📋', roles: TRAINER_ROLES,           component: TrainerNavigator },
  { key: 'RouteSort',       label: 'Route Sort',       icon: '🗺️', roles: ROUTE_SORT_ROLES,         component: RouteSortScreen },
  { key: 'MyTraining',      label: 'My Training',      icon: '📚', roles: TRAINEE_ROLES,           component: TraineeNavigator },
  { key: 'Walker',          label: 'Walker',           icon: '🚶', roles: WALKER_ROLES,            component: WalkerDashboard },
  { key: 'DriverSurvey',   label: 'Survey',           icon: '📊', roles: DRIVER_SURVEY_ROLES,     component: DriverSurveyScreen },
  { key: 'Schedule',        label: 'Schedule',         icon: '📅', roles: SCHEDULE_ROLES,          component: ScheduleScreen },
  { key: 'SchChanges',      label: 'Sch. Changes',     icon: '🔄', roles: SCHEDULE_CHANGE_ROLES,   component: ScheduleChangesScreen },
  { key: 'Incidents',       label: 'Incidents',        icon: '⚠️', roles: INCIDENT_ROLES,          component: IncidentsScreen },
  { key: 'Locations',       label: 'Locations',        icon: '📍', roles: LOCATION_PROFILE_ROLES,  component: LocationProfilesScreen },
  { key: 'Gear',            label: 'Gear',             icon: '🎒', roles: GEAR_ROLES,              component: GearRequestsScreen },
  { key: 'Preferences',     label: 'Preferences',      icon: '⚙️', roles: PREFERENCES_ROLES,       component: PreferencesScreen },
  { key: 'Notifications',   label: 'Notifications',    icon: '🔔', roles: [],                      component: NotificationsScreen },
  { key: 'Account',         label: 'Account',          icon: '👤', roles: [],                      component: MyAccountScreen },
];

// ── Home stack navigator ──────────────────────────────────────────────────────
function HomeNavigator() {
  const c = useColors();
  return (
    <HomeStack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: c.surface },
        headerTintColor: c.primary,
        headerTitleStyle: { fontWeight: fontWeight.semibold, color: c.foreground, fontSize: fontSize.base },
        headerShadowVisible: false,
      }}
    >
      <HomeStack.Screen name="HomeMain"         component={HomeScreen}            options={{ headerShown: false }} />
      <HomeStack.Screen name="TodayAssignment"  component={TodayAssignmentScreen} options={{ headerShown: false }} />
      <HomeStack.Screen name="Profile"          component={ProfileScreen}         options={{ headerShown: false }} />
    </HomeStack.Navigator>
  );
}

// ── Trainer nested navigator ──────────────────────────────────────────────────
function TrainerNavigator() {
  return (
    <TrainerStack.Navigator screenOptions={{ headerShown: false }}>
      <TrainerStack.Screen name="TrainerDashboard" component={TrainerDashboard} />
    </TrainerStack.Navigator>
  );
}

// ── Trainee nested navigator ──────────────────────────────────────────────────
function TraineeNavigator() {
  return (
    <TraineeStack.Navigator screenOptions={{ headerShown: false }}>
      <TraineeStack.Screen name="TraineeDashboard" component={TraineeDashboard} />
    </TraineeStack.Navigator>
  );
}

// ── Horizontal scroll tab bar ─────────────────────────────────────────────────
function HorizontalTabBar({
  tabs,
  activeKey,
  onSelect,
}: {
  tabs: TabDef[];
  activeKey: string;
  onSelect: (key: string) => void;
}) {
  const c = useColors();
  const insets = useSafeAreaInsets();
  const s = tabBarStyles(c);

  return (
    <View style={[s.container, { paddingBottom: insets.bottom }]}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={s.scroll}
      >
        {tabs.map(tab => {
          const active = tab.key === activeKey;
          return (
            <TouchableOpacity
              key={tab.key}
              style={[s.tab, active && s.tabActive]}
              onPress={() => onSelect(tab.key)}
              activeOpacity={0.7}
            >
              <Text style={[s.icon, active && s.iconActive]}>{tab.icon}</Text>
              <Text style={[s.label, active && s.labelActive]}>{tab.label}</Text>
              {active && <View style={s.indicator} />}
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );
}

const tabBarStyles = (c: ThemeColors) => StyleSheet.create({
  container: {
    backgroundColor: c.surface,
    borderTopWidth: 1,
    borderTopColor: c.border,
  },
  scroll:      { paddingHorizontal: spacing.sm, paddingTop: spacing.xs },
  tab:         { alignItems: 'center', paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, minWidth: 64, position: 'relative' },
  tabActive:   {},
  icon:        { fontSize: 20, marginBottom: 2 },
  iconActive:  {},
  label:       { fontSize: 10, color: '#9CA3AF', fontWeight: '500' },
  labelActive: { color: c.primary, fontWeight: '600' },
  indicator:   {
    position: 'absolute', top: 0,
    left: spacing.md, right: spacing.md,
    height: 2, backgroundColor: c.primary,
    borderBottomLeftRadius: 2, borderBottomRightRadius: 2,
  },
});

// ── Main app shell ────────────────────────────────────────────────────────────
function MainShell() {
  const { hasRole } = useAuth();

  const visibleTabs = ALL_TABS.filter(t =>
    t.roles.length === 0 || hasRole(...t.roles)
  );

  const [activeKey, setActiveKey] = useState(visibleTabs[0]?.key ?? 'Home');

  // Remap 'NotificationsTab' alias so HomeScreen can switch to it by a stable name
  const switchTab = useCallback((key: string) => {
    const target = key === 'NotificationsTab' ? 'Notifications' : key;
    setActiveKey(target);
  }, []);

  const ActiveScreen = visibleTabs.find(t => t.key === activeKey)?.component ?? HomeNavigator;

  return (
    <TabSwitchContext.Provider value={switchTab}>
      <View style={{ flex: 1 }}>
        <View style={{ flex: 1 }}>
          <ActiveScreen />
        </View>
        <HorizontalTabBar tabs={visibleTabs} activeKey={activeKey} onSelect={setActiveKey} />
      </View>
    </TabSwitchContext.Provider>
  );
}

// ── Root navigator ────────────────────────────────────────────────────────────
export default function RootNavigator() {
  const { isAuthenticated, isLoading } = useAuth();
  const c = useColors();

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: c.background }}>
        <ActivityIndicator size="large" color={c.primary} />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <RootStack.Navigator screenOptions={{ headerShown: false }}>
        {isAuthenticated ? (
          <RootStack.Screen name="Main" component={MainShell} />
        ) : (
          <RootStack.Screen name="Auth" component={LoginScreen} />
        )}
      </RootStack.Navigator>
    </NavigationContainer>
  );
}
