# ADR-061: FieldOps — Station Staging Check, Manifest Acknowledgement, and Full Mobile Screen Rewrite

**Date:** 2026-05-05  
**Status:** Accepted

## Context

The FieldOps mobile screen existed as a placeholder. Drivers had no way to perform any shift lifecycle action from their phone. Meanwhile the backend's `station_arrivals` table had no way to record whether the station was staged when the truck arrived, and `package_manifests` had no driver acknowledgement step — the driver had no formal confirmation that they received the manifest.

Three gaps needed closing simultaneously:

1. **Backend schema** — `station_arrivals` needed `was_staged` (bool) and `missing_items` (string[]) columns; `package_manifests` needed `acknowledged_by` (FK → employees) and `acknowledged_at` (timestamp).
2. **Backend API** — new endpoints to record the staging check on arrival and to let a driver acknowledge a manifest.
3. **Mobile screen** — a complete driver-facing shift lifecycle screen covering all 19 steps from pre-shift check-in through EOD sign-out.

## Decision

### Schema (migration `g1b2c3d4e5f6`)

Added to `station_arrivals`:
- `was_staged BOOLEAN` — null if arrival_type is "return" (irrelevant), true/false for loading arrivals.
- `missing_items TEXT[]` — items from the fixed STAGING_ITEMS set that were not ready.

Added to `package_manifests`:
- `acknowledged_by UUID → employees(id) ON DELETE SET NULL`
- `acknowledged_at TIMESTAMPTZ`

Both additions are nullable so existing rows are unaffected. The `down_revision` initially pointed at `f2a3b4c5d6e7` (wrong branch); corrected to `b6c7d8e9f0a1` after `alembic current` revealed the DB was at that head.

### API endpoints (field_ops router)

- `POST /field-ops/station-arrival` — updated to accept `was_staged` and `missing_items` on the create payload; fields are only stored when `arrival_type == "loading"`.
- `POST /field-ops/manifest/{truck_id}/acknowledge` — stamps `acknowledged_by = current_user.id` and `acknowledged_at = now()` on the manifest for the given date. Idempotent: re-acknowledging overwrites with the same employee's timestamp.
- `GET /field-ops/manifest/{truck_id}` — existing endpoint; now returns `acknowledged_by` and `acknowledged_at`.

### Mobile FieldOpsScreen rewrite

The screen is a single-file, 1 642-line React Native component implementing the full 19-step driver shift lifecycle:

**Offsite (pre-shift)**
1. Check-in (photo optional)
2. View dock/gate assignment
3. Pre-trip vehicle inspection
4. Log start odometer

**Station (loading)**
5. Record station arrival + staging check (totes, OV packages, phones/rabbits, chargers)
6. View & acknowledge package manifest
7. Record departure

**Route / Anchor Point**
8. Post initial AP + ETA
9. Confirm AP arrival
10. Check-in 1 — crew compliance + NCNS report
11. Walker ratings — drafted in AsyncStorage per walker, flushed with end-odometer submit
12. Check-in 2 — routes remaining + help request
13. Check-in 3 — routes remaining update
14. Departure request (RTS) — dispatch must approve before station return

**Station (return)**
15. Record station arrival (return)
16. Station handoff — totes returned + RTS package count

**Offsite (end-of-day)**
17. Log end odometer + flush walker rating drafts
18. EOD vehicle inspection
19. Sign out

Steps gate sequentially — a step is shown only when all preceding steps are complete. Completed steps collapse to a summary chip. The active step is expanded and highlighted.

## Consequences

- Drivers can now complete their entire shift from the mobile app with no web-console fallback required.
- Staging deficiencies are recorded at the moment of loading arrival, giving dispatch a real-time signal before the truck departs.
- Manifest acknowledgement creates an audit trail: dispatch knows when (and by whom) the manifest was accepted.
- Walker rating drafts survive app kills (AsyncStorage) and are submitted atomically with the end-odometer log.
- The Alembic heads divergence pattern is now documented: always run `alembic current` before writing `down_revision` for a new migration to avoid multi-head conflicts.
