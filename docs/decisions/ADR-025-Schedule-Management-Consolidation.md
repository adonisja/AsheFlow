# ADR-025: Schedule Management Consolidation

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The `/schedule` route served field staff and management/admin in the same component. Management saw a pending approvals card above a personal-calendar section they had no use for. The approvals card mixed 3 request types (PTO, workday changes, schedule reworks) with no filtering or age visibility. Schedule rework reviews were duplicated on `/schedule-changes`, splitting management's work across two pages.

---

## Decision

Branch `/schedule` at the top of the component on `isPrivileged` (management | admin). Privileged users receive `ScheduleManagementView`, which provides:

1. **KPI row** — per-type pending counts + oldest pending age
2. **Admin analytics strip** — total/approved/rejected/approval-rate for schedule reworks (admin only)
3. **Unified approvals queue** — all 3 types, filterable by type, sortable by age, with per-card age badges
4. **4-week availability heatmap** — role × day grid showing available staff count per day for the next 28 days

Field staff continue to see their personal calendar view unchanged.

---

## Alternatives Considered

### A — Keep three separate approval sections but add age + filter

The existing flat grid with PTO / offday / rework sections would gain filter tabs and age badges. Rejected because the sections still force the reviewer to scan multiple areas for the oldest/highest-priority item. A unified sorted queue is strictly better for triage.

### B — Move all approvals to `/schedule-changes`

Would make `/schedule-changes` the single approval hub. Rejected because the page title and existing mental model suggest it is for schedule structure changes (add/drop/rework), not PTO. Mixing PTO into that page creates its own confusion.

### C — Add a dedicated `/schedule-management` route

A clean URL separation. Rejected because the navbar already has a Schedule link that management expects to lead to schedule oversight. A new route would require navbar changes and a redirect — same result, more surfaces to maintain.

---

## Consequences

**Positive:**
- Management sees all pending schedule requests in one place, sorted and filterable.
- Age badges create implicit SLA visibility without a formal SLA system.
- 4-week heatmap gives forward visibility for dispatch planning without a separate analytics page.
- Field staff experience is unchanged.
- No new backend endpoints required.

**Negative / Trade-offs:**
- The `/schedule-changes` page retains its own management queue for reworks, meaning rework approvals exist in two places. This is intentional redundancy — management can act from either page. If it becomes confusing, the rework queue on `/schedule-changes` should be removed for management and they should be redirected to `/schedule`.
- The heatmap fires 28 parallel requests. At scale, a single `GET /schedule/availability-summary?start=...&end=...` endpoint would be more efficient.
