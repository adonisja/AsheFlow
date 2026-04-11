# Journal: Field Ops Driver Tools — Phase 2
**Date:** 2026-04-10

## Context

Following the Phase 1 Field Ops audit (check-in timestamp, departure gate, walker rating pre-population, stars column fix, incident report, return/end-of-day log), three additional tools were planned to complete the driver shift lifecycle: a structured vehicle inspection checklist, attendance confirmation before walker ratings, and a fuel/mileage log. These tools together create a complete digital paper trail for every driver shift.

## What Was Built

### Pre-Trip Vehicle Inspection Checklist

**Model** (`backend/app/models/field_ops.py` — `VehicleInspection`):
- `id`, `driver_id` (FK CASCADE), `truck_id` (FK SET NULL, auto-resolved from assignment), `date`
- `items` (JSONB — `{item_name: true/false}`)
- `has_failures` (Boolean — computed server-side from any `false` value in items)
- `notes` (Text, nullable), `submitted_at`
- Standard checklist items defined as `INSPECTION_ITEMS` constant: tyres, lights, mirrors, brakes, fluids, horn, wipers, seatbelts, cargo_security, fuel_level

**Router** (`backend/app/routers/field_ops.py`):
| Endpoint | Purpose |
|---|---|
| `GET /field-ops/inspection/items` | Returns canonical item list so UI doesn't hard-code it |
| `POST /field-ops/inspection` | Submit checklist; one per driver per date; validates unknown items |
| `GET /field-ops/inspection/{driver_id}` | Driver's own inspection history |
| `GET /field-ops/inspections/summary?target_date=` | All inspections for a date (management) |

**Migration:** `f4e891bc2d10` — creates `vehicle_inspections` table with indexes on `driver_id`, `date`, `truck_id`.

**UI** (`InspectionPanel` in `FieldOps.tsx`):
- Positioned after check-in, before departure — enforces "inspect before you depart" flow
- Pass/Fail toggle per item; submit blocked until all items answered
- On reload: fetches history, pre-populates confirmed state with per-item pass/fail grid
- Failure state shows red `XCircle` per failed item + "Report to management" callout
- Item labels defined in `ITEM_LABELS` constant — human-readable, no raw snake_case shown to driver

---

### Walker Attendance Confirmation

**Model change** (`WalkerRating`):
- Added `present` (Boolean, `NOT NULL`, `server_default=true`) — separates absence from poor performance
- `stars` made nullable — no-shows stored as `present=false, stars=null`
- Existing rows unaffected by migration (backfilled as `present=true`)

**Router change** (`POST /field-ops/rating`):
- `present=true` requires `stars` 1–5; `present=false` must have `stars=null` — cross-field validation at boundary
- Duplicate check covers both present and no-show submissions for the same driver/walker/date

**Migration:** `c2a983f01e44` — adds `present` column (default `true`), alters `stars` to nullable.

**UI** (`WalkerRatingPanel` updated):
- New attendance step: "Present" / "No-Show" buttons appear first per walker
- Star rating form only renders for present walkers
- "Confirm No-Show" button for absent walkers — explicit action, not omission
- Pre-population on load restores attendance state (`r.present`) alongside rating state
- Panel renamed to "Walker Attendance & Rating" to reflect the expanded scope

---

### Fuel / Mileage Log

**Model** (`backend/app/models/field_ops.py` — `FuelMileageLog`):
- `id`, `driver_id` (FK CASCADE), `truck_id` (FK SET NULL, auto-resolved), `date`
- `odometer_start` (Integer, required at departure time)
- `odometer_end`, `fuel_added` (both Integer, nullable — patched at return)
- `notes` (Text, nullable), `created_at`

**Router** (`backend/app/routers/field_ops.py`):
| Endpoint | Purpose |
|---|---|
| `POST /field-ops/fuel-log` | Log start odometer at departure; one per driver per date |
| `PATCH /field-ops/fuel-log/{driver_id}` | Patch end odometer + fuel added at return; validates end ≥ start |
| `GET /field-ops/fuel-log/{driver_id}` | Driver's own log history |
| `GET /field-ops/fuel-logs/summary?target_date=` | All logs for a date with computed distance (management) |

**Migration:** `e7d2130af5b1` — creates `fuel_mileage_logs` table with indexes on `driver_id`, `date`, `truck_id`.

**UI** (`FuelMileagePanel` in `FieldOps.tsx`):
- Positioned after inspection, before departure — start odometer must be logged as part of pre-trip prep
- Three states: (1) no record yet → odometer start form; (2) start logged, no end → end odometer + fuel form; (3) fully complete → read-only summary with computed distance
- Distance computed client-side for display from `odometer_end - odometer_start`
- End odometer form shows start reading as reference to prevent guessing

---

## Final Driver Shift Flow on Field Ops Page

1. **Check-In** — photo confirmation (all field staff)
2. **Pre-Trip Inspection** — pass/fail checklist (driver only)
3. **Fuel Log — Start** — departure odometer (driver only)
4. **Departure** — itinerary photo (all field staff, gated on check-in)
5. _[Route runs]_
6. **Return** — yard confirmation, shift duration computed (driver only, appears post-departure)
7. **Fuel Log — End** — return odometer + fuel added (driver only)
8. **Walker Attendance & Rating** — attendance then rating per walker (driver only)

## Design Decisions

- **JSONB for inspection items** — flexible enough to add new checklist items without a schema migration; `INSPECTION_ITEMS` constant on the server is the authoritative list that both validates payloads and seeds the UI.
- **has_failures computed server-side** — client cannot lie about failures; any `false` value in `items` sets the flag regardless of what the client sends.
- **Attendance before rating** — separating attendance from quality rating prevents the ambiguity of a missing rating meaning "forgot" vs "walker wasn't there." Every walker on the manifest gets an explicit record.
- **Fuel log as two-phase POST + PATCH** — start odometer is known at departure but end odometer is only known at return. Using a single record with a patch avoids a join and keeps distance calculation trivial.
- **No gate on Departure behind inspection/fuel** — the flow is positional (inspect → fuel → depart on the page) but not server-enforced. Drivers can still depart without completing inspection or logging odometer. This is intentional: enforcement blocks are a source of friction that can strand drivers in edge cases. Management visibility via summary endpoints is the accountability mechanism.
