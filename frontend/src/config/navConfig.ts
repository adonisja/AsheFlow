import {
  Home, ClipboardCheck, BarChart2, Users, ScrollText, Building2, ClipboardList,
  MapPin, MessageSquare, Shield, ShoppingBag, AlertTriangle, Route, Calendar,
  RefreshCw, Settings, Activity, ShieldAlert, Star, Gavel, Package,
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
 * Roles: admin | management | dispatch | trainer | trainee | driver | walker | captain.
 * (super_admin is a separate app shell and not modeled here.)
 */

export type Role =
  | 'admin' | 'management' | 'dispatch' | 'trainer' | 'trainee' | 'driver' | 'walker'
  // ADR-274 D20: captain is a truck's route lead (ADR-256). It was absent from
  // this union entirely, so a captain had no nav tabs and homeRouteForGroups
  // dropped them to '/' with no dashboard.
  | 'captain';

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

// A captain crews a truck like the rest of field staff; what makes them a
// captain is route-lead AUTHORITY (ADR-256 D5), not a different shift.
const ALL_FIELD: Role[] = ['driver', 'walker', 'trainer', 'trainee', 'captain'];

/**
 * Canonical nav items. Each `roles` array is the authoritative access set for
 * that path — App.tsx gates derive from it.
 *
 * Display order is NOT this literal's order: navItemsForGroups sorts by label,
 * so an entry may be appended anywhere. The Navbar prepends the role's
 * Dashboard as the first tab, which is why no dashboard route appears here.
 */
export const NAV_ITEMS: NavItem[] = [
  { path: '/dispatch',              label: 'Assignments',       icon: ClipboardCheck, roles: ['admin', 'dispatch'] },
  { path: '/anchor-points',         label: 'Anchor Points',     icon: MapPin,         roles: ['admin', 'dispatch', 'driver', 'captain'] },
  { path: '/assets',                label: 'Assets',            icon: Users,          roles: ['admin', 'management'] },
  { path: '/audit',                 label: 'Audit Log',         icon: ScrollText,     roles: ['admin', 'management'] },
  { path: '/building-profiles',     label: 'Buildings',         icon: Building2,      roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  // ADR-277 D3: truck-scoped, alongside the company-wide list above. Field
  // roles + sign-off roles — the same union that gates the endpoint.
  // Explicit list, NOT ...ALL_FIELD: that spread includes `driver`, and a
  // driver has no business here for the reason _allow_delivery already
  // records — "logistics role, does not walk blocks or assess difficulty".
  // Spreading it also silently drifted the nav gate away from the route
  // gate, which is what test_nav_and_route_gates_agree caught.
  { path: '/my-truck-buildings',    label: 'My truck buildings', icon: Building2,     roles: ['admin', 'dispatch', 'management', 'captain', 'walker', 'trainer', 'trainee'] },
  { path: '/vehicle-compliance',    label: 'Compliance',        icon: ShieldAlert,    roles: ['admin', 'management'] },
  { path: '/crew-status',           label: 'Crew Status',       icon: Users,          roles: ['admin', 'dispatch', 'management', 'driver', 'trainer', 'captain'] },
  // /dispatch-home has NO tab: it is dispatch's Dashboard landing
  // (homeRouteForGroups), and every role has its own scoped home dashboard —
  // admin lands on /admin and doesn't need dispatch's. Route access is gated
  // in App.tsx (admin retains URL access per the full-access role model).
  { path: '/driver-surveys',        label: 'Driver Surveys',    icon: ClipboardList,  roles: ['admin', 'management'] },
  { path: '/feedback',              label: 'Feedback',          icon: MessageSquare,  roles: ['admin'] },
  { path: '/field-ops',             label: 'Field Ops',         icon: Shield,         roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  { path: '/field-packages',        label: 'Field Packages',    icon: Package,        roles: ['admin', 'dispatch', 'management'] },
  { path: '/gear',                  label: 'Gear',              icon: ShoppingBag,    roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  { path: '/incidents',             label: 'Incidents',         icon: AlertTriangle,  roles: ['admin', 'dispatch', 'management', ...ALL_FIELD] },
  { path: '/my-route',              label: 'My Route',          icon: Route,          roles: ['walker', 'trainee'] },
  { path: '/my-training',           label: 'My Training',       icon: ClipboardCheck, roles: ['trainee'] },
  { path: '/my-quiz',               label: 'Quiz',              icon: ClipboardCheck, roles: ['trainee'], when: c => c.hasActiveQuiz },
  { path: '/phase4-observation',    label: 'Phase 4',           icon: ClipboardCheck, roles: ['admin', 'trainer'], when: c => c.trainerPhase === 4 },
  { path: '/preferences',           label: 'Preferences',       icon: Settings,       roles: ['driver', 'walker', 'trainer', 'trainee'] },
  { path: '/scorecards',            label: 'Scorecards',        icon: Star,           roles: ['admin', 'dispatch', 'management'] },
  { path: '/schedule',              label: 'Schedule',          icon: Calendar,       roles: ['admin', 'management', ...ALL_FIELD] },
  { path: '/schedule-changes',      label: 'Schedule Changes',  icon: RefreshCw,      roles: ['admin', 'dispatch', 'driver', 'trainer', 'trainee', 'walker', 'captain'] },
  { path: '/settings',              label: 'Settings',          icon: Settings,       roles: ['admin'] },
  { path: '/sort',                  label: 'Station Sort',      icon: Route,          roles: ['admin', 'dispatch', 'driver'] },
  // ADR-273: cross-run algorithm telemetry used to justify a tenant-wide tuning
  // change. Management+admin only — dispatch is not management (ADR-242).
  { path: '/sort-metrics',          label: 'Sort Metrics',      icon: Activity,       roles: ['admin', 'management'] },
  { path: '/walker-sort',           label: 'AP Sort',           icon: Activity,       roles: ['admin', 'dispatch', 'management', 'driver', 'trainer', 'captain'] },
  { path: '/trainee-management',    label: 'Trainees',          icon: ClipboardCheck, roles: ['admin', 'management'] },
  // /trainer-dashboard has NO nav tab. It is a trainer's Dashboard landing
  // (homeRouteForGroups), so trainers reach it without one; the admin tab was
  // removed on request — admin oversight of training lives on /trainee-management,
  // and a second entry point to a role-specific dashboard was noise.
  // The ROUTE remains (App.tsx) so trainer landing and direct links still work.
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
  return NAV_ITEMS
    .filter(item => {
      if (!item.roles.some(r => roleSet.has(r))) return false;
      if (item.when && !item.when(ctx)) return false;
      return true;
    })
    // Sorted HERE rather than relying on the literal's order. The list was
    // documented as alphabetical and had drifted — nothing enforced it, so
    // every append landed wherever it was pasted. The Dashboard tab is
    // prepended separately by the Navbar and is deliberately not part of this.
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Role-specific landing route for the Dashboard link. */
export function homeRouteForGroups(groups: string[]): string {
  if (groups.includes('admin'))      return '/admin';
  // Before this, a captain fell through to '/' and got WorkerView — a
  // driver/walker page with none of their route-lead signals.
  if (groups.includes('captain'))    return '/captain-dashboard';
  if (groups.includes('dispatch'))   return '/dispatch-home';
  if (groups.includes('management')) return '/management';
  if (groups.includes('trainer'))    return '/trainer-dashboard';
  if (groups.includes('trainee'))    return '/my-training';
  return '/';
}

export const HOME_ICON = Home;
