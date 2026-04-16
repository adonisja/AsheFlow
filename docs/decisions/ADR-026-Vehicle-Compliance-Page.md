# ADR-026: Vehicle Compliance Page

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The existing "Vehicle Compliance" dashboard card showed aggregate inspection failure counts per checklist item (e.g. "Brakes — 3 failures, 15% fail rate"). This data came from `GET /field-ops/inspection-failures/summary`, which intentionally aggregates across all drivers and trucks in the period. The problem was twofold:

1. The aggregation was never explained, so managers read the numbers as "this truck has this problem" when they actually mean "this item appeared in this many failing inspections fleet-wide."
2. There was no way to drill down to individual records — which driver, which truck, which date — for follow-up.

---

## Decision

1. Add a `GET /field-ops/inspections/history` endpoint returning full per-inspection records, filterable by driver, truck, and pass/fail status.
2. Build a dedicated `/vehicle-compliance` page providing:
   - KPIs: total inspections, pass rate, repeat-failure trucks, repeat-failure drivers
   - The existing fleet-wide pattern summary (renamed and explained)
   - A heatmap showing failures concentrated by truck or driver
   - A filterable full history table with expandable per-record item detail
3. Rename the dashboard card to "Inspection Failure Patterns (7d)" and add an explanatory sentence + link to the new page.

---

## Alternatives Considered

### A — Add drill-down modals on the dashboard card

Clicking a failure item would open a modal showing which inspections contributed to that count. Rejected because modals are poor containers for a multi-filter, multi-sort table. A dedicated page scales better and is linkable directly.

### B — Extend the existing Field Ops admin analytics view

Admin's FieldOps page already has an inspections table. Adding history and heatmap there would make that page too wide and conflate today's operational view (who checked in, who departed) with the historical compliance view. Separate pages maintain clear purpose boundaries.

### C — Backend-side filtering for the history table

Pass filter params to the API with each filter change. Rejected at this scale — the full period's records are already fetched; client-side filtering is instant and avoids round-trips. When the dataset grows beyond a few thousand records, server-side pagination should be added.

---

## Consequences

**Positive:**
- The dashboard card is now interpretable — the explanation text makes it clear that counts are fleet-wide, not per-vehicle.
- Management can identify repeat-offender trucks and drivers without navigating through individual driver profiles.
- The heatmap makes concentration patterns visually obvious (e.g. 4 of 5 brake failures are on one truck).
- The history table provides a complete audit trail linkable by driver or truck for performance conversations.

**Negative / Trade-offs:**
- The ≥2 threshold for "repeat failures" is arbitrary. It should be made configurable (or at least revisited) if the fleet size changes significantly.
- Client-side filtering means the full period's dataset is always in memory. For 90-day windows with many drivers this could be a few hundred records — acceptable now, but a server-side paginated endpoint should replace this if it grows.
