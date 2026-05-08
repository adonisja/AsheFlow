# ADR-073 — Role Protection Guards and Trainer Promotion/Demotion

**Date:** 2026-05-08  
**Status:** Accepted

## Context

Management users should only have authority over field staff. They must not be able to view, create, edit, activate, or deactivate management or admin accounts. Additionally, the walker→trainer promotion path needed a formal, auditable flow rather than a free-form role edit.

## Decision

### Backend (`backend/app/routers/employees.py`)

1. **`PROTECTED_ROLES = {"management", "admin"}`** constant defined at module level.
2. **`_assert_not_protected(caller_groups, target_role)`** helper raises 403 if the target role is in `PROTECTED_ROLES` and the caller is not admin.
3. Guards added to:
   - `GET /employees/` — management callers get `Employee.role.notin_(PROTECTED_ROLES)` filter applied
   - `GET /employees/{id}` — 403 if caller is management and target has protected role
   - `PUT /employees/{id}` — `_assert_not_protected` before any mutation
   - `PUT /employees/{id}/deactivate` — same guard
   - `PUT /employees/{id}/reactivate` — same guard
4. **`POST /employees/{id}/promote`** — walker→trainer only; syncs Cognito group; fires `role_change` in-app notification to the employee naming the caller.
5. **`POST /employees/{id}/demote`** — trainer→walker only; same pattern.

Cognito group sync is best-effort (logged on failure, does not roll back the DB change) because the DB is authoritative and groups are re-synced on next token refresh.

### Frontend (`frontend/src/pages/Assets.tsx`)

1. `isManagement` flag: `groups.includes('management') && !isAdmin`.
2. `visible` filter skips `PROTECTED_ROLES` rows when `isManagement`.
3. `allowedRoles` passed to `EmployeeModal` — management callers see only `FIELD_ROLES` in the role select.
4. Edit and Deactivate/Reactivate buttons hidden for protected-role rows when caller is management.
5. **Promote** button shown on active walker rows; **Demote** button shown on active trainer rows. Both show a confirmation dialog before calling the API. Inline feedback ("Done" / "Failed") with full text in `title`.

## Consequences

- Management users have a clean, scoped view with no ability to affect admin/management accounts — enforced at both API and UI layers.
- Promotion/demotion is an explicit, confirmed action with an in-app notification to the affected employee.
- The `role_change` notification type is new but reuses the existing `Notification` model without schema changes.
- Admins retain full access to everything, consistent with ADR memory note on admin scope.
