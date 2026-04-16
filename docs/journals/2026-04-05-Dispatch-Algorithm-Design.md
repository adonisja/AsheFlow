# Engineering Journal: April 5, 2026

**Session Start Time**: April 3, 2026, ~11:00 PM EST (GMT-5, NYC)
**Session End Time**: April 5, 2026, 9:10 PM EST (GMT-5, NYC)

## Goal for the Session
Fix seed script FK violation, update the fav relationship system to be role-aware, and design the dispatch algorithm from first principles.

---

## Problems Encountered

### 1. ForeignKeyViolation on Seed Script
**Cause:** Seed script deleted `trucks` before `truck_assignments`, which still held FK references to trucks. PostgreSQL enforced referential integrity and rejected the delete.
**Fix:** Reordered deletions to children-before-parents:
```
EmployeeRelationship → EmployeeOffDay → AssignmentMember → TruckAssignment → Truck → Employee
```
**Rule:** Deletion order is always the reverse of creation (dependency resolution) order.

### 2. Missing imports in seed.py
**Cause:** `TruckAssignment` and `AssignmentMember` were used in the deletion block but never imported.
**Fix:** Added both imports at the top of the file.

### 3. Stale seed data after fav system redesign
**Cause:** After redesigning the fav limits to be role-specific, existing seed data had relationships that violated the new rules (e.g. drivers with 2 random favs, potentially both captains).
**Fix:** Cleared all seed data and re-seeded with role-aware generation logic.

### 4. `captain` vs `trainer` role inconsistency
**Cause:** Seed script used `role="trainer"` and the model's CheckConstraint used `trainer`, but `FAV_LIMITS` dict in the router still used `"captain"` as a key — a holdover from an earlier draft.
**Fix:** Standardized all references to `trainer`. Updated router, seed variable name (`CAPTAIN_NAMES` → `TRAINER_NAMES`), and `FAV_LIMITS` keys.

### 5. Variable scope bug — `ban_count` defined inside `else`, referenced outside
**Cause:** Both `existing_count` and `ban_count` were defined inside their respective `if/else` branches but the limit checks were written outside the branches, causing a `NameError` at runtime when the wrong branch ran.
**Fix:** Moved each limit check inside its own branch so variables are only used where they're defined.

### 6. Nested dict lookup syntax error
**Cause:** `FAV_LIMITS[db_employee.role[db_target.role]]` tried to index into the role *string* using another string as a key — Python strings don't support that. Throws `TypeError`.
**Fix:** Two separate bracket lookups: `FAV_LIMITS[db_employee.role][db_target.role]` — first lookup returns the inner dict, second returns the integer limit.

### 7. Consecutive truck check logic was incorrect
**Cause:** Original `was_on_truck_yesterday()` used `date == yesterday` (calendar day minus 1). If an employee was off the previous calendar day, the check found nothing and allowed a repeat truck assignment.
**Fix:** Must query the employee's **most recent actual assignment** regardless of date, then check if it was the same truck. Design updated for the dispatch service.

---

## Solutions & Procedures

### Role-aware fav limit enforcement (router)
Replaced flat max-2 check with a JOIN query that counts existing favs of the same target role, then compares against `FAV_LIMITS[employee_role][target_role]`.

Ban relationships kept a simple flat max-2 check — no role distinction needed.

### Updated seed.py relationship generation
Instead of sampling 0–2 random employees, now iterates over `FAV_LIMITS[emp.role]` and for each target role, samples 0–N from that role's pool. Respects role-specific limits exactly.

### Dispatch algorithm designed (not yet implemented)
Full algorithm design reached through Socratic discussion. See ADR-001 for the complete decision record.

---

## Key Takeaways

* Deletion order must be children-before-parents — the exact reverse of table creation order.
* Variables defined inside an `if/else` branch only exist if that branch ran. Keep the check inside the branch.
* Two chained dict lookups (`d[a][b]`) is not the same as one nested lookup (`d[a[b]]`). The first does two sequential key lookups; the second tries to subscript a string.
* "Consecutive" in a business rule means "their last actual workday" — not "calendar yesterday." Always query by most recent record, not by date arithmetic.
* Role standardization must be consistent across models, routers, seed scripts, and constraint dicts. One missed reference causes silent bugs.
* ADRs should be written as decisions are made — not retroactively. Start them early.
