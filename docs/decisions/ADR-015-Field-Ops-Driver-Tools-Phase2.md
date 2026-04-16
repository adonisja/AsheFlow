# ADR-015: Field Ops Driver Tools — Phase 2

**Date:** 2026-04-10  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Phase 1 of Field Ops established the core shift panels (check-in, departure, walker rating) and added the incident report, return/end-of-day log, and several UX fixes. Three additional tools were identified to complete the driver shift lifecycle: a pre-trip inspection checklist, attendance confirmation before walker ratings, and a fuel/mileage log. Without these, the system captures presence and performance but not vehicle safety compliance or fleet cost data.

---

## Decision

Build three new driver-facing panels in FieldOps.tsx, backed by new models, Alembic migrations, and REST endpoints. All three are driver-only. Management/admin receive read access via summary endpoints.

---

## Rationale

### Why JSONB for inspection items rather than a normalized table?

A normalized `inspection_items` table would require a migration every time a new checklist item is added. JSONB gives us schema flexibility: the server-side `INSPECTION_ITEMS` constant is the authoritative list and validates payloads; the client fetches it via `GET /field-ops/inspection/items` so the checklist is always in sync without a frontend deploy. Historical records preserve exactly what was checked at the time — the JSONB snapshot is immutable after submission.

### Why is `has_failures` computed server-side instead of client-sent?

Client-computed fields are trust boundaries. A driver could send `has_failures=false` with failed items in the payload. Server recomputes from `any(v is False for v in items.values())` so the flag is always accurate and management dashboards can rely on it for alerting.

### Why does Departure have no server-side gate blocking it if inspection wasn't submitted?

Enforcing a hard gate (400 if no inspection today) creates a blocking dependency that can strand drivers: inspection app crashes, backend is unreachable for one request but not another, dispatcher needs a driver to move immediately. The accountability mechanism is management visibility via `GET /field-ops/inspections/summary` — a missing inspection is an anomaly a manager can follow up on, not a system blocker. The UI still presents the panels in the correct order to guide compliance.

### Why separate attendance from rating in WalkerRating?

Previously, a missing rating was ambiguous: either the driver forgot, or the walker was absent. These have opposite implications — one is a data quality gap, the other is an HR event (no-show). Storing `present=false` with `stars=null` creates an explicit record of absence. The `present` column backfills as `true` for all historical rows, so old ratings retain full meaning.

### Why is the fuel log a POST + PATCH rather than two separate endpoints?

Two records (departure log, return log) would require a join to compute shift distance and add indirection to management queries. A single row with nullable `odometer_end` makes distance a trivial column subtraction on any read. The PATCH validates `odometer_end >= odometer_start` so the record is always internally consistent.

### Why no gate on Departure behind fuel log start?

Same rationale as inspection gate: positional ordering on the UI page guides compliance without creating blocking dependencies that can cause operational problems in edge cases.

---

## Consequences

- Driver shift lifecycle is now fully captured digitally: check-in → inspection → fuel start → departure → return → fuel end → attendance + rating.
- Management gains three new summary endpoints for daily fleet oversight: inspections, fuel/mileage, and the existing returns summary.
- `WalkerRating.stars` is now nullable — any existing code that assumed non-null stars must handle null (analytics queries, averages).
- The `INSPECTION_ITEMS` constant on the server is the single source of truth for the checklist. Adding a new item requires a server-side code change + redeployment but no migration.
- `fuel_mileage_logs` and `vehicle_inspections` grow one row per driver per day — low volume, no partitioning needed at current scale.
