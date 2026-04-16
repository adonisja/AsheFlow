# Journal: Role-Based Home Routing and Roster Pagination
**Date:** 2026-04-14

---

## Issues Addressed

Two separate issues fixed in this session.

---

## Issue 1 — Workforce Breakdown Showing Wrong Counts

### Symptom

Admin dashboard Workforce Breakdown showed 1 trainee. Training Sessions Today card showed 6 trainees actively being trained.

### Root Cause

`GET /employees/` uses the `Pagination` dependency with a default `limit=100`. With 193 employees in the database (119 walkers, 49 trainers, 17 drivers, 6 trainees, etc.), the first 100 rows returned by the default query ordering left only 1 trainee in the slice. The frontend took `r.data` as-is and computed role counts from a truncated list.

The workforce breakdown must count all employees to be meaningful. Passing `limit=500` (within the backend's enforced cap) retrieves the full roster in one request.

### Fix

`AdminDashboard.tsx`: employees fetch changed to `/employees/?include_inactive=true&limit=500`.

---

## Issue 2 — Employee Roster Rendering All Rows as One Long List

### Symptom

With 193 employees, the admin roster and management Assets/PeopleTab each rendered a single unbroken table — no pagination, requiring significant scrolling.

### Fix

Added client-side pagination to both roster views. Data is fully loaded (needed for accurate counts / search / filter), then sliced for display.

**AdminDashboard.tsx** — `ROSTER_PAGE_SIZE = 50`:
- `rosterPage` state (0-indexed)
- Table body slices `employees` to current page's 50 rows
- Pagination bar: "1–50 of 193 employees" label, numbered page buttons, Previous/Next
- Only renders when total employees exceed one page

**Assets.tsx PeopleTab** — `PEOPLE_PAGE_SIZE = 25`:
- `page` state + `totalPages` / `currentPage` / `pageSlice` derived values
- Search and role filter both reset `page` to 0 on change (prevents landing on a blank page after narrowing)
- Same pagination bar pattern, nested inside the card below the table
- Employee fetch updated to `limit=500` (was hitting the same default 100 cap as admin)

---

## Issue 3 — Home Navbar Link Redirecting to Generic `/` Instead of Role Homepage

### Symptom

Clicking Home in the navbar took all users to `http://localhost:3000/`, which renders the generic `<Dashboard>` component. Admin users expected to land on `/admin`, dispatch on `/dispatch`, trainer on `/trainer-dashboard`, etc.

### Root Cause

The Home `NavLink` was hardcoded `to="/"` for every role. The `"/"` route always rendered `<Dashboard>` regardless of who was logged in.

### Fix

**Navbar.tsx** — added `homeRoute` computed value:

```typescript
const homeRoute = (() => {
  if (groups.includes('admin'))      return '/admin';
  if (groups.includes('dispatch'))   return '/dispatch';
  if (groups.includes('management')) return '/';
  if (groups.includes('trainer'))    return '/trainer-dashboard';
  if (groups.includes('trainee'))    return '/my-training';
  return '/';
})();
```

Both the desktop and mobile Home `NavLink` now use `to={homeRoute}`.

**App.tsx** — replaced the `"/"` route's `<Dashboard>` with `<RoleRedirect>`:

```typescript
function RoleRedirect() {
  const { groups } = useAuth();
  if (groups.includes('admin'))    return <Navigate to="/admin" replace />;
  if (groups.includes('dispatch')) return <Navigate to="/dispatch" replace />;
  if (groups.includes('trainer'))  return <Navigate to="/trainer-dashboard" replace />;
  if (groups.includes('trainee'))  return <Navigate to="/my-training" replace />;
  return <Dashboard />;
}
```

This handles direct URL entry (`localhost:3000`) and post-login redirects, not just the navbar button. Management, drivers, and walkers still receive `<Dashboard>` since `/` is their correct home.

---

## Issue 4 — Management Missing a Dedicated Home Route (Follow-up Fix)

`ManagementView` is a rich operations dashboard — incident trends, walker performance, training pipeline, fleet compliance. It was initially left routing to `"/"` under the assumption that the generic `<Dashboard>` wrapper was close enough. It isn't: management has the same claim to a dedicated route as admin and dispatch.

**Fix:**
- Added `/management` route in `App.tsx` (accessible to management and admin)
- `RoleRedirect` now sends management to `/management` instead of falling through to `<Dashboard>`
- `homeRoute` in Navbar updated to `/management` for the management group
- `ManagementView` promoted from embedded component to standalone page — added a greeting header with the user's name and today's date, matching the pattern of other role dashboards

---

## Role → Home Mapping

| Role | Home route |
|---|---|
| admin | `/admin` |
| dispatch | `/dispatch` |
| management | `/management` |
| trainer | `/trainer-dashboard` |
| trainee | `/my-training` |
| driver / walker | `/` (Dashboard, worker view) |

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/AdminDashboard.tsx` | `limit=500` on employees fetch; roster pagination (50/page) |
| `frontend/src/pages/Assets.tsx` | `limit=500` on employees fetch; PeopleTab pagination (25/page) with search/filter page reset |
| `frontend/src/components/layout/Navbar.tsx` | `homeRoute` computed from groups (management → `/management`); Home NavLink uses it on desktop and mobile |
| `frontend/src/App.tsx` | `RoleRedirect` component; `/management` route added; `"/"` route renders `RoleRedirect` instead of `<Dashboard>` directly |
| `frontend/src/components/dashboard/ManagementView.tsx` | Added greeting header (user name + date); imports `useAuth` and `LayoutDashboard` icon |
