# Journal: Admin Schedule Access Correction and ScheduleChanges Role Split
**Date:** 2026-04-14

---

## Goal for the Session

Two related role scope corrections identified after reviewing admin access paths:

1. Admin should not have access to the `/schedule` page — there is no business reason for an admin to view or manage their own work schedule, since admins are not field staff and are not dispatched.
2. The `/schedule-changes` page was presenting admins with the same view as management — a pending requests queue with no personal form. This was acceptable but missed an opportunity: admins should see organizational analytics (request volume, approval rate, top requested days off), not just the queue.

---

## What Changed

### `Navbar.tsx`

Added a new predicate `canAccessSchedule`:

```typescript
const canAccessSchedule = isFieldStaff || groups.includes('management');
```

`isFieldStaff` covers driver, walker, trainer, trainee. Management is included because they legitimately use the Schedule page to view any employee's schedule and check the available staff panel. Admin is absent — deliberately.

Both the desktop and mobile Schedule nav links were changed from `{isFieldStaff && ...}` to `{canAccessSchedule && ...}`. Preferences remains `isFieldStaff` only — management and admin have no personal preferences to manage either.

The `canAccessScheduleChanges` predicate is unchanged — admin still sees the Schedule Changes link, they just see a different view when they arrive.

---

### `App.tsx`

`/schedule` route changed from an open `ProtectedRoute` (any authenticated user) to an explicit allowlist:

```tsx
// Before
<Route path="/schedule" element={<ProtectedRoute><Schedule /></ProtectedRoute>} />

// After
<Route path="/schedule" element={
  <ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'management']}>
    <Schedule />
  </ProtectedRoute>
} />
```

Admin hitting `/schedule` directly now receives the Access Denied screen instead of the field staff calendar view.

---

### `ScheduleChanges.tsx`

The page now has three distinct render paths determined by role at the top of the component:

```typescript
const isAdmin      = groups.includes('admin');
const isManagement = groups.includes('management');
const isReviewer   = isAdmin || isManagement;
```

**Admin path** (`isAdmin === true`):
- `ScheduleAnalytics` component — stat cards (total, pending, approved, rejected), approval rate progress bar, breakdown by request type (add/drop/rework), top 3 most-requested days off derived from drop_day and full_rework requests
- Pending requests queue with approve/reject
- No personal schedule summary, no submission form, no "My Requests" section

**Management path** (`isManagement === true`, not admin):
- Pending requests queue with approve/reject only
- No analytics, no personal sections
- Cleaner than before — the old version showed a "Your Current Schedule" summary and "My Requests" history section because `isReviewer` only gated the form, not the personal data sections. These are now removed for management too.

**Field staff path** (everyone else):
- Current schedule summary (day pills, strikethrough = off day)
- Submission form with mode selector (add/drop/full rework)
- "My Requests" history with cancel button for pending requests

---

### `ScheduleAnalytics` component (new, internal to `ScheduleChanges.tsx`)

Derives all stats from the `allRequests` array passed as a prop. No additional API calls.

| Metric | How derived |
|---|---|
| Total / Pending / Approved / Rejected | Filter by `status` |
| Approval rate | `approved / (approved + rejected) * 100`, null if no reviewed requests yet |
| By request type | Count per `request_type` value |
| Top off days | From `days_to_drop` on drop_day requests + inferred off days from full_rework's `proposed_schedule` (days NOT in proposed = days being dropped) |

---

## Problems Encountered

**Management was silently seeing personal sections they shouldn't.** The old code used a single `isReviewer` flag to hide the submission form. But the "Your Current Schedule" summary and "My Requests" history sections were rendered unconditionally — they showed the management user's own off-days and their own schedule change history (which would always be empty since management can't submit requests). The three-branch render approach eliminates this entirely; management and admin now render completely different JSX trees.

---

## Key Takeaways

- A single `isReviewer` flag is not sufficient when reviewer roles need meaningfully different views from each other. Admin ≠ Management even when both "review" — one needs oversight analytics, the other needs the queue.
- Hiding a form with a conditional does not hide all the state that feeds that form. When the personal sections share data-loading logic with the form, removing the form still loads and displays that data elsewhere on the page.
- Always ask: does this role have a personal stake in this page's subject matter? If not, none of the personal sections should render — not just the action buttons.
