# ADR-014: Assignment Change Requests

**Date:** 2026-04-10  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Walkers and trainers have no formal mechanism to request a truck reassignment for a given day. Verbal requests to dispatch are untraceable, easy to miss, and produce no audit trail. A lightweight request/approval workflow is needed that fits into the existing dispatch override model without auto-mutating live assignments.

---

## Decision

Introduce a first-class `AssignmentChangeRequest` model and REST API. Workers submit requests through their Preferences page; dispatch reviews and acts on them from the Dashboard. Approval is a two-step process: the system marks the request approved and notifies the employee, then the dispatcher manually performs the truck swap via the existing drag-and-drop interface.

---

## Rationale

### Why not auto-swap on approval?

Auto-swapping would require the system to choose a destination truck on the worker's behalf, which reintroduces the same complexity as dispatch (fav/ban weights, crew balance, caps). Approval is a human signal that the request is valid — the actual swap decision still belongs to dispatch who has full situational context.

### Why one pending request per employee per date?

Multiple concurrent requests for the same date from the same employee create confusing queue state with no clear winner. One-at-a-time keeps the queue clean and ensures dispatch is acting on the current preference, not a stale one.

### Why DELETE for self-cancel instead of a cancelled status?

A `cancelled` status adds a third terminal state with no operational value — it would only add clutter to the employee's history list and the dispatch queue. Hard-deleting a pending request is safe because no downstream records depend on it.

### Why is reviewed_by nullable?

The reviewer is resolved by matching discord_id from the JWT to an Employee record. If that lookup fails (test users, service accounts), the approval should still succeed — `reviewed_by` is audit metadata, not a hard dependency.

---

## Consequences

- Dispatch queue is now a single card aggregating three request types (time-off, off-day, reassignment) — one place to review all pending worker requests.
- Actual truck swaps still require a manual dispatcher action after approval; no automation risk.
- Workers get a status-visible history of their own requests in Preferences, reducing "did dispatch see my request?" questions.
- The `assignment_change_requests` table grows over time; old resolved rows are never purged automatically. A future cleanup job or retention policy may be needed.
