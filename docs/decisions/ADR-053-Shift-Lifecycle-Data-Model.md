# ADR-053 — Shift Lifecycle Data Model

**Date:** 2026-05-02
**Status:** Accepted

---

## Context

The existing codebase tracked field operations in broad strokes: check-in, departure, walker ratings, vehicle inspection, fuel/mileage, anchor points. But the full daily shift — from the moment a driver arrives at the offsite facility to the moment they hand their truck back — had no coherent data model behind it.

The confirmed lifecycle is:

```
offsite → station (loading) → AP (route) → station (return) → offsite (EOD)
```

Each transition had gaps: no dock zone assignment, no station arrival timestamps, no package load counts, no mid-shift crew status, no structured return gate.

---

## Decisions

### 1. `inspection_type` on `VehicleInspection`

**Decision:** Add `inspection_type` (`"pre_trip"` | `"eod"`) and relax the unique constraint from `(driver_id, date)` to `(driver_id, date, inspection_type)`.

**Why:** A vehicle leaves and returns. Both legs need an inspection record. The original constraint physically prevented this.

**Constraint:** EOD inspection endpoint requires a `Departure` record for the same date — you cannot submit an EOD inspection without having first departed.

---

### 2. `TruckAssignment.status` transitions

**Decision:** Wire the existing (but never-written) `status` column in `record_departure` and `record_return`.

- Departure → `planned → active`
- Return → `→ completed`

**Why:** Status was modeled from day one but the transitions were never implemented, meaning `status` was always `"planned"` in production. The management dashboard "Fleet Today" card was reading this field and always showed 0 active trucks.

---

### 3. `DockAssignment`

**Decision:** New table. Dispatch assigns a dock zone string (`"A3"`, `"Dock 7"`, etc.) to each driver before their shift starts.

**Why:** Drivers need to know where to bring their truck at the station. This is currently communicated verbally or via Discord — no record exists. Having it in the DB lets the driver's FieldOps page surface it automatically.

---

### 4. `StationArrival` (two visits)

**Decision:** New table with `arrival_type: "loading" | "return"`. One record per type per driver per date.

**Why:** The `Departure` model records when drivers *leave*. There was no corresponding record for when they *arrive*. Two arrivals happen per shift — at the start (to load) and at the end (returning with RTS). Both timestamps matter for shift duration analysis and compliance tracking.

---

### 5. `PackageManifest`

**Decision:** One record per truck per date. Dispatch submits tote count and OV count at load time. Updatable via PATCH.

**Why:** Package counts are currently tracked outside the system (paper or verbal). Bringing them in enables: (a) reconciliation against `StationHandoff.totes_returned` at EOD, (b) per-truck load analytics over time.

**Owned by:** Dispatch (creates/updates). Drivers and management can read.

---

### 6. `CrewCompliance`

**Decision:** Driver submits one record per crew member at AP arrival — `arrival_time`, `uniform_pass`, `cart_cover_pass`.

**Why:** Compliance checks happen at the AP but are never recorded. The endpoint validates that the submitted `employee_id` values are actually on the driver's truck assignment that day — prevents fabricated compliance records for unrelated employees.

**One bulk submit:** The driver submits all crew members in one POST to avoid N separate calls.

---

### 7. `DriverCheckIn` (4 per shift)

**Decision:** 4 structured check-ins per driver per day (numbers 1–4). Fields: `routes_remaining`, `help_requested`, `working_crew_count`, `ncns_count`.

**Why:** Dispatch currently has no structured visibility into route progress during the shift. The check-in summary endpoint sorts by `help_requested` first, `routes_remaining` descending — dispatch sees the trucks that need attention at the top.

**Constraint:** Check-ins require a departure record (driver must have left the station).

---

### 8. Two-step return: `RTSReport` + `StationHandoff`

See ADR-054 for the full rationale on the split.

**Summary:**
- `RTSReport` — field submission before leaving the AP area. Dispatch approval gate.
- `StationHandoff` — physical confirmation at the station. Requires approved `RTSReport`.

---

## New Router

`/shift-ops` — all mid-shift operations (crew compliance, driver check-ins, RTS report, station handoff). Separated from `/field-ops` because these are sequenced, lifecycle-aware operations, not general field tools.

---

## Migration Chain

```
... → f4e891bc2d10 (vehicle_inspections)
    → a1b2c3d4e5f7 (inspection_type)
    ↘ b4c5d6e7f8a9 (is_manual assignment_members — pre-existing parallel head)
    → c1d2e3f4a5b6 (merge)
    → d2e3f4a5b6c7 (dock_assignments)
    → e3f4a5b6c7d8 (station_arrivals)
    → f4a5b6c7d8e9 (package_manifests)
    → a5b6c7d8e9f0 (crew_compliance, driver_check_ins, rts_reports, station_handoffs)
```

Single head after merge: `a5b6c7d8e9f0`.
