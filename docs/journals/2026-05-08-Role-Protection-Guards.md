# 2026-05-08 — Role Protection Guards & Trainer Promotion/Demotion

## What we built

Work Item B from the Phase 2 roadmap: role-scoped access control so management users cannot touch management/admin accounts, plus a formal promote/demote path for walker↔trainer transitions.

## Backend changes

- Added `PROTECTED_ROLES = {"management", "admin"}` and `_assert_not_protected()` guard helper to `employees.py`.
- `GET /employees/` now filters out protected-role rows for management callers via `.notin_()`.
- `PUT /{id}`, `PUT /{id}/deactivate`, `PUT /{id}/reactivate` all call the guard before mutating.
- New `POST /{id}/promote` and `POST /{id}/demote` endpoints:
  - Validate current role before transitioning (strict: walker→trainer, trainer→walker only)
  - Sync Cognito group (best-effort, logged on failure)
  - Create a `role_change` Notification for the affected employee naming the caller

## Frontend changes

- `isManagement` flag computed from `groups` (management but not admin).
- `visible` filter silently hides protected-role rows for management viewers.
- `EmployeeModal` now takes `allowedRoles` prop — management callers only see `FIELD_ROLES` in the role select.
- Edit/Deactivate/Reactivate buttons conditionally rendered based on target role and caller privilege.
- Promote/Demote buttons added to active walker/trainer rows respectively, each with a `useConfirm` dialog and inline feedback state.

## Key decisions

- Cognito sync failure is non-fatal: DB is authoritative, groups re-sync on next token refresh. Avoids a hard dependency on Cognito availability for an admin action.
- Promote/Demote are POST endpoints (not PUT) because they're state transitions with side effects, not field updates.
- `role_change` notification type reuses the existing Notification model — no migration needed.
- The confirmation dialog for Demote uses `variant: 'danger'` to signal the destructive intent; Promote uses `variant: 'default'`.
