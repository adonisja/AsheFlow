# Journal: Vehicle Compliance Page
**Date:** 2026-04-15

---

## Problem

### 1. Dashboard card was uninterpretable

The "Vehicle Compliance (7d)" card on the management dashboard showed a grid of inspection item failure counts and fail rates. The numbers had no explanation, so a manager seeing "Brakes — 3 failures, 15% fail rate" had no idea what that meant:

- Does this mean one truck has chronic brake issues?
- Is it three different trucks each failing brakes once?
- Which driver submitted those inspections?

The endpoint (`GET /field-ops/inspection-failures/summary`) aggregates across all drivers, all trucks, and all dates in the period. It intentionally loses the per-record context in order to surface fleet-wide patterns. But presenting the output without explaining that aggregation made it look like a list of trucks with problems, when it is actually a fleet-wide pattern summary.

### 2. No inspection history page

There was no page where management could:
- Look up all inspections for a specific truck
- See which driver submitted a failing inspection and on what date
- Filter to failed-only records
- Identify drivers or trucks with recurring failures
- Do follow-up after a failure notification

Inspections appeared in two read-only places: the today-only table on the management dashboard and the admin Field Ops analytics view. Neither was filterable or searchable.

---

## What Was Built

### Backend — `GET /field-ops/inspections/history`

New endpoint returning full inspection records for the last N days (default 30, max 365).

Query parameters:
| Param | Type | Description |
|---|---|---|
| `days` | int | Rolling window (default 30) |
| `driver_id` | UUID | Filter to one driver |
| `truck_id` | UUID | Filter to one truck |
| `has_failures` | bool | Filter to passed or failed only |

Response fields per record: `inspection_id`, `driver_id`, `driver_name`, `truck_id`, `truck_name`, `date`, `submitted_at`, `has_failures`, `failed_items` (list), `passed_items` (list), `notes`.

### Frontend — `/vehicle-compliance` page

**Period selector**: 7d / 14d / 30d / 60d / 90d — re-fetches all data on change.

**KPI row** (4 cards):
- Total Inspections in period
- Pass Rate (% passed, color-coded: green ≥95%, yellow 80–94%, red <80%)
- Trucks with Repeat Failures (≥2 failed inspections in period)
- Drivers with Repeat Failures (≥2 failed inspections in period)

**Most Frequently Failed Items** — the same aggregate pattern view from the dashboard, now with an explanatory paragraph clarifying that these counts are fleet-wide totals, not per-truck counts.

**Failure Pattern Heatmap** — item × truck (or item × driver, tab-togglable). Each cell shows how many times that truck/driver failed that specific item. Color intensity is relative to the period maximum. This is the view that answers "which truck keeps failing brakes?"

**Trucks/Drivers with Repeat Failures** — two side-by-side lists, only shown when at least one entity has ≥2 failures in the period. Click-path for follow-up.

**Inspection History table** — filterable by driver, truck, and pass/fail status. Each row: pass/fail icon, driver, truck, date, submitted time, result badge. Expandable to show the full item-by-item breakdown (failed items in red pill badges, passed items in green).

### Dashboard card update

"Vehicle Compliance (7d)" → **"Inspection Failure Patterns (7d)"**. Added an explanatory sentence. Added "View full compliance report →" link to `/vehicle-compliance`.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/field_ops.py` | Added `GET /field-ops/inspections/history` |
| `frontend/src/pages/VehicleCompliance.tsx` | New page |
| `frontend/src/App.tsx` | Added `/vehicle-compliance` route |
| `frontend/src/components/layout/Navbar.tsx` | Added `ShieldAlert` import; added Compliance nav link for admin/management |
| `frontend/src/components/dashboard/ManagementView.tsx` | Renamed card, added explanation text and link |

---

## Design Notes

- **Repeat failure threshold is ≥2** — a single failure can be a one-time issue. Two or more in the same period signals a pattern worth following up on.
- **Heatmap axis is toggleable (truck vs driver)** — both axes answer different questions: truck axis spots mechanical problems, driver axis spots drivers who are not thorough inspectors or who are assigned problem vehicles repeatedly.
- **All filters are client-side** — the history endpoint already returns the full period's records; filtering client-side avoids additional round-trips for each filter change.
- **Period selector re-fetches** — the 4-endpoint parallel fetch is repeated when the period changes, ensuring KPIs, failure patterns, and history all reflect the same window.
