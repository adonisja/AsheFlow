# 2026-05-02 — Shift Lifecycle Data Model

## Summary

Implemented the full daily shift lifecycle in the backend — from the moment a driver receives their initial dispatch confirmation to the moment they return their truck at end of day. All new tables, schemas, and endpoints are migration-backed and untested against a live DB (Docker was not running during this session).

---

## Lifecycle Overview

The confirmed shift flow is:

```
offsite → station (loading) → AP (route) → station (return) → offsite (EOD)
```

Each leg now has corresponding records:

| Stage | Records |
|---|---|
| Offsite (pre-shift) | `CheckIn`, `DockAssignment`, `VehicleInspection (pre_trip)` |
| Station → departure | `StationArrival (loading)`, `PackageManifest`, `Departure` → `TruckAssignment.status = active` |
| Route (AP) | `AnchorPoint`, `CrewCompliance`, `DriverCheckIn ×4` |
| Field → station gate | `RTSReport` (dispatch approval gate) |
| Station (return) | `StationArrival (return)`, `StationHandoff` |
| Offsite (EOD) | `VehicleInspection (eod)`, `Departure.returned_at` → `TruckAssignment.status = completed` |

---

## Changes Made

### #1 — `inspection_type` on `VehicleInspection`

**Problem:** The unique constraint `(driver_id, date)` blocked two inspections per day, making an EOD inspection impossible.

**Fix:**
- Added `inspection_type = Column(String(20))` with values `"pre_trip"` | `"eod"`
- Changed unique constraint from `(driver_id, date)` → `(driver_id, date, inspection_type)`
- `POST /field-ops/inspection` now validates `inspection_type`; EOD requires a departure record to exist first
- Failure notification message now labels the type: `"Pre Trip inspection FAILED"` / `"Eod inspection FAILED"`
- Migration: `a1b2c3d4e5f7`

### #2 — `TruckAssignment` status wiring

**Problem:** `status` column existed with `planned | active | completed` constraint but was never written by any code — always stayed `"planned"`.

**Fix:** Two status transitions wired in `field_ops.py`:
- `record_departure` → `planned → active` (only if currently `planned`)
- `record_return` → `→ completed` (any non-completed status)

### #3 — `DockAssignment` model + endpoints

Dispatch assigns a dock zone to each driver before their pre-trip inspection so they know where to pick up their truck at the station.

- Model: `dock_assignments` — one per driver per date, `dock_zone: String(50)`
- Endpoints: `POST`, `PATCH`, `GET /field-ops/dock-assignment/{driver_id}`, `GET /field-ops/dock-assignments/summary`
- Driver reads their own; dispatch can PATCH if zone changes
- Migration: `d2e3f4a5b6c7`

### #4 — `StationArrival` model + endpoints

Records the two station visits per shift: `"loading"` (arriving to load packages) and `"return"` (arriving back with RTS). The existing `Departure` model records when the driver *leaves*; this records when they *arrive*.

- Model: `station_arrivals` — unique on `(driver_id, date, arrival_type)`
- `POST /field-ops/station-arrival` — driver self-reports
- Migration: `e3f4a5b6c7d8`

### #5 — `PackageManifest` model + endpoints

Dispatch records tote count and OV (oversized) package count per truck per date at station load time.

- Model: `package_manifests` — unique on `(truck_id, date)`
- Endpoints in dispatch router: `POST`, `PATCH /dispatch/manifest/{truck_id}`, `GET /dispatch/manifest/{truck_id}`, `GET /dispatch/manifests/summary` (daily totals)
- Migration: `f4a5b6c7d8e9`

### #6 — `CrewCompliance` model + endpoints

Driver submits AP arrival compliance for each crew member — arrival time, uniform pass/fail, cart cover pass/fail. One record per `(driver_id, employee_id, date)`.

- Validates crew member is actually on the driver's truck assignment that day
- `POST /shift-ops/crew-compliance` (bulk — covers all members in one call)
- Migration: `a5b6c7d8e9f0`

### #7 — `DriverCheckIn` model + endpoints

4 structured mid-shift check-ins per driver per date (numbers 1–4). Each captures `routes_remaining`, `help_requested`, `working_crew_count`, `ncns_count`.

- Requires departure record (driver must have left the station first)
- `GET /shift-ops/check-ins/summary` returns latest check-in per driver, sorted by `help_requested` then `routes_remaining` descending
- Migration: `a5b6c7d8e9f0`

### #8 — `RTSReport` + `StationHandoff` (two-step return)

Initial design used a single `RTSClearance` model that conflated the field report and the physical station handoff. **Corrected to two distinct steps** after clarifying the real workflow:

**`RTSReport`** — submitted from the field before leaving the AP area:
- `crew_confirmed` count, `rts_packages` grouped by reason
- Dispatch approval gate: `status = pending | approved | rejected`
- Driver is blocked from leaving until `status = approved`
- `GET /shift-ops/rts-reports/pending` — dispatch review queue

**`StationHandoff`** — submitted at the station after physically handing off:
- `totes_returned`, `rts_count` (physical count)
- Requires `RTSReport.status == "approved"` on same date
- `GET /shift-ops/station-handoffs/summary` — daily totals across all trucks

- Migration: `a5b6c7d8e9f0` (both tables in the same migration)

---

## New Router: `/shift-ops`

`backend/app/routers/shift_ops.py` — registered in `main.py`. Contains all mid-shift operations:
- Crew compliance
- Driver check-ins
- RTS report (field gate)
- Station handoff (physical close)

---

## New/Modified Files

| File | Change |
|---|---|
| `models/field_ops.py` | Added `inspection_type`, `INSPECTION_TYPES`, updated `UniqueConstraint` |
| `models/dock_assignment.py` | New |
| `models/station_arrival.py` | New |
| `models/package_manifest.py` | New |
| `models/crew_compliance.py` | New |
| `models/driver_check_in.py` | New |
| `models/rts_clearance.py` | New (contains both `RTSReport` and `StationHandoff`) |
| `models/__init__.py` | Added all new model imports |
| `schemas/field_ops.py` | Added `inspection_type` to inspection schemas; added `DockAssignmentCreate/Patch/Response`, `StationArrivalCreate/Response` |
| `schemas/manifest.py` | New — `PackageManifestCreate/Patch/Response` |
| `schemas/shift_ops.py` | New — all crew compliance, driver check-in, RTS report, station handoff schemas |
| `routers/field_ops.py` | Updated inspection endpoints; added dock assignment + station arrival endpoints; wired `TruckAssignment` status transitions in `record_departure` / `record_return` |
| `routers/dispatch.py` | Added package manifest endpoints |
| `routers/shift_ops.py` | New router |
| `main.py` | Registered `shift_ops` router |
| `alembic/versions/a1b2c3d4e5f7` | `inspection_type` + constraint change |
| `alembic/versions/c1d2e3f4a5b6` | Merge head (inspection_type branch + is_manual branch) |
| `alembic/versions/d2e3f4a5b6c7` | `dock_assignments` table |
| `alembic/versions/e3f4a5b6c7d8` | `station_arrivals` table |
| `alembic/versions/f4a5b6c7d8e9` | `package_manifests` table |
| `alembic/versions/a5b6c7d8e9f0` | `crew_compliance`, `driver_check_ins`, `rts_reports`, `station_handoffs` tables |

---

## Issues / Notes

- Docker was not running during this session — none of the new migrations were applied to a live DB. Run `alembic upgrade head` after starting Docker.
- `aiohttp` is still missing as a dev dependency (pre-existing, tracked separately).
- `RTSClearance` was initially named and implemented as a single table. Renamed to `RTSReport` + added `StationHandoff` after clarifying the two-step workflow with the user. The migration was updated before any data existed — no data migration needed.
- The `a5b6c7d8e9f0` migration creates 4 tables: `crew_compliance`, `driver_check_ins`, `rts_reports`, `station_handoffs`. The `rts_clearances` table name was corrected to `rts_reports` before the migration ran.
