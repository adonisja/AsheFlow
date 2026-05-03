# ADR-056 — Anchor Point Lifecycle Rewrite

**Date:** 2026-05-02
**Status:** Accepted

## Context

The original anchor point model assumed one record per truck per day — an end-of-day submission from the driver. When the actual business flow was described it was fundamentally different:

1. Before departure the driver sets a **preliminary** anchor point with an ETA and location. This goes to crew and dispatch immediately.
2. On arrival the driver taps "Arrived" to confirm they reached the spot, optionally correcting the location if conditions differed.
3. Mid-day the driver may need to relocate. Each relocation creates a new AP row; the previous one is marked `relocated`.

The single-row-per-truck-per-day model with a `UniqueConstraint("truck_id", "date")` could not represent this. The EOD framing in the UI was also wrong — APs are a departure-time tool, not an end-of-day one.

Additionally, the `GET /anchor-points/truck/{id}` endpoint returned 403 for drivers because `allow_dispatch` excluded the driver role, and `GET /field-ops/dock-assignment/{id}` raised 404 for unassigned drivers (normal pre-dispatch state), producing noisy browser errors.

## Decision

### Data model

Drop `UniqueConstraint("truck_id", "date")`. Add:
- `sequence` (int) — 1-based counter per truck per day
- `is_initial` (bool) — True only on the first AP of the day; feeds next-day driver suggestions
- `status` (CheckConstraint: `preliminary | arrived | relocated`)
- `arrived_at` (timestamptz nullable)

### Status lifecycle

```
preliminary → arrived      (driver taps "Arrived")
preliminary → relocated    (driver submits a new AP mid-day)
arrived     → relocated    (driver moves again after arriving)
```

When a new AP is submitted, all active (non-relocated) APs for the truck that day are marked `relocated` before the new row is inserted.

### API changes

| Endpoint | Change |
|---|---|
| `POST /anchor-points/` | Creates new AP; marks previous active as `relocated`; notifies crew+dispatch |
| `PATCH /{id}/arrive` | Sets status=arrived, stamps `arrived_at`, optional location correction |
| `PATCH /{id}/confirm` | Dispatch acknowledge — unchanged |
| `GET /driver/today` | Returns `List[AnchorPointResponse]` ordered by sequence |
| `GET /truck/{id}` | Returns last N `is_initial=True` records only (history suggestions) |
| `GET /field-ops/dock-assignment/{id}` | Returns `Optional` (200 null) instead of 404 when unassigned |

Role fix: added `allow_truck_read = RoleChecker(["driver", "dispatch", "management", "admin"])` so drivers can read their own truck's AP history.

### Discord notifications

All three events (preliminary, arrived, relocated) fire a rich embed to the truck's Discord channel via `POST /internal/post-embed` (new bot endpoint). Each event has a distinct color and footer:
- Preliminary: amber `#F59E0B` — "Awaiting arrival confirmation"
- Arrived: green `#22C55E` — "Arrival confirmed"
- Relocated: purple `#8B5CF6` — "Previous anchor point marked as relocated"

In-app notifications go to the full crew + all dispatch/admin employees on every event.

### Frontend (AnchorPoints.tsx)

Complete rewrite. Driver view shows a timeline of today's APs with status dots, a preliminary submission form (with location suggestions from truck history), and a one-tap "Arrived" card for the active AP. Dispatch view groups all APs by truck with the full chain visible and an acknowledge button per AP.

FieldOps.tsx `AnchorPointPanel` simplified to a compact status card + one-tap arrive + link to the full page.

### Alembic migration

`b6c7d8e9f0a1_rewrite_anchor_points_lifecycle.py` — drops the unique constraint, adds four columns, backfills existing rows (`sequence=1`, `is_initial=true`, `status='preliminary'`), adds the check constraint.

## Consequences

- Multiple AP rows per truck per day is now expected and correct.
- `is_initial=True` ensures next-day driver suggestions show the planned departure location, not a mid-day relocation.
- 404 noise on dock-assignment endpoint eliminated — WorkerView no longer logs errors on load for unassigned drivers.
- Dispatch sees a full intraday location timeline per truck, not just a single snapshot.
