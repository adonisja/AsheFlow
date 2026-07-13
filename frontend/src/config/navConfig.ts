import {
  Home, ClipboardCheck, BarChart2, Users, ScrollText, Building2, ClipboardList,
  MapPin, MessageSquare, Shield, ShoppingBag, AlertTriangle, Route, Calendar,
  RefreshCw, Settings, Activity, ShieldAlert, Star,
  type LucideIcon,
} from 'lucide-react';

/**
 * Single source of truth for role-based navigation AND route access
 * (access-control audit, 2026-07-03).
 *
 * Both the desktop and mobile navs render from `NAV_ITEMS`, and the App.tsx
 * route gates read their allowed-role sets from `routeRoles(path)` — so a nav
 * tab and its route can never disagree again. Previously desktop nav, mobile
 * nav, and route gates were three hand-maintained lists that silently drifted.
 *
 * Roles: admin | management | dispatch | trainer | trainee | driver | walker.
 * (super_admin is a separate app shell and not modeled here.)
 */

export type Role =
  | 'admin' | 'management' | 'dispatch' | 'trainer' | 'trainee' | 'driver' | 'walker';

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  roles: Role[];
  /** Optional predicate for conditional visibility (e.g. trainer phase 4). */
  when?: (ctx: NavContext) => boolean;
}

export interface NavContext {
  trainerPhase: number | null;
  hasActiveQuiz: boolean;
}

const ALL_FIELD: Role[] = ['driver', 'walker', 'trainer', 'trainee'];

/**
 * Canonical nav items, alphabetical within the list (the Navbar groups by role
 * and orders alphabetically). Each `roles` array is the authoritative access
 * set for that path — App.tsx gates derive from it.
 */
export const NAV_ITEMS: NavItem[] = [
  { path: '/dispatch',              label: 'Assignments',       icon: ClipboardCheck, roles: ['admin', 'dispatch'] },
  { path: '/operations-analytics',  label: 'Analytics',         icon: BarChart2,      roles: ['admin', 'dispatch', 'management'] },
  { path: '/anchor-points',         label: 'Anchor Points',     icon: MapPin,         roles: ['admin', 'dispatch', 'driver'] },
  { path: '/assets',                label: 'Assets',            icon: Users,          roles: ['admin', 'management'] },
  { path: '/audit',                 label: 'Audit Log',         icon: ScrollText,     roles: ['admin', 'management'] },
  { path: '/building-profiles',     label: 'Buildings',         icon: Building2,      roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  { path: '/vehicle-compliance',    label: 'Compliance',        icon: ShieldAlert,    roles: ['admin', 'management'] },
  { path: '/crew-status',           label: 'Crew Status',       icon: Users,          roles: ['admin', 'dispatch', 'management', 'driver', 'trainer'] },
  // /dispatch-home has NO tab: it is dispatch's Dashboard landing
  // (homeRouteForGroups), and every role has its own scoped home dashboard —
  // admin lands on /admin and doesn't need dispatch's. Route access is gated
  // in App.tsx (admin retains URL access per the full-access role model).
  { path: '/driver-surveys',        label: 'Driver Surveys',    icon: ClipboardList,  roles: ['admin', 'management'] },
  { path: '/feedback',              label: 'Feedback',          icon: MessageSquare,  roles: ['admin'] },
  { path: '/field-ops',             label: 'Field Ops',         icon: Shield,         roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  { path: '/gear',                  label: 'Gear',              icon: ShoppingBag,    roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  { path: '/incidents',             label: 'Incidents',         icon: AlertTriangle,  roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  { path: '/my-route',              label: 'My Route',          icon: Route,          roles: ['walker', 'trainee'] },
  { path: '/my-training',           label: 'My Training',       icon: ClipboardCheck, roles: ['trainee'] },
  { path: '/my-quiz',               label: 'Quiz',              icon: ClipboardCheck, roles: ['trainee'], when: c => c.hasActiveQuiz },
  { path: '/phase4-observation',    label: 'Phase 4',           icon: ClipboardCheck, roles: ['admin', 'trainer'], when: c => c.trainerPhase === 4 },
  { path: '/preferences',           label: 'Preferences',       icon: Settings,       roles: ['driver', 'walker', 'trainer', 'trainee'] },
  { path: '/schedule',              label: 'Schedule',          icon: Calendar,       roles: ['admin', 'management', ...ALL_FIELD] },
  { path: '/schedule-changes',      label: 'Schedule Changes',  icon: RefreshCw,      roles: ['admin', 'dispatch', 'driver', 'trainer', 'trainee', 'walker'] },
  { path: '/settings',              label: 'Settings',          icon: Settings,       roles: ['admin'] },
  { path: '/sort',                  label: 'Station Sort',      icon: Route,          roles: ['admin', 'dispatch', 'driver'] },
  { path: '/walker-sort',           label: 'AP Sort',           icon: Activity,       roles: ['admin', 'dispatch', 'management', 'driver', 'trainer'] },
  { path: '/trainee-management',    label: 'Trainees',          icon: ClipboardCheck, roles: ['admin', 'management'] },
  // /trainer-dashboard is a trainer's Dashboard landing (homeRouteForGroups),
  // so it needs no separate tab for trainers. Kept as an admin tab only, since
  // admin's Dashboard lands on /admin.
  { path: '/trainer-dashboard',     label: 'Trainer Dash',      icon: ClipboardCheck, roles: ['admin'] },
  { path: '/walker-performance',    label: 'Walkers',           icon: Star,           roles: ['admin', 'management'] },
];

/** All roles that may access a path (empty = no gate registered here). */
export function routeRoles(path: string): Role[] {
  const item = NAV_ITEMS.find(i => i.path === path);
  return item ? item.roles : [];
}

/** The nav items a set of Cognito groups may see, respecting `when` predicates.
 * Admin is shown its own curated set (it does not inherit every role's tabs). */
export function navItemsForGroups(groups: string[], ctx: NavContext): NavItem[] {
  const roleSet = new Set(groups as Role[]);
  return NAV_ITEMS.filter(item => {
    if (!item.roles.some(r => roleSet.has(r))) return false;
    if (item.when && !item.when(ctx)) return false;
    return true;
  });
}

/** Role-specific landing route for the Dashboard link. */
export function homeRouteForGroups(groups: string[]): string {
  if (groups.includes('admin'))      return '/admin';
  if (groups.includes('dispatch'))   return '/dispatch-home';
  if (groups.includes('management')) return '/management';
  if (groups.includes('trainer'))    return '/trainer-dashboard';
  if (groups.includes('trainee'))    return '/my-training';
  return '/';
}

export const HOME_ICON = Home;
