# ADR-016: Role Architecture and Dashboard Restructure

**Date:** 2026-04-10
**Status:** Accepted
**Deciders:** adonisja

---

## Context

A comprehensive codebase audit revealed that the three elevated roles (dispatch, management, admin) were conflated into a single `isManagement` boolean in the frontend dashboard, causing all three to see the same interface despite having fundamentally different responsibilities. Additionally, multiple backend routers (trucks, time_off_requests, employee_off_days, employee_relationships, schedule, notifications) were completely unauthenticated, and several frontend routes had incorrect role gates (field-ops excluded walkers/trainers/trainees; admin was routed to operational forms intended for trainers and trainees).

---

## Decision

1. Separate the three elevated roles into distinct dashboard experiences with non-overlapping tool sets.
2. Add authentication to all currently unprotected backend routers.
3. Fix frontend route role gates to match the actual role definitions.
4. Build new backend reporting endpoints to support a data-driven management dashboard.
5. Build a dedicated `/admin` page for system-level tooling.

---

## Role Separation Rationale

### Why dispatch ≠ management

Dispatch is an operational role — they execute the day's plan. Management is a supervisory role — they evaluate outcomes and approve requests. Dispatch runs the algorithm and handles reassignment requests. Management reads reports and approves time-off. Giving management the Dispatch Center link implies they should be running dispatch, which they shouldn't — that creates dual-authority confusion over daily assignments.

### Why management ≠ admin

Admin (the tech lead) needs system-level tools that management should never touch: user role changes, database inspection, Alembic migration version, dispatch record deletion. Giving management admin-level access is a data integrity risk. Conversely, admin should not be routed to operational forms (trainer dashboard, trainee dashboard, field ops submission forms) — those are role-specific operational UIs, not audit tools.

### Why field-ops must include all field staff

Check-in and departure are required for all field staff, not just drivers. Walkers and trainers arrive at the yard and need to check in. The current gate of `['driver', 'admin']` means walkers and trainers cannot access the check-in panel — a regression from the intended shift lifecycle.

---

## Consequences

- The dashboard `App.tsx` will be refactored to branch on `isDispatch`, `isManagement`, `isAdmin` independently rather than the single `isManagement` catch-all.
- Management's dashboard becomes a read-heavy reporting interface — no action buttons except time-off/off-day approvals.
- Admin's dashboard gets a dedicated `/admin` route with system tools, replacing the incomplete `/assets` stub.
- Five new backend endpoints are needed to supply the management reporting panels with aggregated data.
- The navbar gains role-specific visibility rules: Preferences hidden from management/admin, Dispatch link hidden from management, admin-specific items grouped under the Admin nav item.
- All six currently unauthenticated routers receive appropriate RoleChecker dependencies — this is a security regression fix, not a feature.
