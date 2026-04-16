# Journal: Schedule Management Consolidation
**Date:** 2026-04-15

---

## Problem

The `/schedule` route was a single component serving everyone. Management and admin users saw:
1. A pending approvals card (PTO + workday changes + reworks) — buried at the top
2. An Available Staff panel below it
3. A personal calendar calendar section beneath that — meaningless for management/admin who have no dispatcher assignments

The three request types (PTO, workday changes, schedule reworks) were rendered as a flat 2-column grid with no filtering, no sort control, and no indication of how long each request had been sitting. The Available Staff panel showed one date at a time and required manual date navigation.

Schedule rework requests also had a **separate page** (`/schedule-changes`) with its own pending queue for management — meaning management had two places to review requests, with no unified view.

---

## What Was Built

### `ScheduleManagementView` component (`Schedule.tsx`)

Management and admin visiting `/schedule` now receive this component immediately (all field-staff state and effects are never initialized for them).

**KPI row** (4 cards):
- Pending PTO — count of outstanding PTO requests
- Workday Changes — count of pending recurring off-day requests
- Schedule Reworks — count of pending schedule change requests
- Oldest Pending — days since the oldest unactioned request was submitted (red ≥7d, yellow ≥3d)

**Admin analytics strip** (admin only, shown when rework history exists):
- Total Requests / Approved / Rejected / Approval Rate — derived from `/schedule-change-requests/` full history

**Unified Approvals Queue:**
- All 3 request types rendered in one card, interleaved and sorted
- **Type filter tabs**: All · PTO (n) · Workday (n) · Rework (n)
- **Age badge** on every card: "Today" / "3d ago" / "7d ago" — color-coded (neutral → yellow → red)
- **Sort toggle**: Newest first / Oldest first
- Each card shows employee name, role, request-specific details, and approve/reject buttons
- Expired PTO requests are faded with a label and no action buttons

**4-Week Availability Heatmap:**
- 28 parallel `GET /schedule/available/{date}` calls, one per day
- Table: rows = driver / trainer / walker, columns = next 28 days
- Each cell shows the count of available staff with heat-map intensity (relative to the max across the entire table)
- Weekends are faded (field ops typically don't run weekends)
- Legend below the table explains intensity tiers

### Route and nav changes

- `/schedule` route now allows `admin` in addition to existing roles
- `canAccessSchedule` flag in Navbar updated to include admin
- `Preferences` nav link now visible to admin (to surface the Preference Analytics view)

---

## Branching Logic

```
Schedule()
  ├── isPrivileged (management | admin) → <ScheduleManagementView isAdmin={isAdmin} />
  └── else → personal calendar view (field staff)
              └── personal PTO calendar + date detail panel
```

All hooks are declared unconditionally above the early return to satisfy React's rules of hooks.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/Schedule.tsx` | Rewrote: added `ScheduleManagementView`, branched on `isPrivileged`, removed old privileged JSX from field-staff view |
| `frontend/src/App.tsx` | Added `'admin'` to `/schedule` route `allowedRoles` |
| `frontend/src/components/layout/Navbar.tsx` | Added admin to `canAccessSchedule`; added admin to Preferences nav link condition |

---

## Design Notes

- **Age badge color thresholds:** < 3 days = neutral, 3–6 days = yellow, ≥ 7 days = red. Seven days is the chosen SLA for a response to a schedule request.
- **28 parallel requests for the heatmap:** The endpoint is cheap (one date lookup); 28 parallel calls complete in ~1 round-trip latency. A single aggregating backend endpoint would be cleaner at scale but is not worth the complexity now.
- **Relative heatmap intensity:** Cell color is `count / heatmapMax`, so the display adapts to the actual pool size. A team of 5 and a team of 50 both produce a readable gradient.
- **ScheduleChanges.tsx left intact:** The admin and management views on that page still exist and handle schedule rework requests only. The unified queue on `/schedule` now duplicates that queue for convenience — management no longer needs to visit two pages. If the pages diverge in the future, `/schedule-changes` remains the canonical rework-only management view.
