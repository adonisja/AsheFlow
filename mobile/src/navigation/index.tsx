import React, { useState, useEffect, useCallback, createContext, useContext } from 'react';
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
import FieldOpsScreen           from '@screens/FieldOps/FieldOpsScreen';
import ScheduleScreen           from '@screens/Schedule/ScheduleScreen';
import NotificationsScreen      from '@screens/Notifications/NotificationsScreen';
import IncidentsScreen          from '@screens/Incidents/IncidentsScreen';
import TrainerDashboard         from '@screens/Trainer/TrainerDashboard';
import TraineeDashboard         from '@screens/Trainee/TraineeDashboard';
import AnchorPointTab           from '@screens/AnchorPoints/AnchorPointTab';
import PreferencesScreen        from '@screens/Preferences/PreferencesScreen';
import ScheduleChangesScreen    from '@screens/ScheduleChanges/ScheduleChangesScreen';
import WalkerDashboard          from '@screens/Walker/WalkerDashboard';
import DriverSurveyScreen       from '@screens/DriverSurvey/DriverSurveyScreen';
import MyAccountScreen          from '@screens/Profile/MyAccountScreen';
import RouteSortScreen          from '@screens/Trainer/RouteSortScreen';
import CrewMemberDetailScreen   from '@screens/Trainer/CrewMemberDetailScreen';
import ReattemptScreen          from '@screens/Trainer/ReattemptScreen';

// ── Role constants ────────────────────────────────────────────────────────────
// Moved to ./roles (cycle-free module) — screens must import from
// '@navigation/roles', never from this file (it imports every screen, so a
// screen importing back from here evaluates the constant as undefined).
// Re-exported for existing imports within this file's consumers.
export * from './roles';
import { TAB_GATES } from './roles';
import {
  FIELD_OPS_ROLES, ANCHOR_POINT_ROLES, PREFERENCES_ROLES, SCHEDULE_ROLES,
  SCHEDULE_CHANGE_ROLES, INCIDENT_ROLES, TRAINER_ROLES, TRAINEE_ROLES,
  WALKER_ROLES, ROUTE_SORT_ROLES, DRIVER_SURVEY_ROLES,
  GEAR_ROLES, MY_ROUTE_TAB_ROLES, REATTEMPT_ROLES, TRUCK_BUILDINGS_ROLES,
  TOTE_ADDRESS_ROLES,
  WORKFORCE_ROUTE_ROLES,
} from './roles';
import GearRequestsScreen from '@screens/Gear/GearRequestsScreen';
import MyRouteTabScreen from '@screens/Trainee/MyRouteScreen';
import TruckBuildingsScreen from '@screens/Walker/TruckBuildingsScreen';
import ToteAddressScreen from '@screens/Captain/ToteAddressScreen';
import MyWorkforceRouteScreen from '@screens/Walker/MyWorkforceRouteScreen';
import MfaRequiredScreen        from '@screens/MfaRequiredScreen';

// ── Tab-switch context (lets child screens navigate to a different tab) ───────
const TabSwitchContext = createContext<(key: string) => void>(() => {});
export const useTabSwitch = () => useContext(TabSwitchContext);

// ── Navigator param lists ─────────────────────────────────────────────────────
export type RootStackParamList = {
  Auth: undefined;
  Main: undefined;
  /** ADR-381 D2 — shown INSTEAD OF Main when the grace period has closed. */
  MfaRequired: undefined;
};

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

// ADR-216 phase 2: AP Sort list + per-employee route detail (crew drill-down).
export type RouteSortStackParamList = {
  RouteSortMain: undefined;
  CrewMemberDetail: { routeId: string; memberName: string };
};

const RootStack      = createNativeStackNavigator<RootStackParamList>();
const HomeStack      = createNativeStackNavigator<HomeStackParamList>();
const TrainerStack   = createNativeStackNavigator<TrainerStackParamList>();
const TraineeStack   = createNativeStackNavigator<TraineeStackParamList>();
const RouteSortStack = createNativeStackNavigator<RouteSortStackParamList>();

// ── Tab definition ────────────────────────────────────────────────────────────
type TabDef = {
  key: string;
  label: string;
  icon: string;
  roles: readonly string[];
  component: React.ComponentType<any>;
  /** ADR-289: capability key this tab needs, checked against
   *  GET /companies/my-capabilities. Absent = always available.
   *
   *  Deliberately NOT in navigation/roles.ts. That module imports nothing on
   *  purpose — constants there once lived here and created a require cycle that
   *  made a role constant `undefined` at import time, showing Field Ops to every
   *  role. Mode is a second filter applied at RENDER (see visibleTabs), never
   *  folded into the role constants. */
  feature?: string;
};

const ALL_TABS: TabDef[] = [
  { key: 'Home',            label: 'Home',            icon: '🏠', component: HomeNavigator, ...TAB_GATES['Home'] },
  { key: 'FieldOps',        label: 'Field Ops',        icon: '🔧', component: FieldOpsScreen, ...TAB_GATES['FieldOps'] },
  { key: 'AnchorPoints',    label: 'Anchor Point',     icon: '📍', component: AnchorPointTab, ...TAB_GATES['AnchorPoints'] },
  { key: 'Training',        label: 'Training',         icon: '📋', component: TrainerNavigator, ...TAB_GATES['Training'] },
  { key: 'RouteSort',       label: 'Route Sort',       icon: '🗺️', component: RouteSortNavigator, ...TAB_GATES['RouteSort'] },
  { key: 'MyRoute',         label: 'My Route',         icon: '🧭', component: MyRouteTabScreen, ...TAB_GATES['MyRoute'] },
  { key: 'Reattempts',      label: 'Reattempts',       icon: '🔁', component: ReattemptScreen, ...TAB_GATES['Reattempts'] },
  // ADR-291: the workforce sort's INPUT. Gated on `workforce_sort`, so it is
  // absent for a full-mode tenant — there the manifest supplies this and a
  // captain typing addresses by hand would be duplicate, contradictory work.
  { key: 'ToteAddresses',   label: 'Tote Addresses',   icon: '📮', component: ToteAddressScreen, ...TAB_GATES['ToteAddresses'] },
  // ADR-297: the workforce sort's OUTPUT, for the person who walks it. Same
  // capability gate as the input above, because they are two ends of one
  // pipeline — a tenant with a package feed gets full mode's MyRoute instead,
  // which is a different screen (stops, not totes) on a different gate.
  { key: 'WorkforceRoute',  label: 'My Route',         icon: '🧭', component: MyWorkforceRouteScreen, ...TAB_GATES['WorkforceRoute'] },
  { key: 'TruckBuildings',  label: 'Buildings',        icon: '🏢', component: TruckBuildingsScreen, ...TAB_GATES['TruckBuildings'] },
  { key: 'MyTraining',      label: 'My Training',      icon: '📚', component: TraineeNavigator, ...TAB_GATES['MyTraining'] },
  // ADR-289. Full-mode only: every sub-tab under it (My Route, Found) calls
  // endpoints registered under `_full_mode` — /rts/stops, /rts/packages,
  // /packages/intake — so in workforce mode the server 404s all of them and the
  // controls are dead. The workforce equivalent is the WorkforceRoute tab.
  //
  // A walker's own numbers live in Account (My Stats + Scorecard), not here.
  { key: 'Walker',          label: 'Walker',           icon: '🚶', component: WalkerDashboard, ...TAB_GATES['Walker'] },
  { key: 'DriverSurvey',   label: 'Survey',           icon: '📊', component: DriverSurveyScreen, ...TAB_GATES['DriverSurvey'] },
  { key: 'Schedule',        label: 'Schedule',         icon: '📅', component: ScheduleScreen, ...TAB_GATES['Schedule'] },
  { key: 'SchChanges',      label: 'Change Requests',  icon: '🔄', component: ScheduleChangesScreen, ...TAB_GATES['SchChanges'] },
  { key: 'Incidents',       label: 'Incidents',        icon: '⚠️', component: IncidentsScreen, ...TAB_GATES['Incidents'] },
  { key: 'Gear',            label: 'Gear',             icon: '🎒', component: GearRequestsScreen, ...TAB_GATES['Gear'] },
  { key: 'Preferences',     label: 'Preferences',      icon: '⚙️', component: PreferencesScreen, ...TAB_GATES['Preferences'] },
  { key: 'Notifications',   label: 'Notifications',    icon: '🔔', component: NotificationsScreen, ...TAB_GATES['Notifications'] },
  { key: 'Account',         label: 'Account',          icon: '👤', component: MyAccountScreen, ...TAB_GATES['Account'] },
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
      {/* The avatar tap on Home routes here. ProfileScreen was deleted: it duplicated
          MyAccountScreen's email-change flow (same two endpoints) while lacking password
          change, both performance cards, and the standard PageHeader. Keeping the route
          name preserves the tap target and the back gesture. */}
      <HomeStack.Screen name="Profile"          component={MyAccountScreen}       options={{ headerShown: false }} />
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

// ── Route Sort nested navigator (ADR-216 phase 2) ─────────────────────────────
// The AP Sort tab is a stack so a crew card can push the per-employee route
// detail (current → remaining → completed stops).
function RouteSortNavigator() {
  return (
    <RouteSortStack.Navigator screenOptions={{ headerShown: false }}>
      <RouteSortStack.Screen name="RouteSortMain"    component={RouteSortScreen} />
      <RouteSortStack.Screen name="CrewMemberDetail" component={CrewMemberDetailScreen} />
    </RouteSortStack.Navigator>
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
  // `mutedForeground`, not a fixed grey. #9CA3AF measured 2.54:1 on the LIGHT
  // tab bar — every inactive label in the app's primary navigation, below the
  // 4.5 floor. A fixed grey cannot serve both themes: it was picked against the
  // dark bar (6.75:1) and never rechecked against white. 5.27 / 8.04 now.
  label:       { fontSize: 10, color: c.mutedForeground, fontWeight: '500' },
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
  const { hasRole, hasFeature } = useAuth();

  // Two independent filters: ROLE (who you are) then FEATURE (what this company
  // has, ADR-289). hasFeature fails open while capabilities are unknown, so a
  // slow or failed call leaves the tabs intact rather than emptying the app.
  const visibleTabs = ALL_TABS.filter(t =>
    (t.roles.length === 0 || hasRole(...t.roles)) &&
    (!t.feature || hasFeature(t.feature))
  );

  const [activeKey, setActiveKey] = useState(visibleTabs[0]?.key ?? 'Home');

  // Remap 'NotificationsTab' alias so HomeScreen can switch to it by a stable name
  const switchTab = useCallback((key: string) => {
    const target = key === 'NotificationsTab' ? 'Notifications' : key;
    setActiveKey(target);
  }, []);

  // ADR-289: capabilities arrive AFTER the first render, so a tab that was
  // visible on mount can disappear a moment later. Without this the tab bar
  // highlights nothing while ActiveScreen silently falls back to Home — the
  // user sees the Home screen with no tab selected and no idea why.
  useEffect(() => {
    if (visibleTabs.length && !visibleTabs.some(t => t.key === activeKey)) {
      setActiveKey(visibleTabs[0].key);
    }
  }, [visibleTabs, activeKey]);

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
  const { isAuthenticated, isLoading, mfaStatus } = useAuth();

  /* ADR-381 D2 — a blocked user gets a screen INSTEAD OF the app, not a modal
     over it. Same idiom as the isAuthenticated swap below: the tab shell is
     unreachable, which is what blocked means. A modal would leave the tabs
     navigable behind it.

     Guarded on `blocked` alone. `enrolled === null` means Cognito could not be
     read, and mfaStatus is null before the first fetch returns -- neither is a
     reason to lock someone out of their shift. */
  const mfaBlocked = Boolean(mfaStatus?.blocked);
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
        {!isAuthenticated ? (
          <RootStack.Screen name="Auth" component={LoginScreen} />
        ) : mfaBlocked ? (
          <RootStack.Screen name="MfaRequired" component={MfaRequiredScreen} />
        ) : (
          <RootStack.Screen name="Main" component={MainShell} />
        )}
      </RootStack.Navigator>
    </NavigationContainer>
  );
}
