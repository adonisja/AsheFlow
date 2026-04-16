# Journal: Role Architecture Audit & Restructure Plan
**Date:** 2026-04-10

## Context

After completing the Phase 2 Field Ops features and running a comprehensive gap evaluation, a second audit pass identified systemic issues with how roles are separated (or not separated) across the frontend dashboard, navbar, route guards, and backend authentication. Six routers were entirely unauthenticated. Three elevated roles shared a single dashboard view. Several routes were gated to the wrong roles.

## Findings

### Backend Auth Gaps

Six routers had zero authentication on all or most endpoints:
- `trucks.py` — all 6 endpoints open
- `time_off_requests.py` — all 6 endpoints open
- `employee_off_days.py` — create/get/delete open; only approve/reject protected
- `employee_relationships.py` — all 5 endpoints open
- `schedule.py` — both endpoints open
- `notifications.py` — all 3 endpoints open

The practical risk: any authenticated session (or even unauthenticated if the CORS gateway allows it) can create bans against drivers (poisoning dispatch weights), approve their own time-off requests, or read any employee's notifications.

### Frontend Route Mismatches

- `/field-ops` gated to `['driver', 'admin']` — walkers, trainers, trainees excluded despite needing check-in/departure
- `/my-training` allows `management` in `allowedRoles` but the nav doesn't show the link to management — inconsistent
- `/trainer-dashboard` allows `admin` — routes admin to the trainer's daily task submission form, not an oversight view
- `management` included in Dispatch nav — implies they should run dispatch

### Dashboard Conflation

`isManagement = groups.some(r => ['admin', 'management', 'dispatch'].includes(r))` is the single predicate for the entire elevated dashboard. All three roles see:
- The same quicklinks (including Dispatch Center for management)
- The same pending approvals card (including reassignment requests for management, which is a dispatch concern)
- Fleet Return Status only for admin/management (not dispatch, who is running the day)

## Plan

### Immediate fixes (auth + route correctness)
Add `get_caller_employee` or appropriate `RoleChecker` to all six unprotected routers. Fix the `/field-ops` route gate. Remove admin from `/trainer-dashboard` and `/my-training`. Remove management from the Dispatch nav link.

### Dashboard restructure
Split `Dashboard` component into three branches:
1. `DispatchView` — existing tools, add fleet return status (dispatch should see this)
2. `ManagementView` — reports-only: operations summary, workforce health, incident trends, training pipeline, walker performance, vehicle compliance
3. `AdminView` — system tools: health metrics, user/employee CRUD (Assets), audit trail, all management panels

### New reporting endpoints
Five new `GET` endpoints to back the management reporting panels: no-shows, walker stats, inspection failure summary, training pipeline summary, incident summary.

## Design Decisions

- Management's pending approvals card retains time-off and off-day approvals only — reassignment requests are removed (dispatcher concern).
- Admin sees all management panels plus system tools, but through a dedicated `/admin` route, not the home dashboard which becomes a role-specific landing page.
- The navbar Preferences link is hidden from management and admin — they have no fav/ban relationships to manage. It remains for all field staff.
- Field ops route opens to all field staff — the panels themselves are already role-gated internally (InspectionPanel, FuelMileagePanel, ReturnPanel, WalkerRatingPanel all use `isDriver` internally).
