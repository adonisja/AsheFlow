# Journal — Dashboard Audit & Fixes
**Date:** 2026-05-02

## Context

After building the full shift lifecycle backend (see journal 2026-05-02-Shift-Lifecycle-Data-Model), we audited all three dashboard views to surface data that was either missing, stale, or wired to the wrong endpoint.

## Problems Found

### WorkerView
- Drivers had no visibility into their assigned truck or dock zone from the home screen.
- Anchor Point and Field Ops links were absent.

### DispatchView
- Fleet Status panel fetched `Departure` rows — always empty at start of day since no one has departed yet. Showed 0/0 all morning.
- RTS Return Requests had no UI surface at all; dispatch had no way to approve/reject from the dashboard.

### DispatchHome
- KPI grid had 4 cards; RTS queue had no presence.
- No way to see pending RTS count at a glance.

### ManagementView
- Fleet Today KPI read from `/field-ops/returns/summary` (departure rows), same root cause as DispatchView — always 0/0.
- Inspections table was titled "Pre-Trip Inspections" with no `inspection_type` column. Now that both pre-trip and EOD inspections exist, both types appear in the same query and the type was invisible.
- No shift ops panels (check-ins, handoffs, RTS queue) — management had no mid-shift visibility.

## Changes Made

### WorkerView
- Added "Today's Assignment" card for drivers: fetches `/employees/me` → `/field-ops/crew/{id}` for truck, `/field-ops/dock-assignment/{id}` for dock zone.
- Added Field Ops and Anchor Point links to driver portal links.
- Portal title is now role-specific (Driver/Trainer/Trainee/Worker Portal).

### DispatchView
- Fleet Status reads from `truck_assignments` array on the `GET /dispatch/{date}` response, counting `planned / active / completed` status.
- Added RTS Return Requests panel: lists pending reports, approve/reject via `PATCH /shift-ops/rts-report/{driver_id}`.
- Added Anchor Points to quick links.

### DispatchHome
- Added `pendingRTS` state; fetches `/shift-ops/rts-reports/pending`.
- Added 5th KPI card "Pending RTS" (grid expanded to `lg:grid-cols-5`).
- Added RTS Return Requests MotionCard at bottom with per-driver approve/reject.

### ManagementView
- Fleet Today KPI now reads from `GET /dispatch/{today}` → `truck_assignments` status counts (planned/active/completed). Shows `X/total` where X is active + completed.
- Dispatch-not-run state shows `—` with "dispatch not run yet" subtext.
- Inspections table renamed to "Vehicle Inspections — Today" with new Type column: colored badge (Pre-Trip / EOD).
- Added 3-panel shift ops row: Driver Check-Ins, RTS Return Requests, Station Handoffs — each with scrollable per-driver list.

## Fix for GetLocalYMD
`getLocalYMD()` takes no arguments (always returns today). ManagementView was erroneously calling `getLocalYMD(new Date())`. Fixed to use `new Date().toISOString().slice(0, 10)` inline.

## Build Validation
`npm run build` passes clean. No TypeScript errors.
