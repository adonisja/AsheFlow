# ADR-023: Role-Based Home Routing

**Date:** 2026-04-14
**Status:** Accepted

---

## Context

The application serves seven distinct roles, each with a dedicated landing page. The navbar Home link and the `"/"` route both sent every user to the generic `<Dashboard>` component regardless of role. Admin users landing on `/` saw a multi-view widget dashboard instead of their `/admin` panel. Dispatch users saw the same. Trainers and trainees had dedicated dashboards they could only reach by navigating manually.

Management was also initially left routing to `"/"` — but `ManagementView` is a rich, role-specific operations dashboard (incidents, walker performance, training pipeline, fleet compliance). It has the same claim to a dedicated route as admin and dispatch. A `/management` route was added and `ManagementView` was promoted from an embedded Dashboard component to a standalone page with its own header.

---

## Decision

### 1. `homeRoute` in Navbar

The Home NavLink target is now computed from the authenticated user's Cognito groups:

```typescript
const homeRoute = (() => {
  if (groups.includes('admin'))       return '/admin';
  if (groups.includes('dispatch'))    return '/dispatch';
  if (groups.includes('management'))  return '/management';
  if (groups.includes('trainer'))     return '/trainer-dashboard';
  if (groups.includes('trainee'))     return '/my-training';
  return '/';
})();
```

Priority order reflects operational importance — admin and dispatch have the most role-specific tooling and should never land on the generic view.

### 2. `RoleRedirect` at `"/"`

The `"/"` route now renders `<RoleRedirect>` instead of `<Dashboard>` directly:

```typescript
function RoleRedirect() {
  const { groups } = useAuth();
  if (groups.includes('admin'))       return <Navigate to="/admin" replace />;
  if (groups.includes('dispatch'))    return <Navigate to="/dispatch" replace />;
  if (groups.includes('management'))  return <Navigate to="/management" replace />;
  if (groups.includes('trainer'))     return <Navigate to="/trainer-dashboard" replace />;
  if (groups.includes('trainee'))     return <Navigate to="/my-training" replace />;
  return <Dashboard />;
}
```

`replace` is used so the redirect does not push an extra entry onto the browser history stack — the back button skips over `/` rather than bouncing the user between it and their home page.

Drivers and walkers fall through to `<Dashboard>` (worker view) — they have no role-specific home page beyond the shared overview.

---

## Consequences

**Positive:**
- Navigating to `localhost:3000` after login immediately delivers the role-appropriate page.
- The Home navbar button takes every role to their primary tool, not a lowest-common-denominator page.
- Adding a new role with a dedicated home requires one line in `homeRoute` and one line in `RoleRedirect` — both in the same priority-ordered structure.

**Trade-off:**
- The generic `<Dashboard>` at `/` is still reachable by admin/dispatch/trainer/trainee if they navigate directly (e.g. type the URL). `RoleRedirect` bounces them away, but they could force-navigate back. This is acceptable — no data is exposed that they shouldn't see, and the Dashboard has its own role-branched rendering.

---

## Role → Home Mapping

| Role | Home |
|---|---|
| admin | `/admin` |
| dispatch | `/dispatch` |
| management | `/management` |
| trainer | `/trainer-dashboard` |
| trainee | `/my-training` |
| driver | `/` |
| walker | `/` |
