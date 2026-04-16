# Journal: Remove Management Access to `/schedule-changes`
**Date:** 2026-04-16

---

## Context

Investigating the management role's navbar revealed two routes both surfacing a schedule change request approval queue. `/schedule` already handled it completely via `ScheduleManagementView` (with heatmap, age badges, PTO queue). `/schedule-changes` gave management a narrower duplicate of the same queue with no additional capability.

Also identified: `dispatch` was missing from `/schedule-changes` allowedRoles despite being a dispatched role with a legitimate need to submit schedule change requests.

---

## Fixes Applied

**File:** `frontend/src/App.tsx`

Removed `management`, added `dispatch` from the `/schedule-changes` `ProtectedRoute`:

```tsx
// Before
allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'management', 'admin']}

// After
allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'admin']}
```

---

**File:** `frontend/src/components/layout/Navbar.tsx`

Updated `canAccessScheduleChanges` to remove `management`, add `dispatch`:

```typescript
// Before
const canAccessScheduleChanges = isFieldStaff || groups.some(role => ['management', 'admin'].includes(role));

// After
const canAccessScheduleChanges = isFieldStaff || groups.includes('dispatch') || groups.includes('admin');
```

The Navbar comment was also updated to explain the rationale.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/App.tsx` | Remove `management`, add `dispatch` from `/schedule-changes` allowedRoles |
| `frontend/src/components/layout/Navbar.tsx` | Remove `management`, add `dispatch` from `canAccessScheduleChanges`; update comment |
