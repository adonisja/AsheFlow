# Engineering Journal: April 2, 2026 (Evening Session)

**Session Start Time**: April 2, 2026, 07:06 PM EST (GMT-5, NYC)
**Session End Time**: April 2, 2026, 11:12 PM EST (GMT-5, NYC)

## Goal for the Session
Build the services layer, truck_assignments router, and assignment_members router — including enforcement of the two core dispatch business rules: consecutive truck prevention and ban list enforcement.

## Problems Encountered

### 1. Business rules placed in wrong router
**Initial assumption:** Consecutive and ban checks belong in `truck_assignments` router.
**Correction:** `truck_assignments` only creates a truck+date record — no employees yet. Business rules belong in `assignment_members` router, where employees are actually assigned.

### 2. Variable name mismatch in endpoint
**Error:** Used `member.employee_id` instead of `assignment_member.employee_id`
**Cause:** Copy-paste confusion between parameter name and variable name.
**Fix:** Always use the exact parameter name declared in the function signature.

### 3. Wrong schema imported in router
**Error:** Imported `AssignmentMemberUpdate` which didn't exist in schema file.
**Fix:** Only import what exists. Add `Update` schema when needed.

### 4. `assignment_member.truck_assignment_id` field name mismatch
**Error:** Used `truck_assignment_id` but schema field is named `assignment_id`.
**Fix:** Field names in router must match exactly what's defined in the Pydantic schema.

## Solutions & Procedures

### Services Layer Created
```
backend/app/services/
├── __init__.py
└── dispatch.py       # check_consecutive_assignment, check_ban_relationship
```

**`check_consecutive_assignment(employee_id, truck_id, target_date, db)`**
- Joins `assignment_members` → `truck_assignments` on `assignment_id`
- Filters: truck_id matches, date = yesterday, employee_id matches
- Returns `True` if employee was on that truck yesterday

**`check_ban_relationship(employee_id, target_employee_id, db)`**
- Queries `employee_relationships` for `relationship_type = "ban"`
- Uses `or_(and_(...), and_(...))` to check both directions (A→B or B→A)
- Returns `True` if a ban exists between the two employees

### Routers Built
- `truck_assignments.py` — CRUD for truck+date assignments (no business rules)
- `assignment_members.py` — Add/remove employees from assignments with full rule enforcement

### Assignment Member POST Logic (4-step pattern)
```
1. Fetch assignment → verify exists, get truck_id + date
2. check_consecutive_assignment → 409 if employee was on this truck yesterday
3. Fetch existing members → loop → check_ban_relationship each → 409 if any banned pair
4. Insert new member → return
```

### Hard Delete on Assignment Members
Removing someone from an assignment uses a real `db.delete()` — not a soft delete. Reassignment is a legitimate operation. Completed assignment history is preserved in the `truck_assignments` record itself.

## Verified Working
- `POST /assignments` → creates truck+date record
- `POST /assignment-members` → enforces consecutive + ban rules
- Ban list `409` confirmed via direct DB insert + Postman test

## Key Architectural Decisions

1. **Services layer for business logic**: Rules that require DB queries and complex conditions live in `services/dispatch.py`, not in routers. Keeps routers thin and logic testable/reusable.
2. **409 Conflict for business rule violations**: Semantically correct — the request is valid JSON but conflicts with existing data/rules. Not a `400 Bad Request` (which implies malformed input).
3. **Hard delete for assignment members**: Unlike employees/trucks, removing someone from an assignment is not a historical event — it's a correction. Hard delete is appropriate here.

## Key Takeaways
* Business rules belong in the services layer, not routers. Router calls service, service enforces rules.
* The `or_(and_(...), and_(...))` pattern handles bidirectional relationship checks.
* `409 Conflict` is the correct status code for valid requests that violate business rules.
* Always verify the assignment exists before running business checks — fail fast with 404 before doing unnecessary work.
* Hard delete vs soft delete depends on the nature of the operation — corrections vs historical records.
