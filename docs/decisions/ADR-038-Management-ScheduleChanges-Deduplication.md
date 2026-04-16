# ADR-038: Remove Management Access to `/schedule-changes`

**Date:** 2026-04-16  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Management had access to two routes that both surfaced a schedule change request approval queue:

- `/schedule` → `ScheduleManagementView` — 4-week availability heatmap, pending PTO approvals, **and** pending schedule change request approvals with age badges and type filtering.
- `/schedule-changes` → management branch of `ScheduleChanges` — pending schedule change request approvals only, no heatmap, no age badges, no PTO queue.

The `/schedule-changes` management view was a narrower, less capable duplicate of work already present on `/schedule`. Management had no personal stake in the submission side of `/schedule-changes` (they don't submit schedule change requests themselves), so the entire page provided nothing `/schedule` didn't already cover.

Additionally, the `dispatch` role was missing from the `/schedule-changes` allowlist despite dispatch staff being field employees with a weekly schedule who can legitimately submit schedule change requests.

---

## Decision

Remove `management` from `/schedule-changes` `allowedRoles` and `canAccessScheduleChanges`. Add `dispatch` to both.

The approval queue for schedule change requests lives in `ScheduleManagementView` on `/schedule` — that is management's canonical review surface for all schedule-related requests. No functionality is lost; the duplicate entry point is removed.

`dispatch` is added because they are dispatched employees with a recurring schedule. They have the same legitimate need to submit add/drop/rework requests as any other field staff role.

---

## Consequences

**Positive:**
- Management's navbar loses the redundant "Schedule Changes" link.
- Management navigating directly to `/schedule-changes` receives an Access Denied response instead of a duplicate queue.
- Dispatch can now submit their own schedule change requests.
- The management branch in `ScheduleChanges.tsx` is now unreachable dead code — it can be removed in a future cleanup pass.

**Negative / Trade-offs:**
- None. The approval capability is fully preserved on `/schedule`. No data or action is lost.

---

## Learnings & Growth

See LEARNING_GUIDE.md — "Duplicate entry points signal a missing consolidation decision."
