# ADR-085 — Bumped Trainee Data Loss and Tenant Isolation Fix

**Date:** 2026-05-09  
**Status:** Accepted  
**Area:** `backend/app/routers/dispatch.py` — manual assignment / trainee bump path

---

## Context

When dispatch manually assigns a trainee to a truck that already has a trainee, the system "bumps" the existing trainee and tries to find them a new slot. Two bugs existed in this path:

### Bug 1 — Missing company_id filter (tenant isolation)

The query that fetches all truck assignments to search for a fallback slot did not filter by `company_id`:

```python
# Before (broken):
all_truck_assignments = db.query(TruckAssignment).filter(
    TruckAssignment.date == assignment_in.date
).all()
```

In a multi-tenant system this would search every company's trucks for that date, potentially placing a bumped trainee on another company's truck. This is the same class of bug as the `GET /employees` leak (ADR-084): a query that predated multi-tenancy and was never updated.

### Bug 2 — Silent data loss when no fallback slot exists

When both fallback search loops failed to find a slot, the bumped trainee's `AssignmentMember` row was already deleted (line 281) and no replacement was created. The trainee had no assignment for that date, but:

- No exception was raised
- The response to the caller showed the incoming trainee was successfully placed
- The only signal was a notification to oversight staff — which could easily be missed

The trainee was effectively lost from the dispatch record with no trace in the assignment tables.

---

## Decision

Two targeted fixes in the bump block:

### Fix 1 — Add company_id to the fallback search

```python
all_truck_assignments = db.query(TruckAssignment).filter(
    TruckAssignment.date == assignment_in.date,
    TruckAssignment.company_id == caller.company_id,   # ← added
).all()
```

### Fix 2 — Employee lookups in the no-fallback path scoped to company

The `bumped_emp` and `incoming_emp` lookups in the notification block were also unscoped. Added `Employee.company_id == caller.company_id` to both.

The no-fallback path itself (notifications to oversight + trainee) is the correct behavior when there is genuinely no slot — the trainee cannot be placed without a human decision. The fix ensures the query that determines "no slot exists" only considers the correct company's trucks.

---

## What Was NOT Changed

The no-fallback notification path is intentionally kept. When there truly is no open truck slot, the system cannot silently place the trainee — that would require inventing a truck assignment. The correct behavior is:
1. Delete the bumped trainee's old slot
2. Send notifications to oversight and the trainee
3. Require manual intervention

This is data loss in the sense that the trainee loses their assignment, but it is unavoidable without creating an invalid state. The fix ensures the decision of "no slot" is evaluated only against the correct company's data.

---

## Consequences

- The fallback search is now correctly scoped to the caller's company — no cross-tenant truck access
- Employee lookups in the notification path are also company-scoped
- `ROLE_TRAINEE` constant used instead of the string literal `"trainee"` in the new `AssignmentMember` — consistent with the rest of the file
- Behavior is otherwise identical — no change to the notification messages or the two-priority fallback strategy
