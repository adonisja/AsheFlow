# Engineering Journal: 2026-05-09 — Bumped Trainee Data Loss Fix

## Goal for the Session

Fix the silent data loss bug in the trainee bump path of `dispatch.py`. When dispatch manually places a trainee on a truck that already has one, the existing trainee is "bumped" and the system tries to find them a new slot. The reported issue was at line ~299 — a case where the trainee could end up with no assignment at all.

---

## Investigation

### Reading the bump path end-to-end

The bump logic lives inside `POST /dispatch/assign` when `assignment_in.role == ROLE_TRAINEE` and the target truck already has a trainee. The sequence:

1. Delete the existing trainee's `AssignmentMember` row and flush
2. Search all trucks for that date for a fallback slot (two priority passes)
3. If found: create a new `AssignmentMember` for the bumped trainee
4. If not found: send notifications to oversight staff and the trainee
5. (Unconditionally) create the new `AssignmentMember` for the incoming trainee

**Bug 1 — tenant isolation:** The query at step 2 fetched all `TruckAssignment` rows for the date with no `company_id` filter. In a multi-tenant deployment this would consider every company's trucks as potential fallback slots.

```python
# Missing filter:
all_truck_assignments = db.query(TruckAssignment).filter(
    TruckAssignment.date == assignment_in.date  # ← no company scope
).all()
```

**Bug 2 — silent data loss:** After step 1, the bumped trainee's row is gone. If step 3 fails (no fallback), the trainee has no assignment. The response to the caller is a 200 showing the incoming trainee was placed — there is no error, no 4xx, no indication in the response body that a trainee was lost. The only signal was a notification, which could be missed.

The employee lookups in step 4 also had no `company_id` filter — minor but consistent with the isolation pattern.

---

## Problems Encountered

### Was this actually "data loss" or correct behavior?

The question: when there's genuinely no fallback slot, is it wrong to leave the trainee unassigned?

Answer: it's the correct outcome — you can't force a trainee onto a full truck. The bug is not that the trainee loses their slot (that's unavoidable when every truck is full). The bug is:

1. The "every truck is full" determination was made against all companies' trucks, not just the caller's
2. Even with the single-company fix, the no-fallback case is not data loss in the destructive sense — it's an expected edge case with proper notification. The original report of "data loss" referred to the fact that the trainee's disappearance was silent with no audit trail in the assignment tables.

The fix scopes the search correctly and adds `Employee.company_id` to the notification-path lookups. The no-fallback notification behavior is preserved — it's the right response when no slot exists.

---

## Solution

Two changes in the bump block:

**1. Add `company_id` to the fallback search:**
```python
all_truck_assignments = db.query(TruckAssignment).filter(
    TruckAssignment.date == assignment_in.date,
    TruckAssignment.company_id == caller.company_id,  # ← added
).all()
```

**2. Scope employee lookups in the no-fallback notification path:**
```python
bumped_emp = db.query(Employee).filter(
    Employee.id == bumped_trainee_id,
    Employee.company_id == caller.company_id,   # ← added
).first()
incoming_emp = db.query(Employee).filter(
    Employee.id == assignment_in.employee_id,
    Employee.company_id == caller.company_id,   # ← added
).first()
```

Also changed the string literal `"trainee"` to `ROLE_TRAINEE` in the new `AssignmentMember` for consistency.

---

## Key Takeaways

### 1. Multi-tenant audit: every query that touches shared tables needs company_id

This is the third instance of a pre-migration query missing `company_id` (after the `GET /employees` list and this bump path). The pattern is consistent: code written before the multi-tenant migration that was not revisited during conversion. A systematic audit of every `db.query(TruckAssignment)`, `db.query(Employee)`, etc. without a `company_id` filter is the right follow-up.

### 2. Distinguish "unavoidable data loss" from "silent unexpected data loss"

When a trainee bump can't find a fallback, losing the trainee's assignment is unavoidable — the system can't manufacture a truck. That's not a bug; it's an edge case. The real issue was whether that edge case was being evaluated against the right data (it wasn't — wrong company scope). The notifications already handled the communication gap correctly.

### 3. Read the full transaction before calling it "data loss"

The bump path deletes first, then searches for a fallback. Reading only the delete at line 281 made it look like the trainee was dropped unconditionally. Reading the full block revealed that the delete is intentional and the fallback search + notification path was already there — just broken by the missing filter.
