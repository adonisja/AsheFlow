# 2026-05-05 — FieldOps Station Staging, Manifest Acknowledgement, and Mobile Screen Rewrite

## What we built

### Backend schema (migration `g1b2c3d4e5f6`)

Added `was_staged` (bool) and `missing_items` (text[]) to `station_arrivals` so loading arrivals record whether the station had the truck's package load ready. Added `acknowledged_by` and `acknowledged_at` to `package_manifests` so drivers can formally confirm the manifest before departure.

The migration initially had the wrong `down_revision` (`f2a3b4c5d6e7`) from a stale copy. Running `alembic current` showed the DB was actually at `b6c7d8e9f0a1`. Corrected the file, then `alembic upgrade g1b2c3d4e5f6` applied cleanly.

### Backend API

Two new endpoints in `field_ops` router:
- `POST /field-ops/station-arrival` now accepts staging fields (ignored for return arrivals).
- `POST /field-ops/manifest/{truck_id}/acknowledge` stamps the driver's acknowledgement on the manifest.

### Mobile: FieldOpsScreen full rewrite

`mobile/src/screens/FieldOps/FieldOpsScreen.tsx` was a placeholder. Replaced with a 1 642-line, 19-step gated lifecycle screen.

Key implementation decisions:
- **Step gating via ShiftState** — one `useEffect` polls all shift endpoints on mount/refresh; a computed `step` integer drives which section renders. Future steps are hidden (not disabled), so drivers only ever see what they can actually do.
- **Walker rating drafts in AsyncStorage** — drafts keyed by `walker_rating_draft:{employee_id}:{date}:{walker_id}` persist across app kills and are flushed atomically when the end-odometer log is submitted.
- **Metric/imperial toggle** — odometer and fuel values are stored in imperial (miles, gallons) but displayed in the user's preferred unit. Conversion happens at read/write boundaries only.
- **Inspection form reused** — `InspectionForm` and `InspDoneView` render both the pre-trip (step 3) and EOD (step 18) inspections; only `inspType` differs.
- **Staging check on station arrival** — a `SwitchRow` per `STAGING_ITEMS` key records missing items; only shown when `arrival_type === "loading"`.
- **Manifest acknowledgement** — `StepManifest` fetches the manifest for the driver's truck, displays tote/OV counts, and lets the driver tap "Acknowledge Manifest." The endpoint is idempotent.

## Files changed

### New
- `backend/alembic/versions/g1b2c3d4e5f6_station_arrival_staging_and_manifest_ack.py`

### Modified
- `backend/app/models/package_manifest.py` — `acknowledged_by`, `acknowledged_at` columns
- `backend/app/models/station_arrival.py` — `was_staged`, `missing_items` columns
- `backend/app/schemas/field_ops.py` — `StationArrivalCreate`/`Response` staging fields; `ManifestAcknowledgeResponse`
- `backend/app/routers/field_ops.py` — staging fields on arrival create; manifest acknowledge endpoint
- `mobile/src/screens/FieldOps/FieldOpsScreen.tsx` — full rewrite (19 steps)

## Debugging note

`alembic heads` showed two heads after the first `upgrade head` attempt — my migration (`g1b2c3d4e5f6`) and the existing head (`b6c7d8e9f0a1`). The root cause was copy-pasting `down_revision` from a migration that was never merged. Lesson: always run `alembic current` first, then set `down_revision` to that output.
