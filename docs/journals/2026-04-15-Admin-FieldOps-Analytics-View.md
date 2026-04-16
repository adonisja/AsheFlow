# Journal: Admin Field Ops Analytics View
**Date:** 2026-04-15

---

## Problem

The `/field-ops` route was accessible to admin (by design) but rendered a blank "Loading your profile…" spinner forever. The page attempted to resolve the admin's employee record by scanning the `/employees/` list for a matching `discord_id` — admin accounts have no Driver employee record, so `self` was never found and `employeeId` stayed empty.

The driver tooling (check-in, inspection, fuel log, departure, return, walker rating) is irrelevant to admin. Admin needs a read-only analytics view of today's field activity.

---

## What Was Built

### Backend — `GET /field-ops/check-ins/summary`

New endpoint returning all driver check-ins for a given date (defaults to today). Filters to `role == "driver"` so non-driver check-ins don't appear. Accessible to management/admin (`allow_management` dependency).

### Frontend — `AdminFieldOpsView` component

Replaces the driver panel for admin users. Fetches five endpoints in parallel on mount:

| Endpoint | Data |
|---|---|
| `/field-ops/check-ins/summary` | Who has arrived at the yard |
| `/field-ops/returns/summary` | Departure/return status per driver |
| `/field-ops/inspections/summary` | Pre-trip inspection results |
| `/field-ops/fuel-logs/summary` | Odometer and fuel data |
| `/field-ops/no-shows` | Walkers marked absent today |

**KPI row** (4 cards):
- Checked In — drivers who have arrived at the yard today
- Trucks Out — departed but not yet returned
- Returned — completed their shift
- No-Shows Today — walkers marked absent

**Tables:**
- Departures & Returns: driver, departed time, returned time, shift duration, status badge
- Pre-Trip Inspections: driver, truck, submission time, pass/fail, failed items listed
- Fuel & Mileage: driver, truck, start odometer, end odometer, distance, fuel added
- Walker No-Shows: walker name and the driver who reported them

### Driver employee resolution fix

The original code resolved the driver's employee ID by fetching `/employees/` (100-record limit) and searching for a `discord_id` match. This was fragile and would silently fail for drivers beyond the first 100 records. Replaced with `GET /employees/me` which resolves directly from the JWT.

---

## Branching Logic

```
FieldOps()
  ├── isAdmin → <AdminFieldOpsView />   (no employee ID needed)
  └── else    → resolve employeeId via /employees/me
                 └── <CheckInPanel>, <DeparturePanel>, etc.
```

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/field_ops.py` | Added `GET /field-ops/check-ins/summary` |
| `frontend/src/pages/FieldOps.tsx` | Added `AdminFieldOpsView`; branched page export on `isAdmin`; fixed driver employee resolution to use `/employees/me` |
