# ADR-020: Remove Admin Access to Schedule Page and Split ScheduleChanges by Role

**Date:** 2026-04-14
**Status:** Accepted
**Area:** Role Access / Frontend

---

## Context

After the role architecture restructure (ADR-016), the admin role retained access to the `/schedule` page and received the same `/schedule-changes` view as management. Two problems emerged:

1. `/schedule` is a personal schedule viewer and PTO request tool for field staff. Admins are not dispatched and have no personal schedule — the page was meaningless to them and implied they could request their own time off.

2. `/schedule-changes` was gated on a single `isReviewer` flag. The form was hidden for reviewers, but the "Your Current Schedule" and "My Requests" sections still rendered. For management and admin, these sections pulled data that would always be empty (they cannot submit schedule change requests) and created confusion about who the page was for. Additionally, admin has an oversight function that management does not — they need to see request volume, approval rates, and trends, not just the queue.

---

## Decision

### 1. Remove admin from the Schedule route and nav link

`/schedule` is restricted to `['driver', 'walker', 'trainer', 'trainee', 'management']`. Admin is excluded at both the route level (`allowedRoles`) and the navbar (`canAccessSchedule` predicate).

Management retains access because they legitimately use the page to view any employee's schedule via the employee dropdown and check the Available Staff panel for future dates. These are management functions. Field staff use it for their own calendar. Admin has neither of these needs — dispatch and availability data is accessible through the Dispatch page.

### 2. Split ScheduleChanges into three distinct render branches

| Role | View |
|---|---|
| Admin | Analytics panel + pending queue |
| Management | Pending queue only |
| Field staff | Personal schedule summary + submission form + own history |

The three branches share no JSX. There is no risk of personal sections leaking into reviewer views.

### 3. Admin analytics panel covers

- Stat cards: total requests, pending, approved, rejected
- Approval rate as a progress bar (suppressed when no requests have been reviewed yet)
- Breakdown by request type (add_day / drop_day / full_rework)
- Top 3 most-requested days off, derived from `days_to_drop` and inferred from full_rework's `proposed_schedule`

All derived client-side from the same `/schedule-change-requests/` response — no additional endpoint needed.

---

## Consequences

**Positive:**
- Admin no longer sees irrelevant personal schedule UI.
- Management no longer sees empty personal data sections.
- Admin gets organizational insight that informs staffing decisions (which days have the most churn, approval throughput).
- Each role sees exactly what they need — no more, no less.

**Tradeoff:**
- The analytics are computed from the pending requests list only, because `/schedule-change-requests/` returns only pending. Historical approved/rejected counts will show 0 until a dedicated all-statuses endpoint is added. This is documented in the analytics component via the `loadAllRequests` comment in the source.

---

## Broader Principle

**Hiding a form is not the same as removing a page section.** When personal data sections (schedule summary, request history) share a page with a reviewer section, gating only the action buttons leaves the personal context visible to roles that have no use for it. The correct fix is branched rendering — each role gets a completely different JSX tree, not a conditionally-hidden subset of a shared tree.

This applies generally: if two roles have meaningfully different purposes for a page, they should render different components, not the same component with different pieces hidden.
