# Journal: Navbar Routing and Dashboard Improvements
**Date:** 2026-04-18

---

## Context

After the design system migration several structural issues surfaced: the navbar overflowed on admin accounts, the dispatch role had no dedicated home dashboard, management tabs had been accidentally removed, and the feedback loop (FeedbackModal → DB → admin review) had no frontend completion. This session addressed all of these.

---

## Changes Applied

### Navbar overflow fix

Management-only tools (Assets, Trainees, Compliance, Walkers) were removed from the admin navbar. Admins reach these via ⌘K or from within their Admin dashboard. Management users retain them since those are their primary navigation targets.

`canAccessScheduleChanges` was corrected to exclude management (they don't review reassignment requests — dispatch does). `canAccessFieldOps` and `canAccessSchedule` already included management correctly.

`isAdmin` and `isMgmt` boolean variables were introduced to the Navbar component to replace repeated `groups.includes(...)` calls — cleaner and less error-prone when the same check is needed in both desktop and mobile nav.

### Dispatcher home dashboard (`/dispatch-home`)

New page: `DispatchHome.tsx`. Fetches four parallel data sources on mount:
- `GET /dispatch/{today}` — today's dispatch status and crew
- `GET /dispatch/{today}/confirmations` — confirmation map from Redis
- `GET /dispatch/unavailable-staff/{today}` — staff off today
- `GET /schedule-change-requests/?status=pending` — pending change requests

Derived stats:
- `isPublished` — true if any confirmations exist in the map (i.e., publish was triggered)
- `confirmed`, `pending`, `declined` — counts from the confirmation map
- `totalAssigned` — flat count of all crew members across all trucks

`RoleRedirect` updated: dispatch users now land on `/dispatch-home` instead of `/dispatch`.

### "Assignments" navbar link

The old "Dispatch" navbar label was renamed to **Assignments** to describe the page function rather than the role. Visible to `dispatch` and `admin`. Dispatch users use it to get to the crew assignment tool; admins use it to access/review dispatch data.

### Feedback Admin page (`/feedback`)

New page: `FeedbackAdmin.tsx`. Admin-only route at `/feedback`. Features:
- Filter tabs with live counts: All / New / In Progress / Resolved
- Table view: type badge (Bug/Feature/General with icon), message (truncated 2 lines), age (color-coded: danger ≥7d, warning 3–6d), status badge, action buttons
- Actions: `new → In Progress`, `any → Resolve`, `resolved → Reopen`
- Empty states per filter
- Navbar link added for admins between management tools and Admin Console
- Command palette entry added under Management group

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/DispatchHome.tsx` | New — dispatcher home dashboard |
| `frontend/src/pages/FeedbackAdmin.tsx` | New — admin feedback review page |
| `frontend/src/App.tsx` | Added `/dispatch-home` and `/feedback` routes; updated `RoleRedirect` |
| `frontend/src/components/layout/Navbar.tsx` | Overflow fix, isMgmt/isAdmin vars, Assignments link, Feedback link, notifications guard |
| `frontend/src/components/CommandPalette.tsx` | Dispatch homeRoute updated; Feedback Inbox action added |
